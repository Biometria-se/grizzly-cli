import argparse
import sys
import os
import subprocess
import re

from argparse import Action, SUPPRESS, ArgumentParser, Namespace, HelpFormatter, _SubParsersAction
from typing import Union, Sequence, Tuple
from types import MethodType
from typing import Any, Dict, List, Set, Optional, cast
from json import loads as jsonloads
from pathlib import Path
from argparse import Namespace as Arguments, ArgumentParser

from behave.parser import parse_file as feature_file_parser
from behave.model import Scenario, Step

__version__ = '0.0.0'

EXECUTION_CONTEXT = os.getcwd()

STATIC_CONTEXT = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'static')

MOUNT_CONTEXT = os.environ.get('GRIZZLY_MOUNT_CONTEXT', EXECUTION_CONTEXT)

PROJECT_NAME = os.path.basename(EXECUTION_CONTEXT)

SCENARIOS: Set[Scenario] = set()


def parse_feature_file(file: Optional[str]) -> None:
    if len(SCENARIOS) > 0:
        return

    if file is None:
        feature_files = list(Path(os.path.join(EXECUTION_CONTEXT, 'features')).rglob('*.feature'))
    else:
        feature_files = [Path(file)]

    for feature_file in feature_files:
        feature = feature_file_parser(feature_file)
        for scenario in feature.scenarios:
            SCENARIOS.add(scenario)


def list_images(args: Arguments) -> Dict[str, Any]:
    images: Dict[str, Any] = {}
    output = subprocess.check_output([
        f'{args.container_system}',
        'image',
        'ls',
        '--format',
        '{"name": "{{.Repository}}", "tag": "{{.Tag}}", "size": "{{.Size}}", "created": "{{.CreatedAt}}", "id": "{{.ID}}"}',
    ]).decode('utf-8')

    for line in output.split('\n'):
        if len(line) < 1:
            continue
        image = jsonloads(line)
        name = image['name']
        tag = image['tag']
        del image['name']
        del image['tag']

        version = {tag: image}

        if name not in images:
            images[name] = {'tags': {}}
        images[name]['tags'].update(version)

    return images

def get_default_mtu(args: Arguments) -> Optional[str]:
    try:
        output = subprocess.check_output([
            'docker',
            'network',
            'inspect',
            'bridge',
            '--format',
            '{{ json .Options }}',
        ]).decode('utf-8')

        lines = output.split('\n')
        line = lines[0]
        network_options = jsonloads(line)
        mtu = network_options.get('com.docker.network.driver.mtu', '1500')

        return cast(str, mtu)
    except:
        print(output)
        return None


def run_command(command: List[str], env: Optional[Dict[str, str]] = None) -> int:
    if env is None:
        env = os.environ.copy()

    process = subprocess.Popen(
        command,
        env=env,
        stderr=subprocess.STDOUT,
        stdout=subprocess.PIPE,
    )

    try:
        while process.poll() is None:
            stdout = process.stdout
            if stdout is None:
                break

            output = stdout.readline()
            if not output:
                break

            print(output.decode('utf-8').strip())

        process.terminate()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            process.kill()
        except Exception:
            pass

    process.wait()

    return process.returncode


class GrizzlyCliParser(ArgumentParser):
    def __init__(self, *args: Tuple[Any], **kwargs: Dict[str, Any]) -> None:
        super().__init__(*args, **kwargs)

        self.add_argument('--md-help', action=MarkdownHelpAction, help=argparse.SUPPRESS)

    def error_no_help(self, message: str) -> None:
        sys.stderr.write('{}: error: {}\n'.format(self.prog, message))
        sys.exit(2)

    def print_help(self) -> None:
        if self.formatter_class is not MarkdownFormatter:
            original_description = self.description
            original_actions = self._actions

            # code block "markers" are not really nice to have in cli help
            self.description = '\n'.join([line for line in self.description.split('\n') if '```' not in line])
            self.description = self.description.replace('\n\n', '\n')

            for action in self._actions:
                if action.help is not None:
                    # remove any markdown link markers
                    action.help = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', action.help)

        super().print_help()

        if self.formatter_class is not MarkdownFormatter:
            self.description = original_description
            self._actions = original_actions


class MarkdownHelpAction(Action):
    def __init__(
        self,
        option_strings: List[str],
        dest: str = SUPPRESS,
        default: str = SUPPRESS,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            default=default,
            nargs=0,
            **kwargs,
        )

    def __call__(
        self,
        parser: ArgumentParser,
        namespace: Namespace,
        values: Union[str, Sequence[Any], None],
        option_string: Optional[str] = None,
    ) -> None:
        self.print_help(parser)

        parser.exit()

    def print_help(self, parser: Union[ArgumentParser, _SubParsersAction], level: int = 0) -> None:
        def format_help_markdown(self):
            formatter = self._get_formatter()

            # description -- in markdown, should come before usage
            formatter.add_text('\n')
            formatter.add_text(self.description)

            # usage
            formatter.add_usage(self.usage, self._actions,
                                self._mutually_exclusive_groups)

            # positionals, optionals and user-defined groups
            for action_group in self._action_groups:
                formatter.start_section(action_group.title)
                formatter.add_text(action_group.description)
                formatter.add_arguments(action_group._group_actions)
                formatter.end_section()

            # epilog
            formatter.add_text(self.epilog)

            # determine help from format above
            return formatter.format_help()


        # <!-- monkey patch our parser
        # switch format_help, so that stuff comes in an order that makes more sense in markdown
        parser.format_help = MethodType(format_help_markdown, parser)
        # switch formatter class so we'll get markdown
        setattr(parser, 'formatter_class', MarkdownFormatter)
        # -->

        MarkdownFormatter.level = level

        parser.print_help()

        # check if the parser has a subparser, so we can generate its
        # help in markdown as well
        _subparsers = getattr(parser, '_subparsers', None)
        if _subparsers is not None:
            for subparsers in _subparsers._group_actions:
                for _, subparser in subparsers.choices.items():
                    self.print_help(subparser, level=level+1)

