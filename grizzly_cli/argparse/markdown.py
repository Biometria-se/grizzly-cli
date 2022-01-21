from typing import Any, Dict, List, Union, Sequence, Optional, Tuple
from types import MethodType
from argparse import Action, SUPPRESS, ArgumentParser, Namespace, HelpFormatter, _SubParsersAction


__all__ = [
    'MarkdownHelpAction',
    'MarkdownFormatter',
]

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
