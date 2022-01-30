from typing import Any, Dict, Tuple, Union, List
from os import chdir, environ, path, getcwd
from shutil import rmtree
from inspect import getfile
from importlib import reload
from textwrap import dedent
from argparse import Namespace

from _pytest.tmpdir import TempdirFactory
from _pytest.capture import CaptureFixture
from pytest_mock import MockerFixture

from grizzly_cli import parse_feature_file, list_images, get_default_mtu, run_command

from .helpers import onerror

CWD = getcwd()


def test___import__(tmpdir_factory: TempdirFactory)  -> None:
    test_context = tmpdir_factory.mktemp('test_context')
    test_context_root = str(test_context)

    chdir(test_context_root)

    try:
        environ['GRIZZLY_MOUNT_CONTEXT'] = '/var/tmp'

        import grizzly_cli
        reload(grizzly_cli)

        static_context = path.join(path.dirname(getfile(grizzly_cli)), 'static')

        assert grizzly_cli.__version__ == '0.0.0'
        assert grizzly_cli.EXECUTION_CONTEXT == test_context_root
        assert grizzly_cli.MOUNT_CONTEXT == '/var/tmp'
        assert grizzly_cli.STATIC_CONTEXT == static_context
        assert grizzly_cli.PROJECT_NAME == path.basename(test_context_root)
        assert len(grizzly_cli.SCENARIOS) == 0
    finally:
        chdir(CWD)
        rmtree(test_context_root, onerror=onerror)
        try:
            del environ['GRIZZLY_MOUNT_CONTEXT']
        except:
            pass


def test_parse_feature_file(tmpdir_factory: TempdirFactory) -> None:
    test_context = tmpdir_factory.mktemp('test_context')
    test_context_root = str(test_context)
    test_context.join('test.feature').write(dedent('''
    Feature: test feature
        Background:
            Given a common test step
            When executed in every scenario
        Scenario: scenario-1
            Given a test step
            And another test step
        Scenario: scenario-2
            Given a second test step
            Then execute it
            When done, just stop
    '''))

    chdir(test_context_root)

    try:
        import grizzly_cli
        reload(grizzly_cli)

        assert len(grizzly_cli.SCENARIOS) == 0

        parse_feature_file('test.feature')

        import grizzly_cli

        cached_scenarios = grizzly_cli.SCENARIOS
        assert len(grizzly_cli.SCENARIOS) == 2
        assert list(grizzly_cli.SCENARIOS)[0].name == 'scenario-1'
        assert len(list(grizzly_cli.SCENARIOS)[0].steps) == 2
        assert len(list(grizzly_cli.SCENARIOS)[0].background_steps) == 2
        assert list(grizzly_cli.SCENARIOS)[1].name == 'scenario-2'
        assert len(list(grizzly_cli.SCENARIOS)[1].steps) == 3
        assert len(list(grizzly_cli.SCENARIOS)[1].background_steps) == 2

        parse_feature_file('test.feature')

        import grizzly_cli

        assert grizzly_cli.SCENARIOS is cached_scenarios

    finally:
        chdir(CWD)
        rmtree(test_context_root, onerror=onerror)


def test_list_images(mocker: MockerFixture) -> None:
    check_output = mocker.patch('grizzly_cli.subprocess.check_output', side_effect=[(
        '{"name": "mcr.microsoft.com/vscode/devcontainers/python", "tag": "0-3.10", "size": "1.16GB", "created": "2021-12-02 23:46:55 +0100 CET", "id": "a05f8cc8454b"}\n'
        '{"name": "mcr.microsoft.com/vscode/devcontainers/python", "tag": "0-3.10-bullseye", "size": "1.16GB", "created": "2021-12-02 23:46:55 +0100 CET", "id": "a05f8cc8454b"}\n'
        '{"name": "mcr.microsoft.com/vscode/devcontainers/python", "tag": "0-3.9", "size": "1.23GB", "created": "2021-12-02 23:27:50 +0100 CET", "id": "bfbce224d490"}\n'
        '{"name": "mcr.microsoft.com/vscode/devcontainers/python", "tag": "0-3.8", "size": "1.23GB", "created": "2021-12-02 23:10:12 +0100 CET", "id": "8a04d9e5df14"}\n'
        '{"name": "mcr.microsoft.com/vscode/devcontainers/base", "tag": "0-focal", "size": "343MB", "created": "2021-12-02 22:44:23 +0100 CET", "id": "0cc1cbb6d08d"}\n'
        '{"name": "mcr.microsoft.com/vscode/devcontainers/python", "tag": "0-3.6", "size": "1.22GB", "created": "2021-12-02 22:17:47 +0100 CET", "id": "cc5abbf52b04"}\n'
    ).encode()])

    arguments = Namespace(container_system='capsulegirl')

    images = list_images(arguments)

    assert check_output.call_count == 1
    args, _ = check_output.call_args_list[-1]
    assert args[0] == [
        'capsulegirl',
        'image',
        'ls',
        '--format',
        '{"name": "{{.Repository}}", "tag": "{{.Tag}}", "size": "{{.Size}}", "created": "{{.CreatedAt}}", "id": "{{.ID}}"}',
    ]

    assert len(images.keys()) == 2
    assert sorted(list(images.get('mcr.microsoft.com/vscode/devcontainers/python', {}).keys())) == sorted([
        '0-3.10',
        '0-3.10-bullseye',
        '0-3.9',
        '0-3.8',
        '0-3.6',
    ])
    assert sorted(list(images.get('mcr.microsoft.com/vscode/devcontainers/base', {}).keys())) == sorted([
        '0-focal'
    ])


