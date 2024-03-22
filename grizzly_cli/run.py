import sys
import os

from typing import Iterable, List, Dict, Any, Callable, Optional, TextIO, Union, cast
from argparse import Namespace as Arguments
from platform import node as get_hostname
from datetime import datetime
from pathlib import Path
from contextlib import suppress

from jinja2 import Environment
from jinja2.lexer import Token, TokenStream
from jinja2_simple_tags import StandaloneTag
from behave.parser import parse_feature
from behave.model import Scenario, Step, Row

import grizzly_cli
from .utils import (
    find_variable_names_in_questions,
    ask_yes_no, get_input,
    distribution_of_users_per_scenario,
    requirements,
    find_metadata_notices,
    parse_feature_file,
    logger,
)
from .argparse import ArgumentSubParser
from .argparse.bashcompletion import BashCompletionTypes


class OnlyScenarioTag(StandaloneTag):
    tags = {'scenario'}

    def preprocess(
        self, source: str, name: Optional[str], filename: Optional[str] = None
    ) -> str:
        self._source = source
        return cast(str, super().preprocess(source, name, filename))

    def render(self, scenario: str, feature: str) -> str:
        feature_file = Path(feature)

        # check if relative to parent feature file
        if not feature_file.exists():
            feature_file = (self.environment.feature_file.parent / feature).resolve()

        feature_content = feature_file.read_text()
        feature_lines = feature_content.splitlines()
        parsed_feature = parse_feature(feature_content, filename=feature_file.as_posix())

        buffer: List[str] = []

        for parsed_scenario in cast(List[Scenario], parsed_feature.scenarios):
            if parsed_scenario.name != scenario:
                continue

            scenario_line = feature_lines[parsed_scenario.line - 1]
            step_indent = (len(scenario_line) - len(scenario_line.lstrip())) * 2

            for index, parsed_step in enumerate(cast(List[Step], parsed_scenario.steps)):
                step_line = f'{parsed_step.keyword} {parsed_step.name}'

                # all lines except first, should have indentation based on how `Scenario:` had been indented
                if index > 0:
                    step_line = f'{" " * step_indent}{step_line}'

                buffer.append(step_line)

                extra_indent = int((step_indent / 2) + step_indent)

                # include step text if set
                if parsed_step.text is not None:
                    buffer.append(f'{" " * extra_indent}"""')
                    for text_line in parsed_step.text.splitlines():
                        buffer.append(f'{" " * (extra_indent)}{text_line}')
                    buffer.append(f'{" " * extra_indent}"""')

                # include step table if set
                if parsed_step.table is not None:
                    header_line = ' | '.join(parsed_step.table.headings)
                    buffer.append(f'{" " * extra_indent}| {header_line} |')
                    for row in cast(List[Row], parsed_step.table.rows):
                        row_line = ' | '.join(row.cells)
                        buffer.append(f'{" " * extra_indent}| {row_line} |')

        return '\n'.join(buffer)

    def filter_stream(self, stream: TokenStream) -> Union[TokenStream, Iterable[Token]]:
        """Everything outside of `{% scenario ... %}` should be treated as "data", e.g. plain text."""
        in_scenario = False
        in_variable = False
        in_block_comment = False

        variable_begin_pos = -1
        variable_end_pos = 0
        block_begin_pos = -1
        block_end_pos = 0
        source_lines = self._source.splitlines()

        for token in stream:
            if token.type == 'block_begin' and stream.current.value in self.tags:
                in_scenario = True
                current_line = source_lines[token.lineno - 1].lstrip()
                in_block_comment = current_line.startswith('#')
                block_begin_pos = self._source.index(token.value, block_begin_pos + 1)

            if not in_scenario:
                if token.type == 'variable_end':
                    # Find variable end in the source
                    variable_end_pos = self._source.index(token.value, variable_begin_pos)
                    # Extract the variable definition substring and use as token value
                    token_value = self._source[variable_begin_pos:variable_end_pos + len(token.value)]
                    in_variable = False
                elif token.type == 'variable_begin':
                    # Find variable start in the source
                    variable_begin_pos = self._source.index(token.value, variable_begin_pos + 1)
                    in_variable = True
                else:
                    token_value = token.value

                if in_variable:
                    # While handling in-variable tokens, withhold values until
                    # the end of the variable is reached
                    continue

                filtered_token = Token(token.lineno, 'data', token_value)
            else:
                if token.type == 'block_end' and in_block_comment:
                    in_block_comment = False
                    block_end_pos = self._source.index(token.value, block_begin_pos)
                    token_value = self._source[block_begin_pos:block_end_pos + len(token.value)]
                    filtered_token = Token(token.lineno, 'data', token_value)
                elif in_block_comment:
                    continue
                else:
                    filtered_token = token

            yield filtered_token

            if in_scenario and token.type == 'block_end':
                in_scenario = False


