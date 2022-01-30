from os import environ, path, getcwd, chdir
from inspect import getfile
from importlib import reload

from pytest_mock import MockerFixture

from argparse import Namespace

from grizzly_cli.build import _create_build_command, main


CWD = getcwd()

def test_getuid_getgid_nt(mocker: MockerFixture) -> None:
    from grizzly_cli import build
    import os
    mocker.patch.object(os, 'name', 'nt')
    reload(build)

    assert build.getuid() == 1000
    assert build.getgid() == 1000

    mocker.patch.object(os, 'name', 'posix')
    reload(build)

    assert build.getuid() >= 0
    assert build.getgid() >= 0


def test__create_build_command(mocker: MockerFixture) -> None:
    mocker.patch('grizzly_cli.build.getuid', side_effect=[1337])
    mocker.patch('grizzly_cli.build.getgid', side_effect=[2147483647])
    args = Namespace(container_system='test')

    assert _create_build_command(args, 'Containerfile.test', 'grizzly-cli:test', '/home/grizzly-cli/') == [
        'test',
        'image',
        'build',
        '--ssh',
        'default',
        '--build-arg', 'GRIZZLY_UID=1337',
        '--build-arg', 'GRIZZLY_GID=2147483647',
        '-f', 'Containerfile.test',
        '-t', 'grizzly-cli:test',
        '/home/grizzly-cli/',
    ]


def test_main(mocker: MockerFixture) -> None:
    from grizzly_cli import build
    reload(build)

    mocker.patch.object(build, 'EXECUTION_CONTEXT', CWD)
    mocker.patch.object(build, 'PROJECT_NAME', path.basename(CWD))
    mocker.patch('grizzly_cli.build.getuser', side_effect=['test-user'] * 2)
    mocker.patch('grizzly_cli.build.getuid', side_effect=[1337] * 2)
    mocker.patch('grizzly_cli.build.getgid', side_effect=[2147483647] * 2)
    run_command = mocker.patch('grizzly_cli.build.run_command', side_effect=[254, 133])
    test_args = Namespace(container_system='test', force_build=False)

    static_context = path.join(path.dirname(getfile(_create_build_command)), 'static')

    chdir(CWD)

    assert main(test_args) == 254
    assert run_command.call_count == 1
    args, kwargs = run_command.call_args_list[-1]

    print(args[0])

    assert args[0] == [
        'test',
        'image',
        'build',
        '--ssh',
        'default',
        '--build-arg', 'GRIZZLY_UID=1337',
        '--build-arg', 'GRIZZLY_GID=2147483647',
        '-f', f'{static_context}/Containerfile',
        '-t', f'{path.basename(CWD)}:test-user',
        getcwd(),
    ]

    actual_env = kwargs.get('env', None)
    assert actual_env is not None
    assert actual_env.get('DOCKER_BUILDKIT', None) == environ.get('DOCKER_BUILDKIT', None)

    test_args = Namespace(container_system='docker', force_build=True)

    assert main(test_args) == 133
    assert run_command.call_count == 2
    args, kwargs = run_command.call_args_list[-1]

    assert args[0] == [
        'docker',
        'image',
        'build',
        '--ssh',
        'default',
        '--build-arg', 'GRIZZLY_UID=1337',
        '--build-arg', 'GRIZZLY_GID=2147483647',
        '-f', f'{static_context}/Containerfile',
        '-t', f'{path.basename(CWD)}:test-user',
        getcwd(),
        '--no-cache'
    ]

    actual_env = kwargs.get('env', None)
    assert actual_env is not None
    assert actual_env.get('DOCKER_BUILDKIT', None) == '1'