class MarkdownFormatter(HelpFormatter):
    level: int

    def __init__(self, *args: Tuple[Any], **kwargs: Dict[str, Any]) -> None:
        super().__init__(*args, **kwargs)
        self._root_section = self.MarkdownSection(self, None)
        self._current_section = self._root_section

    class MarkdownSection(HelpFormatter._Section):
        def format_help(self) -> str:
            # format the indented section
            if self.parent is not None:
                self.formatter._indent()
            join = self.formatter._join_parts
            helps: List[str] = []

            # only one table header per section
            print_table_headers = True
            for func, args in self.items:
                item_help_text = func(*args)
                name = getattr(func, '__name__', repr(func))

                # we need to fix headers for argument tables
                if name == '_format_action':
                    if print_table_headers and len(item_help_text) > 0:
                        helps.extend([
                            '\n',
                            '| argument | default | help |',
                            '\n',
                            '| -------- | ------- | ---- |',
                            '\n',
                        ])
                        print_table_headers = False

                helps.append(item_help_text)

            item_help = join(helps)

            if self.parent is not None:
                self.formatter._dedent()

            # return nothing if the section was empty
            if not item_help:
                return ''

            # add the heading if the section was non-empty
            if self.heading is not SUPPRESS and self.heading is not None:
                current_indent = self.formatter._current_indent
                heading = '%*s%s\n' % (current_indent, '', self.heading)

                # increase header if we're in a subparser
                if MarkdownFormatter.level > 0:
                    # a bit hackish, to get a space when adding a subparsers help
                    if self.parent is None:
                        print('')

                    heading = f'#{heading}'
            else:
                heading = ''

            # join the section-initial newline, the heading and the help
            return join(['\n', heading, item_help, '\n'])

    @property
    def current_level(self) -> int:
        return MarkdownFormatter.level + 1

    def _format_usage(self, *args: Tuple[Any], **kwargs: Dict[str, Any]) -> str:
        # remove last argument, which is prefix, we are going to set it
        args = args[:-1]
        usage_text = super()._format_usage(*args, **kwargs, prefix='')

        # wrap usage text in a markdown code block, with bash syntax
        return '\n'.join([
            '',
            f'{"#" * self.current_level}## Usage',
            '',
            '```bash',
            usage_text.strip(),
            '```',
            '',
        ])

    def format_help(self) -> str:
        heading = f'{"#" * self.current_level} `{self._prog}`'
        self._root_section.heading = heading
        return super().format_help()

    def _format_text(self, text: str) -> str:
        if '%(prog)' in text:
            text = text % dict(prog=self._prog)

        # in markdown, it will look better if we have first upper case on the first word in the sentence
        # sentence = string that ends with dot .
        if len(text.strip()) > 0:
            lines: List[str] = []
            in_code_block = False
            for line in text.split('\n'):
                sentences: List[str] = []

                # do not to upper the first letter of the first word in a
                # sentence if we're in a code block
                if line.strip().startswith('```'):
                    in_code_block = not in_code_block

                for sentence in line.split('.'):
                    if len(sentence.strip()) > 0 and not in_code_block:
                        sentence = f'{sentence[0].upper()}{sentence[1:]}'

                    sentences.append(sentence)

                line = '.'.join(sentences)
                lines.append(line)
            text = '\n'.join(lines)

        return f'{text}\n'

    def start_section(self, heading: str) -> None:
        heading = f'{heading[0].upper()}{heading[1:]}'
        heading = f'{"#" * self.current_level}# {heading}'
        self._indent()
        section = self.MarkdownSection(self, self._current_section, heading)
        self._add_item(section.format_help, [])
        self._current_section = section

    def _format_action(self, action: Action) -> str:
        # do not include -h/--help or --md-help in the markdown
        # help
        if 'help' in action.dest or not action.help:
            return ''

        lines: List[str] = []

        expanded_help = self._expand_help(action)
        help_text = self._split_lines(expanded_help, 80)

        # format arguments as a markdown table row
        lines.append('| `{argument}` | {default} | {help} |'.format(
            argument=', '.join(action.option_strings) or action.dest,
            default=action.default or '',
            help='<br/>'.join(help_text)),
        )
        lines.extend([''])

        return '\n'.join(lines)
