from __future__ import annotations

import sys
import os
import re

from typing import Iterable, List, Dict, Any, Callable, Optional, TextIO, Union, Set, cast
from argparse import Namespace as Arguments
from platform import node as get_hostname
from datetime import datetime
from pathlib import Path
from contextlib import suppress
from textwrap import dedent

from jinja2 import Environment
from jinja2.lexer import Token, TokenStream
from jinja2_simple_tags import StandaloneTag
from behave.parser import parse_feature
from behave.model import Scenario

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


class ScenarioTag(StandaloneTag):
    tags = {'scenario'}

    def preprocess(
        self, source: str, name: Optional[str], filename: Optional[str] = None
    ) -> str:
        self._source = source

        return cast(str, super().preprocess(source, name, filename))

    @classmethod
    def get_scenario_text(cls, name: str, file: Path) -> str:
        content = file.read_text()

        content_skel = re.sub(r'\{%.*%\}', '', content)
        content_skel = re.sub(r'\{\$.*\$\}', '', content_skel)

        assert len(content.splitlines()) == len(content_skel.splitlines()), 'oops, there is not a 1:1 match between lines!'

        feature = parse_feature(content_skel, filename=file.as_posix())
        scenarios = cast(List[Scenario], feature.scenarios)
        lines = content.splitlines()

        for scenario_index, scenario in enumerate(scenarios):
            if scenario.name == name:
                break

        # check if there are scenarios after our scenario in the source
        next_scenario: Optional[Scenario] = None
        with suppress(IndexError):
            next_scenario = scenarios[scenario_index + 1]

        if next_scenario is None:  # last scenario, take everything until the end
            scenario_lines = lines[scenario.line:]
        else:  # take everything up until where the next scenario starts
            scenario_lines = lines[scenario.line:next_scenario.line - 1]
            if scenario_lines[-1] == '':  # if last line is an empty line, lets remove it
                scenario_lines.pop()

        # remove any scenario text/comments
        if scenario_lines[0].strip() == '"""':
            try:
                offset = scenario_lines[1:].index(scenario_lines[0]) + 1 + 1
            except:
                offset = 0

            scenario_lines = scenario_lines[offset:]

        # first line can have incorrect indentation
        scenario_lines[0] = dedent(scenario_lines[0])

        return '\n'.join(scenario_lines)

    def render(self, scenario: str, feature: str, **variables: str) -> str:
        feature_file = Path(feature)

        # check if relative to parent feature file
        if not feature_file.exists():
            feature_file = (self.environment.feature_file.parent / feature).resolve()

        scenario_content = self.get_scenario_text(scenario, feature_file)

        ignore_errors = getattr(self.environment, 'ignore_errors', False)

        # <!-- sub-render included scenario
        errors_unused: Set[str] = set()
        errors_undeclared: Set[str] = set()

        # tag has specified variables, so lets "render"
        for name, value in variables.items():
            variable_template = f'{{$ {name} $}}'
            if variable_template not in scenario_content:
                errors_unused.add(name)
                continue

            scenario_content = scenario_content.replace(variable_template, str(value))

        # look for sub-variables that has not been rendered
        if not ignore_errors:
            if '{$' in scenario_content and '$}' in scenario_content:
                matches = re.finditer(r'\{\$ ([^$]+) \$\}', scenario_content, re.MULTILINE)

                for match in matches:
                    errors_undeclared.add(match.group(1))

            if len(errors_undeclared) + len(errors_unused) > 0:
                scenario_identifier = f'{feature}#{scenario}'
                buffer_error: List[str] = []
                if len(errors_unused) > 0:
                    errors_unused_message = "\n  ".join(errors_unused)
                    buffer_error.append(f'the following variables has been declared in scenario tag but not used in {scenario_identifier}:\n  {errors_unused_message}')
                    buffer_error.append('')

                if len(errors_undeclared) > 0:
                    errors_undeclared_message = "\n  ".join(errors_undeclared)
                    buffer_error.append(f'the following variables was used in {scenario_identifier} but was not declared in scenario tag:\n  {errors_undeclared_message}')
                    buffer_error.append('')

                message = '\n'.join(buffer_error)
                raise ValueError(message)

        # check if we have nested statements (`{% .. %}`), and render again if that is the case
        if '{%' in scenario_content and '%}' in scenario_content:
            environment = self.environment.overlay()
            environment.feature_file = feature_file
            template = environment.from_string(scenario_content)
            scenario_content = template.render()
        # // -->

        return scenario_content

    def filter_stream(self, stream: TokenStream) -> Union[TokenStream, Iterable[Token]]:  # type: ignore[return]
        """Everything outside of `{% scenario ... %}` (and `{% if ... %}...{% endif %}`) should be treated as "data", e.g. plain text.

        Overloaded from `StandaloneTag`, must match method signature, which is not `Generator`, even though we yield
        the result instead of returning.
        """
        in_scenario = False
        in_block_comment = False
        in_condition = False
        in_variable = False

        variable_begin_pos = -1
        variable_end_pos = 0
        block_begin_pos = -1
        block_end_pos = 0
        source_lines = self._source.splitlines()

        for token in stream:
            if token.type == 'block_begin':
                if stream.current.value in self.tags:  # {% scenario ... %}
                    in_scenario = True
                    current_line = source_lines[token.lineno - 1].lstrip()
                    in_block_comment = current_line.startswith('#')
                    block_begin_pos = self._source.index(token.value, block_begin_pos + 1)
                elif stream.current.value in ['if', 'endif']:  # {% if <condition> %}, {% endif %}
                    in_condition = True

            if in_scenario:
                if token.type == 'block_end' and in_block_comment:
                    in_block_comment = False
                    block_end_pos = self._source.index(token.value, block_begin_pos)
                    token_value = self._source[block_begin_pos:block_end_pos + len(token.value)]
                    filtered_token = Token(token.lineno, 'data', token_value)
                elif in_block_comment:
                    continue
                else:
                    filtered_token = token
            elif in_condition:
                filtered_token = token
            else:
                if token.type == 'variable_begin':
                    # Find variable start in the source
                    variable_begin_pos = self._source.index(token.value, variable_begin_pos + 1)
                    in_variable = True
                    continue
                elif token.type == 'variable_end':
                    # Find variable end in the source
                    variable_end_pos = self._source.index(token.value, variable_begin_pos)
                    # Extract the variable definition substring and use as token value
                    token_value = self._source[variable_begin_pos:variable_end_pos + len(token.value)]
                    in_variable = False
                elif in_variable:  # Variable templates is yielded when the whole block has been processed
                    continue
                else:
                    token_value = token.value

                filtered_token = Token(token.lineno, 'data', token_value)

            yield filtered_token

            if token.type == 'block_end':
                if in_scenario:
                    in_scenario = False

                if in_condition:
                    in_condition = False


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
        '--dry-run',
        action='store_true',
        required=False,
        help='Will setup and run anything up until when locust should start. Useful for debugging feature files when developing new tests',
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

    environment = Environment(autoescape=False, extensions=[ScenarioTag])
    feature_file = Path(args.file)

    # during execution, create a temporary .lock.feature file that will be removed when done
    original_feature_lines = feature_file.read_text().splitlines()
    feature_lock_file = feature_file.parent / f'{feature_file.stem}.lock{feature_file.suffix}'

    try:
        buffer: List[str] = []
        remove_endif = False

        # remove if-statements containing variables (`{$ .. $}`)
        for line in original_feature_lines:
            stripped_line = line.strip()

            if stripped_line[:2] == '{%' and stripped_line[-2:] == '%}':
                if '{$' in stripped_line and '$}' in stripped_line and 'if' in stripped_line:
                    remove_endif = True
                    continue

                if remove_endif and 'endif' in stripped_line:
                    remove_endif = False
                    continue

            buffer.append(line)

        original_feature_content = '\n'.join(buffer)

        template = environment.from_string(original_feature_content)
        environment.extend(feature_file=feature_file, ignore_errors=False)
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

        if args.dry_run:
            environ.update({'GRIZZLY_DRY_RUN': 'true'})

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
        feature_lock_file.unlink(missing_ok=True)
