import sys

from os import environ

import pytest

from _pytest.tmpdir import TempPathFactory
from _pytest.capture import CaptureFixture
from pytest_mock import MockerFixture

from grizzly_cli.__main__ import _parse_arguments
from grizzly_cli.auth import auth


def test_auth_env(capsys: CaptureFixture, mocker: MockerFixture) -> None:
    try:
        sys.argv = ['grizzly-cli', 'auth']
        arguments = _parse_arguments()

        with pytest.raises(ValueError) as ve:
            auth(arguments)

        assert str(ve.value) == 'environment variable OTP_SECRET is not set'
        capsys.readouterr()

        environ['OTP_SECRET'] = 'f00bar='

        with pytest.raises(ValueError) as ve:
            auth(arguments)
        assert str(ve.value) == 'unable to generate TOTP code: Non-base32 digit found'

        environ['OTP_SECRET'] = 'asdfasdf'
        mocker.patch('grizzly_cli.auth.TOTP.now', return_value=111111)

        assert auth(arguments) == 0

        capture = capsys.readouterr()

        assert capture.err == ''
        assert capture.out == '111111\n'
    finally:
        try:
            del environ['OTP_SECRET']
        except:
            pass


def test_auth_stdin(capsys: CaptureFixture, mocker: MockerFixture) -> None:
    sys.argv = ['grizzly-cli', 'auth', '-']
    arguments = _parse_arguments()

    mocker.patch('sys.stdin.read', return_value=None)

    with pytest.raises(ValueError) as ve:
        auth(arguments)
    assert str(ve.value) == 'OTP secret could not be read from stdin'

    mocker.patch('sys.stdin.read', return_value=' ')

    with pytest.raises(ValueError) as ve:
        auth(arguments)
    assert str(ve.value) == 'OTP secret could not be read from stdin'

    mocker.patch('sys.stdin.read', return_value='f00bar=')

    with pytest.raises(ValueError) as ve:
        auth(arguments)
    assert str(ve.value) == 'unable to generate TOTP code: Non-base32 digit found'

    capsys.readouterr()

    mocker.patch('grizzly_cli.auth.TOTP.now', return_value=222222)
    mocker.patch('sys.stdin.read', return_value='asdfasdf')

    assert auth(arguments) == 0

    capture = capsys.readouterr()

    assert capture.err == ''
    assert capture.out == '222222\n'


def test_auth_file(capsys: CaptureFixture, mocker: MockerFixture, tmp_path_factory: TempPathFactory) -> None:
    test_context = tmp_path_factory.mktemp('test_context')

    file = test_context / 'secret.txt'

    sys.argv = ['grizzly-cli', 'auth', str(file)]
    arguments = _parse_arguments()

    with pytest.raises(ValueError) as ve:
        auth(arguments)
    assert str(ve.value) == f'file {file} does not exist'

    file.write_text(' ')

    with pytest.raises(ValueError) as ve:
        auth(arguments)
    assert str(ve.value) == f'file {file} does not seem to contain a single line with a valid OTP secret'

    file.write_text('aasdf\nasdfasdf\n')

    with pytest.raises(ValueError) as ve:
        auth(arguments)
    assert str(ve.value) == f'file {file} does not seem to contain a single line with a valid OTP secret'

    file.write_text('hello world\n')

    with pytest.raises(ValueError) as ve:
        auth(arguments)
    assert str(ve.value) == f'file {file} does not seem to contain a single line with a valid OTP secret'

    file.write_text('f00bar=\n')

    with pytest.raises(ValueError) as ve:
        auth(arguments)
    assert str(ve.value) == 'unable to generate TOTP code: Non-base32 digit found'

    file.write_text('asdfasdf')
    mocker.patch('grizzly_cli.auth.TOTP.now', return_value=333333)

    assert auth(arguments) == 0

    capture = capsys.readouterr()

    assert capture.err == ''
    assert capture.out == '333333\n'
