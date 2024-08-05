import re

from os import environ
from typing import Generator, Optional, Tuple
from contextlib import contextmanager

import pytest

from _pytest.tmpdir import TempPathFactory

from tests.helpers import run_command, rm_rf


@contextmanager
def auth_via(tmp_path_factory: TempPathFactory, method: str) -> Generator[Tuple[Optional[str], Optional[str]], None, None]:
    secret = 'asdfasdf'
    test_context = tmp_path_factory.mktemp('test_context')
    argument: Optional[str] = None
    stdin: Optional[str] = None

    if method == 'env':
        environ['OTP_SECRET'] = secret
        argument = None
    elif method == 'stdin':
        argument = '-'
        stdin = secret
    elif method == 'file':
        file = test_context / 'secret.txt'
        file.write_text(f'{secret}\n')
        argument = str(file)

    try:
        yield (argument, stdin,)
    finally:
        if method == 'env':
            try:
                del environ['OTP_SECRET']
            except:
                pass

        rm_rf(test_context)


@pytest.mark.parametrize('method', ['env', 'file', 'stdin'])
def test_e2e_auth(tmp_path_factory: TempPathFactory, method: str) -> None:
    with auth_via(tmp_path_factory, method) as context:
        argument, stdin = context
        command = ['grizzly-cli', 'auth']
        if argument is not None:
            command.append(argument)

        rc, output = run_command(command, stdin=stdin)

        assert rc == 0

        result = ''.join(output).strip()

        assert re.match(r'^[0-9]{6}$', result)
