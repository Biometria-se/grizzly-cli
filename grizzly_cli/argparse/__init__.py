import sys
import re

from typing import Any, Dict, Tuple
from argparse import ArgumentParser as CoreArgumentParser, Namespace, SUPPRESS

from .markdown import MarkdownFormatter, MarkdownHelpAction
from .bashcompletion import BashCompletionAction


class ArgumentParser(CoreArgumentParser):
    def __init__(self, markdown_help: bool = True, bash_completion: bool = True, *args: Tuple[Any], **kwargs: Dict[str, Any]) -> None:
        super().__init__(*args, **kwargs)

        self.markdown_help = markdown_help
        self.bash_completion = bash_completion

        if self.markdown_help:
            self.add_argument('--md-help', action=MarkdownHelpAction, help=SUPPRESS)

        if self.bash_completion:
            self.add_argument('--bash-completion', action=BashCompletionAction, help=SUPPRESS)

    def error_no_help(self, message: str) -> None:
        sys.stderr.write('{}: error: {}\n'.format(self.prog, message))
        sys.exit(2)

    def print_help(self) -> None:
        '''Hook to make help more command line friendly, if there is markdown markers in the text.
        '''
        if not self.markdown_help:
            super().print_help()
            return

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

    def parse_args(self) -> Namespace:
        '''Hook to add `--bash-complete` to all parsers.'''
        # @TODO: add it here
        return super().parse_args()
