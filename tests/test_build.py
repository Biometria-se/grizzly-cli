from os import environ, path, getcwd, chdir
from inspect import getfile

from _pytest.capture import CaptureFixture
from pytest_mock import MockerFixture

from argparse import Namespace

from grizzly_cli.build import _create_build_command, build, getgid, getuid


CWD = getcwd()

def test_getuid_getgid_nt(mocker: MockerFixture) -> None:
    mocker.patch('grizzly_cli.build.os.name', 'nt')

    assert getuid() == 1000
    assert getgid() == 1000

    mocker.patch('grizzly_cli.build.os.name', 'posix')

    assert getuid() >= 0
    assert getgid() >= 0


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


def test_build(capsys: CaptureFixture, mocker: MockerFixture) -> None:
    mocker.patch('grizzly_cli.build.EXECUTION_CONTEXT', CWD)
    mocker.patch('grizzly_cli.build.PROJECT_NAME', path.basename(CWD))
    mocker.patch('grizzly_cli.build.getuser', side_effect=['test-user'] * 5)
    mocker.patch('grizzly_cli.build.getuid', side_effect=[1337] * 5)
    mocker.patch('grizzly_cli.build.getgid', side_effect=[2147483647] * 5)
    run_command = mocker.patch('grizzly_cli.build.run_command', side_effect=[254, 133, 0, 1, 0, 0, 2, 0, 0, 0])
    test_args = Namespace(container_system='test', force_build=False)

    static_context = path.join(path.dirname(getfile(_create_build_command)), 'static')

    chdir(CWD)

    assert build(test_args) == 254
    assert run_command.call_count == 1
    args, kwargs = run_command.call_args_list[-1]

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

    assert build(test_args) == 133
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

    image_name = f'{path.basename(CWD)}:test-user'
    test_args = Namespace(container_system='docker', force_build=False, registry='ghcr.io/biometria-se/')

    assert build(test_args) == 1

    capture = capsys.readouterr()
    assert capture.err == ''
    assert capture.out == f'\n!! failed to tag image {image_name} -> ghcr.io/biometria-se/{image_name}\n'

    assert run_command.call_count == 4

    args, kwargs = run_command.call_args_list[-1]
    assert args[0] == [
        'docker',
        'image',
        'tag',
        image_name,
        f'ghcr.io/biometria-se/{image_name}',
    ]

    actual_env = kwargs.get('env', None)
    assert actual_env.get('DOCKER_BUILDKIT', None) == '1'

    test_args = Namespace(container_system='docker', force_build=True, no_cache=True, build=True, registry='ghcr.io/biometria-se/')

    assert build(test_args) == 2

    capture = capsys.readouterr()
    assert capture.err == ''
    assert capture.out == f'\n!! failed to push image ghcr.io/biometria-se/{image_name}\n'

    assert run_command.call_count == 7

    args, kwargs = run_command.call_args_list[-1]
    assert args[0] == [
        'docker',
        'image',
        'push',
        f'ghcr.io/biometria-se/{image_name}',
    ]

    actual_env = kwargs.get('env', None)
    assert actual_env.get('DOCKER_BUILDKIT', None) == '1'

    assert build(test_args) == 0

    capture = capsys.readouterr()
    assert capture.err == ''
    assert capture.out == ''


