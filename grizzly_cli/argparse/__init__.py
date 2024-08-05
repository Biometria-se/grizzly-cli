import sys
import re

from typing import Any, Optional, IO, Sequence, cast
from argparse import ArgumentParser as CoreArgumentParser, Namespace, _SubParsersAction

from .markdown import MarkdownFormatter, MarkdownHelpAction
from .bashcompletion import BashCompletionAction, hook as bashcompletion_hook


ArgumentSubParser = _SubParsersAction


class ArgumentParser(CoreArgumentParser):
    def __init__(self, markdown_help: bool = False, bash_completion: bool = False, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        self.markdown_help = markdown_help
        self.bash_completion = bash_completion

        if self.markdown_help:
            self.add_argument('--md-help', action=MarkdownHelpAction)

        if self.bash_completion:
            self.add_argument('--bash-completion', action=BashCompletionAction)

        self._optionals.title = 'optional arguments'

    def error_no_help(self, message: str) -> None:
        sys.stderr.write('{}: error: {}\n'.format(self.prog, message))
        sys.exit(2)

    def print_help(self, file: Optional[IO[str]] = None) -> None:
        '''Hook to make help more command line friendly, if there is markdown markers in the text.
        '''
        if not self.markdown_help:
            super().print_help(file)
            return

        if cast(type, self.formatter_class) is not MarkdownFormatter:
            original_description = self.description
            original_actions = self._actions

            # code block "markers" are not really nice to have in cli help
            if self.description is not None:
                self.description = '\n'.join([line for line in self.description.split('\n') if '```' not in line])
                self.description = self.description.replace('\n\n', '\n')

            for action in self._actions:
                if action.help is not None:
                    # remove any markdown link markers
                    action.help = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', action.help)

        super().print_help(file)

        if cast(type, self.formatter_class) is not MarkdownFormatter:
            self.description = original_description
            self._actions = original_actions

    def parse_args(self, args: Optional[Sequence[str]] = None, namespace: Optional[Namespace] = None) -> Namespace:  # type: ignore
        """
        Hook to add `--bash-complete` to all parsers, if enabled for parser.
        """
        if self.bash_completion:
            bashcompletion_hook(self)

        return super().parse_args(args, namespace)
