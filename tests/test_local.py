
from shutil import rmtree
from os import getcwd, environ
from argparse import ArgumentParser, Namespace

import pytest

from _pytest.tmpdir import TempPathFactory
from pytest_mock import MockerFixture

from grizzly_cli.local import create_parser, local_run, local

from .helpers import onerror

CWD = getcwd()


def test_local(mocker: MockerFixture) -> None:
    run_mocked = mocker.patch('grizzly_cli.local.run', return_value=0)

    arguments = Namespace(subcommand='run')

    assert local(arguments) == 0
    assert run_mocked.call_count == 1
    args, _ = run_mocked.call_args_list[0]
    assert args[0] is arguments
    assert args[1] is local_run

    arguments = Namespace(subcommand='foo')
    with pytest.raises(ValueError) as ve:
        local(arguments)
    assert 'unknown subcommand foo' == str(ve.value)


def test_local_run(mocker: MockerFixture, tmp_path_factory: TempPathFactory) -> None:
    run_command = mocker.patch('grizzly_cli.local.run_command', side_effect=[0])
    test_context = tmp_path_factory.mktemp('test_context')
    (test_context / 'test.feature').write_text('Feature:')

    parser = ArgumentParser()

    sub_parsers = parser.add_subparsers(dest='test')

    create_parser(sub_parsers)

    try:
        assert environ.get('GRIZZLY_TEST_VAR', None) is None

        arguments = parser.parse_args([
            'local', 'run', f'{test_context}/test.feature',
        ])

        assert local_run(
            arguments,
            {
                'GRIZZLY_TEST_VAR': 'True',
            },
            {
                'master': ['--foo', 'bar', '--master'],
                'worker': ['--bar', 'foo', '--worker'],
                'common': ['--common', 'true'],
            },
        ) == 0

        assert run_command.call_count == 1
        args, _ = run_command.call_args_list[-1]
        assert args[0] == [
            'behave',
            f'{test_context}/test.feature',
            '--foo', 'bar', '--master',
            '--bar', 'foo', '--worker',
            '--common', 'true',
        ]

        assert environ.get('GRIZZLY_TEST_VAR', None) == 'True'
    finally:
        rmtree(test_context, onerror=onerror)
        try:
            del environ['GRIZZLY_TEST_VAR']
        except:
            pass
