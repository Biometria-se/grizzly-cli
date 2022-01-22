from typing import Dict, List, Tuple
from pathlib import Path
from os import getcwd
from fnmatch import filter as fnmatch_filter
from argparse import ArgumentTypeError

__all__ = [
    'BashCompletionTypes',
]

class BashCompletionTypes:
    class File:
        def __init__(self, *args: str) -> None:
            self.patterns = list(args)

        def __call__(self, value: str) -> str:
            matches = [match for pattern in self.patterns for match in fnmatch_filter([value], pattern)]
            if len(matches) > 0:
                return value
            else:
                raise ArgumentTypeError(f'{value} does not match {", ".join(self.patterns)}')

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

            for pattern in self.patterns:
                for path in Path(cwd).rglob(pattern):
                    path_match = str(path).replace(f'{cwd}/', '')

                    if path_match.startswith('.') or (value is not None and not path_match.startswith(value)):
                        continue

                    if path.is_file():
                        path_type = 'file'
                    elif path.is_dir():
                        path_type = 'dir'
                    else:
                        path_type = 'unknown'

                    matches.update({path_match: path_type})

            return matches
