from __future__ import annotations

import sys
from argparse import ArgumentTypeError
from fnmatch import filter as fnmatch_filter
from os.path import sep as path_separator
from pathlib import Path
from typing import Optional

__all__ = [
    'BashCompletionTypes',
]

ESCAPE_CHARACTERS: dict[str, str | int | None] = {
    ' ': '\\ ',
    '(': '\\(',
    ')': '\\)',
}


class BashCompletionTypes:
    class File:
        def __init__(self, *args: str, missing_ok: bool = False) -> None:
            self.patterns = list(args)
            self.cwd = Path.cwd()
            self.missing_ok = missing_ok

        def __call__(self, value: str) -> str:
            if self.missing_ok:
                return value

            file = Path(value)

            if not file.exists():
                message = f'{value} does not exist'
                raise ArgumentTypeError(message)

            if not file.is_file():
                message = f'{value} is not a file'
                raise ArgumentTypeError(message)

            matches = [match for pattern in self.patterns for match in fnmatch_filter([value], pattern)]

            if len(matches) < 1:
                message = f'{value} does not match {", ".join(self.patterns)}'
                raise ArgumentTypeError(message)

            return value

        def list_files(self, value: Optional[str]) -> dict[str, str]:
            matches: dict[str, str] = {}

            if value is not None:
                if value.endswith('\\') and sys.platform != 'win32':
                    value += ' '
                value = value.replace('\\ ', ' ').replace('\\(', '(').replace('\\)', ')')

            for pattern in self.patterns:
                for path in self.cwd.rglob(f'**/{pattern}'):
                    try:
                        path_match = path.relative_to(self.cwd)
                    except ValueError:
                        path_match = path

                    path_match_value = path_match.as_posix()

                    if path_match_value.startswith('.') or (value is not None and not path_match_value.startswith(value)):
                        continue

                    match: Optional[dict[str, str]] = None

                    if path_separator in path_match_value:
                        try:
                            index_match = len(value or '')
                            index_sep = path_match_value[index_match:].index(path_separator) + index_match
                            match = {path_match_value[:index_sep].translate(str.maketrans(ESCAPE_CHARACTERS)): 'dir'}
                        except ValueError:
                            pass

                    if match is None:
                        match = {path_match_value.translate(str.maketrans(ESCAPE_CHARACTERS)): 'file'}

                    matches.update(match)

            return matches
