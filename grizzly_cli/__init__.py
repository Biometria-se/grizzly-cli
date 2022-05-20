import os

from typing import Callable, List

from .argparse import ArgumentSubParser

# pyright: reportMissingImports=false
try:
    from importlib.metadata import version, PackageNotFoundError  # type: ignore[no-redef]  # pylint: disable=import-error
except ImportError:
    from importlib_metadata import version, PackageNotFoundError  # type: ignore[no-redef]  # pylint: disable=import-error

from behave.model import Scenario


try:
    __version__ = version('grizzly-loadtester-cli')
except PackageNotFoundError:
    __version__ = '0.0.0'

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