def test_get_default_mtu(mocker: MockerFixture) -> None:
    from json.decoder import JSONDecodeError
    check_output = mocker.patch('grizzly_cli.subprocess.check_output', side_effect=[
        JSONDecodeError,
        (
            '{"com.docker.network.bridge.default_bridge":"true","com.docker.network.bridge.enable_icc":"true",'
            '"com.docker.network.bridge.enable_ip_masquerade":"true","com.docker.network.bridge.host_binding_ipv4":"0.0.0.0",'
            '"com.docker.network.bridge.name":"docker0","com.docker.network.driver.mtu":"1500"}\n'
        ).encode(),
        (
            '{"com.docker.network.bridge.default_bridge":"true","com.docker.network.bridge.enable_icc":"true",'
            '"com.docker.network.bridge.enable_ip_masquerade":"true","com.docker.network.bridge.host_binding_ipv4":"0.0.0.0",'
            '"com.docker.network.bridge.name":"docker0","com.docker.network.driver.mtu":"1440"}\n'
        ).encode(),
    ])

    arguments = Namespace(container_system='capsulegirl')

    assert get_default_mtu(arguments) is None  # JSONDecodeError

    assert check_output.call_count == 1
    args, _ = check_output.call_args_list[-1]
    assert args[0] == [
        'capsulegirl',
        'network',
        'inspect',
        'bridge',
        '--format',
        '{{ json .Options }}',
    ]

    assert get_default_mtu(arguments) == '1500'
    assert get_default_mtu(arguments) == '1440'

    assert check_output.call_count == 3


def test_run_command(capsys: CaptureFixture, mocker: MockerFixture) -> None:
    terminate = mocker.patch('grizzly_cli.subprocess.Popen.terminate', autospec=True)
    wait = mocker.patch('grizzly_cli.subprocess.Popen.wait', autospec=True)

    def popen___init___no_stdout(*args: Tuple[Any, ...], **kwargs: Dict[str, Any]) -> None:
        setattr(args[0], 'returncode', 133)
        setattr(args[0], 'stdout', None)

    mocker.patch('grizzly_cli.subprocess.Popen.__init__', popen___init___no_stdout)
    poll = mocker.patch('grizzly_cli.subprocess.Popen.poll', side_effect=[None])
    kill = mocker.patch('grizzly_cli.subprocess.Popen.kill', side_effect=[RuntimeError, None])

    assert run_command([]) == 133

    capture = capsys.readouterr()
    assert capture.err == ''
    assert capture.out == ''

    assert terminate.call_count == 1
    assert wait.call_count == 1
    assert poll.call_count == 1
    assert kill.call_count == 1

    def popen___init__(*args: Tuple[Any, ...], **kwargs: Dict[str, Any]) -> None:
        setattr(args[0], 'returncode', 0)

        class Stdout:
            def __init__(self) -> None:
                self.output: List[Union[bytes, int]] = [
                    b'first line\n',
                    b'second line\n',
                    0,
                ]

            def readline(self) -> Union[bytes, int]:
                return self.output.pop(0)

        setattr(args[0], 'stdout', Stdout())



    mocker.patch('grizzly_cli.subprocess.Popen.terminate', side_effect=[KeyboardInterrupt])
    mocker.patch('grizzly_cli.subprocess.Popen.__init__', popen___init__)
    poll = mocker.patch('grizzly_cli.subprocess.Popen.poll', side_effect=[None] * 3)

    assert run_command([], {}) == 0

    capture = capsys.readouterr()
    assert capture.err == ''
    assert capture.out == (
        'first line\n'
        'second line\n'
    )

    assert wait.call_count == 2
    assert poll.call_count == 3
    assert kill.call_count == 2
