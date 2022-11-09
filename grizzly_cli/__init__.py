import os

from typing import Callable, List

from behave.model import Scenario

from .argparse import ArgumentSubParser
from .__version__ import __version__


EXECUTION_CONTEXT = os.getcwd()

STATIC_CONTEXT = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'static')

MOUNT_CONTEXT = os.environ.get('GRIZZLY_MOUNT_CONTEXT', EXECUTION_CONTEXT)

PROJECT_NAME = os.path.basename(EXECUTION_CONTEXT)

SCENARIOS: List[Scenario] = []


class register_parser:
    registered: List[Callable[[ArgumentSubParser], None]] = []

    def __init__(self, order: int = 1) -> None:
        self.order = order - 1

    def __call__(self, func: Callable[[ArgumentSubParser], None]) -> Callable[[ArgumentSubParser], None]:
        register_parser.registered.insert(self.order, func)

        return func


__all__ = [
    '__version__',
]
