from typing import Callable, Dict, List
from pathlib import Path
from os import getcwd

__all__ = [
    'BashCompletionTypes',
]

class BashCompletionTypes:
    class File:
        def __init__(self, pattern: str = '*') -> Callable[[str], str]:
            self.pattern = pattern

        def __call__(self, value: str) -> str:
            return value

        def list_files(self, values: List[str]) -> Dict[str, str]:
            # first is the argument that has this type
            values.pop(0)

            # there should be 0 or 1 items in list
            if len(values) > 0:
                value = values[0]
            else:
                value = None

            cwd = getcwd()

            matches: Dict[str, str] = {}

            for path in Path(cwd).rglob(self.pattern):
                path_match = str(path).replace(f'{cwd}/', '')

                if path_match.startswith('.') or (value is not None and not path_match.startswith(value)):
                    continue

                if Path(path).is_file:
                    path_type = 'file'
                elif Path(path).is_dir:
                    path_type = 'dir'
                else:
                    path_type = 'unknown'

                matches.update({path_match: path_type})

            return matches