def create_parser(sub_parser: ArgumentSubParser, parent: str) -> None:
    # grizzly-cli ... run ...
    run_parser = sub_parser.add_parser('run', description='execute load test scenarios specified in a feature file.')
    run_parser.add_argument(
        '--verbose',
        action='store_true',
        required=False,
        help=(
            'changes the log level to `DEBUG`, regardless of what it says in the feature file. gives more verbose logging '
            'that can be useful when troubleshooting a problem with a scenario.'
        )
    )
    run_parser.add_argument(
        '-T', '--testdata-variable',
        action='append',
        type=str,
        required=False,
        help=(
            'specified in the format `<name>=<value>`. avoids being asked for an initial value for a scenario variable.'
        )
    )
    run_parser.add_argument(
        '-y', '--yes',
        action='store_true',
        default=False,
        required=False,
        help='answer yes on any questions that would require confirmation',
    )
    run_parser.add_argument(
        '-e', '--environment-file',
        type=BashCompletionTypes.File('*.yaml', '*.yml'),
        required=False,
        default=None,
        help='configuration file with [environment specific information](/grizzly/framework/usage/variables/environment-configuration/)',
    )
    run_parser.add_argument(
        '--csv-prefix',
        nargs='?',
        const=True,
        default=None,
        help='write log statistics to CSV files with specified prefix, if no value is specified the description of the gherkin Feature tag will be used, suffixed with timestamp',
    )
    run_parser.add_argument(
        '--csv-interval',
        type=int,
        default=None,
        required=False,
        help='interval that statistics is collected for CSV files, can only be used in combination with `--csv-prefix`',
    )
    run_parser.add_argument(
        '--csv-flush-interval',
        type=int,
        default=None,
        required=False,
        help='interval that CSV statistics is flushed to disk, can only be used in combination with `--csv-prefix`',
    )
    run_parser.add_argument(
        '-l', '--log-file',
        type=str,
        default=None,
        required=False,
        help='save all `grizzly-cli` run output in specified log file',
    )
    run_parser.add_argument(
        '--log-dir',
        type=str,
        default=None,
        required=False,
        help='log directory suffix (relative to `requests/logs`) to save log files generated in a scenario',
    )
    run_parser.add_argument(
        '--dump',
        nargs='?',
        default=None,
        const=True,
        help=(
            'Dump parsed contents of file, can be useful when including scenarios from other feature files. If no argument is specified it '
            'will be dumped to stdout, the argument is treated as a filename'
        ),
    )
    run_parser.add_argument(
        'file',
        nargs='+',
        type=BashCompletionTypes.File('*.feature'),
        help='path to feature file with one or more scenarios',

    )

    if run_parser.prog != f'grizzly-cli {parent} run':  # pragma: no cover
        run_parser.prog = f'grizzly-cli {parent} run'


