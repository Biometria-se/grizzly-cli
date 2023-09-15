import os

from typing import Callable, List, Optional

from behave.model import Scenario

from .argparse import ArgumentSubParser
from .__version__ import __version__


EXECUTION_CONTEXT = os.getcwd()

STATIC_CONTEXT = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'static')

MOUNT_CONTEXT = os.environ.get('GRIZZLY_MOUNT_CONTEXT', EXECUTION_CONTEXT)

PROJECT_NAME = os.path.basename(EXECUTION_CONTEXT)

SCENARIOS: List[Scenario] = []

FEATURE_DESCRIPTION: Optional[str] = None


class register_parser:
    registered: List[Callable[[ArgumentSubParser], None]] = []
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
