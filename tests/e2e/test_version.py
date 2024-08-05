from typing import Optional

import pytest

from _pytest.tmpdir import TempPathFactory
from pytest_mock import MockerFixture

from tests.helpers import run_command, get_current_version, rm_rf


CURRENT_VERSION = get_current_version()


@pytest.mark.parametrize('pip_module,grizzly_version,locust_version', [
    ('grizzly-loadtester==1.0.0', '1.0.0', '2.2.1',),
    ('grizzly-loadtester[mq]==2.4.6', '2.4.6 ── extras: mq', '2.9.0',),
    ('git+https://git@github.com/biometria-se/grizzly.git@v1.4.1#egg=grizzly-loadtester', '(development)', '2.2.1',),
    ('git+https://git@github.com/biometria-se/grizzly.git@v2.4.6#egg=grizzly-loadtester', '(development)', '2.9.0',),
    ('git+https://git@github.com/biometria-se/grizzly.git@7285294b#egg=grizzly-loadtester', '2.4.7.dev7', '>=2.12.0,<2.13',),
    ('grizzly-loadtester[mq] @ git+https://git@github.com/biometria-se/grizzly.git@7285294b', '2.4.7.dev7 ── extras: mq', '>=2.12.0,<2.13',),
])
def test_e2e_version(pip_module: str, grizzly_version: str, locust_version: str, tmp_path_factory: TempPathFactory, mocker: MockerFixture) -> None:
    test_context = tmp_path_factory.mktemp('test_context')

    result: Optional[str] = None

    try:
        # create project
        rc, output = run_command(
            ['grizzly-cli', 'init', 'foobar', '--yes'],
            cwd=str(test_context)
        )

        try:
            assert rc == 0
        except AssertionError:
            print(''.join(output))
            raise

        requirements_file = test_context / 'foobar' / 'requirements.txt'

        requirements_file.unlink()
        requirements_file.write_text(f'{pip_module}\n')

        rc, output = run_command(
            ['grizzly-cli', '--version', 'all'],
            cwd=str(test_context / 'foobar')
        )

        result = ''.join(output)

        assert rc == 0
        assert f'''grizzly-cli {CURRENT_VERSION}
└── grizzly {grizzly_version}
    └── locust {locust_version}
''' in ''.join(output)
    except AssertionError:
        if result is not None:
            print(result)
        raise
    finally:
        rm_rf(test_context)
