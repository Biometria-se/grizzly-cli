from __future__ import annotations

from os import environ
from pathlib import Path
from typing import TYPE_CHECKING, Callable, ClassVar, Optional

from grizzly_cli.__version__ import __version__

if TYPE_CHECKING:  # pragma: no cover
    from behave.model import Scenario

    from grizzly_cli.argparse import ArgumentSubParser

EXECUTION_CONTEXT = Path.cwd().as_posix()

STATIC_CONTEXT = Path.joinpath(Path(__file__).parent.absolute(), 'static').as_posix()

MOUNT_CONTEXT = environ.get('GRIZZLY_MOUNT_CONTEXT', EXECUTION_CONTEXT)

PROJECT_NAME = Path(EXECUTION_CONTEXT).name

SCENARIOS: list[Scenario] = []

FEATURE_DESCRIPTION: Optional[str] = None


class register_parser:
    registered: ClassVar[list[Callable[[ArgumentSubParser], None]]] = []
    order: Optional[int]

    def __init__(self, order: Optional[int] = None) -> None:
        self.order = order

    def __call__(self, func: Callable[[ArgumentSubParser], None]) -> Callable[[ArgumentSubParser], None]:
        if self.order is not None:
            self.registered.insert(self.order - 1, func)
        else:
            self.registered.append(func)

        return func


__all__ = [
    '__version__',
]