@requirements(grizzly_cli.EXECUTION_CONTEXT)
def run(args: Arguments, run_func: Callable[[Arguments, Dict[str, Any], Dict[str, List[str]]], int]) -> int:
    # always set hostname of host where grizzly-cli was executed, could be useful
    environ: Dict[str, Any] = {
        'GRIZZLY_CLI_HOST': get_hostname(),
        'GRIZZLY_EXECUTION_CONTEXT': grizzly_cli.EXECUTION_CONTEXT,
        'GRIZZLY_MOUNT_CONTEXT': grizzly_cli.MOUNT_CONTEXT,
    }

    environment = Environment(autoescape=False, extensions=[OnlyScenarioTag])
    feature_file = Path(args.file)
    original_feature_content = feature_file.read_text()
    feature_lock_file = feature_file.parent / f'{feature_file.stem}.lock{feature_file.suffix}'

    try:
        # during execution, create a temporary .lock.feature file that will be removed when done
        template = environment.from_string(original_feature_content)
        environment.extend(feature_file=feature_file)
        feature_content = template.render()
        feature_lock_file.write_text(feature_content)

        if args.dump:
            output: TextIO
            if isinstance(args.dump, str):
                output = Path(args.dump).open('w+')
            else:
                output = sys.stdout

            print(feature_content, file=output)

            return 0

        args.file = feature_lock_file.as_posix()

        variables = find_variable_names_in_questions(args.file)
        questions = len(variables)
        manual_input = False

        if questions > 0 and not getattr(args, 'validate_config', False):
            logger.info(f'feature file requires values for {questions} variables')

            for variable in variables:
                name = f'TESTDATA_VARIABLE_{variable}'
                value = os.environ.get(name, '')
                while len(value) < 1:
                    value = get_input(f'initial value for "{variable}": ')
                    manual_input = True

                environ[name] = value

            logger.info('the following values was provided:')
            for key, value in environ.items():
                if not key.startswith('TESTDATA_VARIABLE_'):
                    continue
                logger.info(f'{key.replace("TESTDATA_VARIABLE_", "")} = {value}')

            if manual_input:
                ask_yes_no('continue?')

        notices = find_metadata_notices(args.file)

        if len(notices) > 0:
            if args.yes:
                output_func = cast(Callable[[str], None], logger.info)
            else:
                output_func = ask_yes_no

            for notice in notices:
                output_func(notice)

        if args.environment_file is not None:
            environment_file = os.path.realpath(args.environment_file)
            environ.update({'GRIZZLY_CONFIGURATION_FILE': environment_file})

        if args.log_dir is not None:
            environ.update({'GRIZZLY_LOG_DIR': args.log_dir})

        if not getattr(args, 'validate_config', False):
            distribution_of_users_per_scenario(args, environ)

        run_arguments: Dict[str, List[str]] = {
            'master': [],
            'worker': [],
            'common': [],
        }

        if args.verbose:
            run_arguments['common'] += ['--verbose', '--no-logcapture', '--no-capture', '--no-capture-stderr']

        if args.csv_prefix is not None:
            if args.csv_prefix is True:
                parse_feature_file(args.file)
                if grizzly_cli.FEATURE_DESCRIPTION is None:
                    raise ValueError('feature file does not seem to have a `Feature:` description to use as --csv-prefix')

                csv_prefix = grizzly_cli.FEATURE_DESCRIPTION.replace(' ', '_')
                timestamp = datetime.now().astimezone().strftime('%Y%m%dT%H%M%S')
                setattr(args, 'csv_prefix', f'{csv_prefix}_{timestamp}')

            run_arguments['common'] += [f'-Dcsv-prefix="{args.csv_prefix}"']

            if args.csv_interval is not None:
                run_arguments['common'] += [f'-Dcsv-interval={args.csv_interval}']

            if args.csv_flush_interval is not None:
                run_arguments['common'] += [f'-Dcsv-flush-interval={args.csv_flush_interval}']

        return run_func(args, environ, run_arguments)
    finally:
        with suppress(FileNotFoundError):
            feature_lock_file.unlink()
