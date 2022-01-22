from typing import Any, Dict, List, Tuple, Union, Sequence, Optional
from argparse import ArgumentParser, Action, Namespace, SUPPRESS, _SubParsersAction, _StoreConstAction, _AppendAction
from os import path

from .types import BashCompletionTypes

__all__ = [
    'BashCompletionTypes',
    'BashCompletionAction',
    'BashCompleteAction',
    'hook',
]


class BashCompletionAction(Action):
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
        file_directory = path.dirname(__file__)
        with open(path.join(file_directory, 'bashcompletion.bash'), encoding='utf-8') as fd:
            print(fd.read().replace('bashcompletion_template', parser.prog))

        parser.exit()

class BashCompleteAction(Action):
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
            nargs=None,
            **kwargs,
        )

    def __call__(
        self,
        parser: ArgumentParser,
        namespace: Namespace,
        values: Union[str, Sequence[Any], None],
        option_string: Optional[str] = None,
    ) -> None:
        all_suggestions: Dict[str, Any] = {}
        suggestions: Dict[str, Any] = {}
        provided_options: List[str] = []

        for action in parser._actions:
            if isinstance(action, (BashCompleteAction, BashCompletionAction, )) or (action.default == '==SUPPRESS==' and action.dest != 'help'):
                continue
            elif isinstance(action, _SubParsersAction):
                suggestions.update({key: action for key in action.choices.keys()})
            elif getattr(action, 'option_strings', None) is not None:
                suggestions.update({key: action for key in action.option_strings})

        if isinstance(values, str):
            provided_options = [value.strip() for value in values.replace(f'{parser.prog}', '').strip().split(' ') if len(value.strip()) > 0]
        elif isinstance(values, Sequence):
            provided_options = [str(value).strip() for value in values if len(str(value).strip()) and parser.prog not in values]

        # remove any completed values
        if len(provided_options) > 2:
            completed_options = ' '.join(provided_options[:2])
            provided_options = ' '.join(provided_options).replace(completed_options, ' ').strip().split(' ')
            filtered_options: List[str] = []
            skip = False

            for index, option in enumerate(provided_options):
                if skip:
                    skip = False
                    continue
                option = option.strip()
                if len(option) < 1:
                    continue

                suggestion = suggestions.get(option, None)
                if suggestion is not None:
                    if isinstance(suggestion, _StoreConstAction):
                        for option in suggestion.option_strings:
                            del suggestions[option]
                        continue
                    if isinstance(suggestion, _AppendAction):
                        if len(provided_options) > index + 1 and not provided_options[index+1].strip().startswith('-'):
                            skip = True
                            continue

                filtered_options.append(option)

            provided_options = filtered_options

        all_suggestions = suggestions.copy()

        if len(provided_options) > 0:
            filtered_suggestions: Dict[str, Any] = {}
            for option in provided_options:
                for option, action in suggestions.items():
                    if option.startswith(option):
                        filtered_suggestions.update({option: action})

            suggestions = filtered_suggestions

        if len(provided_options) > 0 and provided_options[0] in suggestions:
            suggestion = suggestions[provided_options[0]]
            if isinstance(suggestion, _StoreConstAction):
                suggestions = all_suggestions
                for option in suggestion.option_strings:
                    del suggestions[option]
            elif isinstance(suggestion, _AppendAction) and len(provided_options) == 2:
                suggestions = all_suggestions

        # value for an argument
        if len(provided_options) > 0:
            action = suggestions.get(provided_options[0], None)
            if len(suggestions) == 1 and action is not None:
                if isinstance(action.type, BashCompletionTypes.File):
                    file_suggestions = action.type.list_files(provided_options[-2:])

                    if not (len(file_suggestions) == 1 and provided_options[-1] in file_suggestions):
                        suggestions = file_suggestions
                    else:
                        suggestions = all_suggestions
                        for option in action.option_strings:
                            del suggestions[option]
                elif isinstance(action.type, str):
                    print(action)

        print(' '.join(suggestions.keys()))
        parser.exit()


def hook(parser: ArgumentParser) -> None:
    parser.add_argument('--bash-complete', action=BashCompleteAction, help=SUPPRESS)

    _subparsers = getattr(parser, '_subparsers', None)
    if _subparsers is not None:
        for subparsers in _subparsers._group_actions:
            for subparser in subparsers.choices.values():
                hook(subparser)
