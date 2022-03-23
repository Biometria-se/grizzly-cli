import os

from typing import Set

# pyright: reportMissingImports=false
try:
    from importlib.metadata import version, PackageNotFoundError  # pylint: disable=import-error
except ImportError:
    from importlib_metadata import version, PackageNotFoundError  # pylint: disable=import-error

from behave.model import Scenario


try:
    __version__ = version('grizzly-loadtester-cli')
except PackageNotFoundError:
    __version__ = '0.0.0'

EXECUTION_CONTEXT = os.getcwd()

STATIC_CONTEXT = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'static')

MOUNT_CONTEXT = os.environ.get('GRIZZLY_MOUNT_CONTEXT', EXECUTION_CONTEXT)

PROJECT_NAME = os.path.basename(EXECUTION_CONTEXT)

SCENARIOS: Set[Scenario] = set()
