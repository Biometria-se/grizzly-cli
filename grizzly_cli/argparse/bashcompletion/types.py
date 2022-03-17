from typing import Dict, Optional
from pathlib import Path
from os import getcwd
from os.path import sep as path_separator
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
            path = Path(value)
            if not path.exists():
                raise ArgumentTypeError(f'{value} does not exist')

            if not path.is_file():
                raise ArgumentTypeError(f'{value} is not a file')
            matches = [match for pattern in self.patterns for match in fnmatch_filter([value], pattern)]

            if len(matches) < 1:
                raise ArgumentTypeError(f'{value} does not match {", ".join(self.patterns)}')

            return value

        def list_files(self, value: Optional[str]) -> Dict[str, str]:
            cwd = getcwd()

            matches: Dict[str, str] = {}

            for pattern in self.patterns:
                for path in Path(cwd).rglob(pattern):
                    path_match = str(path).replace(f'{cwd}{path_separator}', '')

                    if path_match.startswith('.') or (value is not None and not path_match.startswith(value)):
                        continue

                    match: Optional[Dict[str, str]] = None

                    if path_separator in path_match:
                        try:
                            index_match = len(value or '')
                            index_sep = path_match[index_match:].index(path_separator) + index_match
                            match = {path_match[:index_sep]: 'dir'}
                        except ValueError:
                            pass

                    if match is None:
                        match = {path_match: 'file'}

                    matches.update(match)

            return matches
