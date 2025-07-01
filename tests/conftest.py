from __future__ import annotations

import sys
from os import environ
from typing import TYPE_CHECKING

import pytest

from tests.fixtures import (
    End2EndFixture,
)

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Generator

    from _pytest.config import Config
    from _pytest.fixtures import SubRequest
    from _pytest.tmpdir import TempPathFactory

E2E_RUN_MODE = environ.get('E2E_RUN_MODE', 'local')
E2E_RUN_DIST = environ.get('E2E_RUN_DIST', 'False').lower() == 'True'.lower()


PYTEST_TIMEOUT = 300 if E2E_RUN_DIST or E2E_RUN_MODE == 'dist' else 150

if sys.platform == 'darwin' and PYTEST_TIMEOUT > 150:
    PYTEST_TIMEOUT = 500


# if we're only running E2E tests, set global timeout
def pytest_configure(config: Config) -> None:
    target = getattr(config.known_args_namespace, 'file_or_dir', ['foobar'])
    if len(target) > 0 and 'tests/e2e' in target[0]:
        config._inicache['timeout'] = PYTEST_TIMEOUT


# also, add markers for each test function that starts with test_e2e_, if we're running everything
def pytest_collection_modifyitems(items: list[pytest.Function]) -> None:
    for item in items:
        if item.originalname.startswith('test_e2e_') and item.get_closest_marker('timeout') is None:
            item.add_marker(pytest.mark.timeout(PYTEST_TIMEOUT))


def _e2e_fixture(tmp_path_factory: TempPathFactory, request: SubRequest) -> Generator[End2EndFixture, None, None]:
    distributed = request.param if hasattr(request, 'param') else E2E_RUN_MODE == 'dist'

    with End2EndFixture(tmp_path_factory, distributed=distributed) as fixture:
        yield fixture


e2e_fixture = pytest.fixture(scope='session', params=[False, True] if E2E_RUN_DIST else None)(_e2e_fixture)
