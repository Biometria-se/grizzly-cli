import sys

from typing import Dict, Optional
from glob import glob
from os import getcwd
from os.path import sep as path_separator, exists, isfile
from fnmatch import filter as fnmatch_filter
from argparse import ArgumentTypeError


__all__ = [
    'BashCompletionTypes',
]

ESCAPE_CHARACTERS = {
    ' ': '\\ ',
    '(': '\\(',
    ')': '\\)',
}


class BashCompletionTypes:
    class File:
        _cwd: str = getcwd()

        def __init__(self, *args: str) -> None:
            self.patterns = list(args)
            self.cwd = BashCompletionTypes.File._cwd

        def __call__(self, value: str) -> str:
            if not exists(value):
                raise ArgumentTypeError(f'{value} does not exist')

            if not isfile(value):
                raise ArgumentTypeError(f'{value} is not a file')

            matches = [match for pattern in self.patterns for match in fnmatch_filter([value], pattern)]

            if len(matches) < 1:
                raise ArgumentTypeError(f'{value} does not match {", ".join(self.patterns)}')

            return value

        def list_files(self, value: Optional[str]) -> Dict[str, str]:
            matches: Dict[str, str] = {}

            if value is not None:
                if value.endswith('\\') and sys.platform != 'win32':
                    value += ' '
                value = value.replace('\\ ', ' ').replace('\\(', '(').replace('\\)', ')')

            for pattern in self.patterns:
                for path in glob('**/{pattern}'.format(pattern=pattern), recursive=True):
                    path_match = path.replace('{cwd}{path_separator}'.format(cwd=self.cwd, path_separator=path_separator), '')

                    if path_match.startswith('.') or (value is not None and not path_match.startswith(value)):
                        continue

                    match: Optional[Dict[str, str]] = None

                    if path_separator in path_match:
                        try:
                            index_match = len(value or '')
                            index_sep = path_match[index_match:].index(path_separator) + index_match
                            match = {path_match[:index_sep].translate(str.maketrans(ESCAPE_CHARACTERS)): 'dir'}  # type: ignore
                        except ValueError:
                            pass

                    if match is None:
                        match = {path_match.translate(str.maketrans(ESCAPE_CHARACTERS)): 'file'}  # type: ignore

                    matches.update(match)

            return matches
