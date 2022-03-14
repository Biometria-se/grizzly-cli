from typing import Dict, Optional, cast
from argparse import ArgumentParser as CoreArgumentParser, Namespace
from os import getcwd, environ, chdir
from shutil import rmtree

import pytest

from _pytest.capture import CaptureFixture
from _pytest.tmpdir import TempPathFactory
from pytest_mock import MockerFixture

from grizzly_cli.__main__ import _create_parser, _parse_arguments, main

from .helpers import onerror

CWD = getcwd()


def test__create_parser() -> None:
    parser = _create_parser()

    assert parser.prog == 'grizzly-cli'
    assert parser.description is not None
    assert 'pip install grizzly-loadtester-cli' in parser.description
    assert 'eval "$(grizzly-cli --bash-completion)"' in parser.description
    assert parser._subparsers is not None
    assert len(parser._subparsers._group_actions) == 1
    assert sorted([option_string for action in parser._actions for option_string in action.option_strings]) == sorted([
        '-h', '--help',
        '--version',
        '--md-help',
        '--bash-completion',
    ])
    assert sorted([action.dest for action in parser._actions if len(action.option_strings) == 0]) == ['category']
    subparser = parser._subparsers._group_actions[0]
    assert subparser is not None
    assert subparser.choices is not None
    assert len(cast(Dict[str, Optional[CoreArgumentParser]], subparser.choices).keys()) == 2

    build_parser = cast(Dict[str, Optional[CoreArgumentParser]], subparser.choices).get('build', None)
    assert build_parser is not None
    assert build_parser._subparsers is None
    assert getattr(build_parser, 'prog', None) == 'grizzly-cli build'
    assert sorted([option_string for action in build_parser._actions for option_string in action.option_strings]) == sorted([
        '-h', '--help',
        '--no-cache',
        '--registry',
    ])

    run_parser = cast(Dict[str, Optional[CoreArgumentParser]], subparser.choices).get('run', None)
    assert run_parser is not None
    assert getattr(run_parser, 'prog', None) == 'grizzly-cli run'
    assert sorted([option_string for action in run_parser._actions for option_string in action.option_strings]) == sorted([
        '-h', '--help',
        '--verbose',
        '-T', '--testdata-variable',
        '-y', '--yes',
        '-e', '--environment-file',
    ])
    assert sorted([action.dest for action in run_parser._actions if len(action.option_strings) == 0]) == ['mode']
    assert run_parser._subparsers is not None
    assert len(run_parser._subparsers._group_actions) == 1
    subparser = run_parser._subparsers._group_actions[0]
    assert subparser is not None
    assert subparser.choices is not None
    assert len(cast(Dict[str, Optional[CoreArgumentParser]], subparser.choices).keys()) == 2

    dist_parser = cast(Dict[str, Optional[CoreArgumentParser]], subparser.choices).get('dist', None)
    assert dist_parser is not None
    assert getattr(dist_parser, 'prog', None) == 'grizzly-cli run dist'
    assert dist_parser._subparsers is None
    assert sorted([option_string for action in dist_parser._actions for option_string in action.option_strings]) == sorted([
        '-h', '--help',
        '--force-build', '--build', '--validate-config',
        '--workers',
        '--id',
        '--limit-nofile',
        '--container-system',
        '--health-timeout',
        '--health-retries',
        '--health-interval',
        '--registry',
    ])
    assert sorted([action.dest for action in dist_parser._actions if len(action.option_strings) == 0]) == ['file']

    local_parser = cast(Dict[str, Optional[CoreArgumentParser]], subparser.choices).get('local', None)
    assert local_parser is not None
    assert getattr(local_parser, 'prog', None) == 'grizzly-cli run local'
    assert local_parser._subparsers is None
    assert sorted([option_string for action in local_parser._actions for option_string in action.option_strings]) == sorted([
        '-h', '--help',
    ])
    assert sorted([action.dest for action in local_parser._actions if len(action.option_strings) == 0]) == ['file']


