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
        *args: Tuple[Any],
        **kwargs: Dict[str, Any]
    ) -> None:
        file_directory = path.dirname(__file__)
        with open(path.join(file_directory, 'bashcompletion.bash'), encoding='utf-8') as fd:
            print(fd.read().replace('bashcompletion_template', parser.prog))

        parser.exit()

import sys
def printerr(message: str) -> None:
    sys.stderr.write(f'{message}\n')
    pass


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

        printerr(values)

        for action in parser._actions:
            if isinstance(action, (BashCompleteAction, BashCompletionAction, )) or (action.default == '==SUPPRESS==' and action.dest != 'help'):
                continue
            elif isinstance(action, _SubParsersAction):
                suggestions.update({key: action for key in action.choices.keys()})
            elif getattr(action, 'option_strings', None) is not None:
                suggestions.update({key: action for key in action.option_strings})

        values = [value.strip() for value in values.replace(f'{parser.prog}', '').strip().split(' ') if len(value.strip()) > 0]

        # remove any completed values
        if len(values) > 2:
            completed = ' '.join(values[:2])
            values = ' '.join(values).replace(completed, ' ').strip().split(' ')
            filtered_values: List[str] = []
            skip = False
            for index, value in enumerate(values):
                if skip:
                    skip = False
                    continue
                value = value.strip()
                if len(value) < 1:
                    continue

                suggestion = suggestions.get(value, None)
                print(f'value={value}, suggestion={suggestion}')
                if suggestion is not None:
                    if isinstance(suggestion, _StoreConstAction):
                        for option in suggestion.option_strings:
                            del suggestions[option]
                        continue
                    if isinstance(suggestion, _AppendAction):
                        if len(values) > index + 1 and not values[index+1].strip().startswith('-'):
                            skip = True
                            continue

                filtered_values.append(value)

            values = filtered_values

        all_suggestions = suggestions.copy()


        printerr(values)

        if len(values) > 0:
            filtered_suggestions: Dict[str, Any] = {}
            for value in values:
                for option, action in suggestions.items():
                    if option.startswith(value):
                        filtered_suggestions.update({option: action})

            suggestions = filtered_suggestions

        if len(values) > 0 and values[0] in suggestions:
            suggestion = suggestions[values[0]]
            if isinstance(suggestion, _StoreConstAction):
                suggestions = all_suggestions
                for option in suggestion.option_strings:
                    del suggestions[option]
            elif isinstance(suggestion, _AppendAction) and len(values) == 2:
                suggestions = all_suggestions

        printerr(f'values={values}')
        printerr(f'suggestions={suggestions}')

        # value for an argument
        if len(values) > 0:
            action = suggestions.get(values[0].strip(), None)
            printerr(f'action={action}')
            if len(suggestions) == 1 and action is not None:
                if isinstance(action.type, BashCompletionTypes.File):
                    file_suggestions = action.type.list_files(values[-2:])

                    if not (len(file_suggestions) == 1 and values[-1] in file_suggestions):
                        suggestions = file_suggestions
                    else:
                        suggestions = all_suggestions
                        for option in action.option_strings:
                            del suggestions[option]
                elif isinstance(action.type, str):
                    print(action)

        print(' '.join(suggestions.keys()))
        parser.exit()


def hook(parser: Union[ArgumentParser, _SubParsersAction]) -> None:
    parser.add_argument('--bash-complete', action=BashCompleteAction, help=SUPPRESS)

    _subparsers = getattr(parser, '_subparsers', None)
    if _subparsers is not None:
        for subparsers in _subparsers._group_actions:
            for subparser in subparsers.choices.values():
                hook(subparser)