def test__parse_argument(capsys: CaptureFixture, mocker: MockerFixture, tmp_path_factory: TempPathFactory) -> None:
    test_context = tmp_path_factory.mktemp('test_context')
    (test_context / 'test.feature').write_text('Feature:')
    test_context_root = str(test_context)

    import sys

    try:
        chdir(test_context_root)
        sys.argv = ['grizzly-cli']

        with pytest.raises(SystemExit) as se:
            _parse_arguments()
        assert se.type == SystemExit
        assert se.value.code == 2
        capture = capsys.readouterr()
        assert capture.out == ''
        assert 'usage: grizzly-cli' in capture.err
        assert 'grizzly-cli: error: no subcommand specified' in capture.err

        sys.argv = ['grizzly-cli', '--version']

        with pytest.raises(SystemExit) as se:
            _parse_arguments()
        assert se.type == SystemExit
        assert se.value.code == 0
        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == '0.0.0\n'

        sys.argv = ['grizzly-cli', 'run']

        with pytest.raises(SystemExit) as se:
            _parse_arguments()
        assert se.type == SystemExit
        assert se.value.code == 2
        capture = capsys.readouterr()
        assert capture.out == ''
        assert 'usage: grizzly-cli' in capture.err
        assert 'grizzly-cli: error: no subcommand for run specified' in capture.err

        sys.argv = ['grizzly-cli', 'run', 'dist', 'test.feature']

        mocker.patch('grizzly_cli.__main__.get_distributed_system', side_effect=[None])

        with pytest.raises(SystemExit) as se:
            _parse_arguments()
        assert se.type == SystemExit
        assert se.value.code == 2
        capture = capsys.readouterr()
        assert capture.out == ''
        assert capture.err == 'grizzly-cli: error: cannot run distributed\n'

        mocker.patch('grizzly_cli.EXECUTION_CONTEXT', getcwd())
        mocker.patch('grizzly_cli.__main__.get_distributed_system', side_effect=['docker'])
        mocker.patch('grizzly_cli.__main__.build', side_effect=[0, 4, 0])

        sys.argv = ['grizzly-cli', 'run', 'dist', 'test.feature', '--limit-nofile', '100', '--registry', 'ghcr.io/biometria-se']
        (test_context / 'requirements.txt').write_text('grizzly-loadtester')
        mocker.patch('grizzly_cli.__main__.get_distributed_system', side_effect=['docker'])
        ask_yes_no = mocker.patch('grizzly_cli.__main__.ask_yes_no', autospec=True)

        arguments = _parse_arguments()
        capture = capsys.readouterr()
        assert arguments.limit_nofile == 100
        assert not arguments.yes
        assert arguments.registry == 'ghcr.io/biometria-se/'
        assert capture.out == '!! this will cause warning messages from locust later on\n'
        assert capture.err == ''
        assert ask_yes_no.call_count == 1
        args, _ = ask_yes_no.call_args_list[-1]
        assert args[0] == 'are you sure you know what you are doing?'

        sys.argv = ['grizzly-cli', 'run', 'local', 'test.feature']
        mocker.patch('grizzly_cli.__main__.which', side_effect=[None])

        with pytest.raises(SystemExit) as se:
            _parse_arguments()
        assert se.type == SystemExit
        assert se.value.code == 2

        capture = capsys.readouterr()
        assert capture.out == ''
        assert capture.err == 'grizzly-cli: error: "behave" not found in PATH, needed when running local mode\n'

        sys.argv = ['grizzly-cli', 'run', '-T', 'variable', 'local', 'test.feature']
        mocker.patch('grizzly_cli.__main__.which', side_effect=['behave'])

        with pytest.raises(SystemExit) as se:
            _parse_arguments()
        assert se.type == SystemExit
        assert se.value.code == 2

        capture = capsys.readouterr()
        assert capture.out == ''
        assert capture.err == 'grizzly-cli: error: -T/--testdata-variable needs to be in the format NAME=VALUE\n'

        sys.argv = ['grizzly-cli', 'run', '-T', 'key=value', 'local', 'test.feature']
        mocker.patch('grizzly_cli.__main__.which', side_effect=['behave'])

        assert environ.get('TESTDATA_VARIABLE_key', None) is None

        arguments = _parse_arguments()
        assert arguments.category == 'run'
        assert arguments.mode == 'local'
        assert arguments.file == 'test.feature'

        assert environ.get('TESTDATA_VARIABLE_key', None) == 'value'

        mocker.patch('grizzly_cli.__main__.get_distributed_system', side_effect=['docker'] * 3)

        sys.argv = ['grizzly-cli', 'build']
        arguments = _parse_arguments()

        assert not arguments.no_cache
        assert not arguments.force_build
        assert arguments.build
        assert arguments.registry is None

        sys.argv = ['grizzly-cli', 'build', '--no-cache', '--registry', 'gchr.io/biometria-se']
        arguments = _parse_arguments()

        assert arguments.no_cache
        assert arguments.force_build
        assert not arguments.build
        assert arguments.registry == 'gchr.io/biometria-se/'

    finally:
        chdir(CWD)
        rmtree(test_context_root, onerror=onerror)


def test_main(mocker: MockerFixture, capsys: CaptureFixture) -> None:
    run_mock = mocker.patch('grizzly_cli.__main__.run', side_effect=[0])
    build_mock = mocker.patch('grizzly_cli.__main__.build', side_effect=[1337])
    mocker.patch('grizzly_cli.__main__._parse_arguments', side_effect=[
        Namespace(category='run'),
        Namespace(category='build'),
        Namespace(category='foobar'),
        KeyboardInterrupt,
        ValueError('hello there'),
    ],)

    assert main() == 0
    assert run_mock.call_count == 1
    assert build_mock.call_count == 0

    assert main() == 1337
    assert run_mock.call_count == 1
    assert build_mock.call_count == 1

    assert main() == 1

    capture = capsys.readouterr()
    assert capture.err == ''
    assert capture.out == '\nunknown subcommand foobar\n\n!! aborted grizzly-cli\n'

    assert main() == 1

    capture = capsys.readouterr()
    assert capture.err == ''
    assert capture.out == '\n\n!! aborted grizzly-cli\n'

    assert main() == 1

    capture = capsys.readouterr()
    assert capture.err == ''
    assert capture.out == '\nhello there\n\n!! aborted grizzly-cli\n'
