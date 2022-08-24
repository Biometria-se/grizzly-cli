from os import environ, path, getcwd, chdir
from inspect import getfile
from shutil import rmtree
from socket import gaierror

from _pytest.capture import CaptureFixture
from _pytest.tmpdir import TempPathFactory
from pytest_mock import MockerFixture

from argparse import Namespace

from grizzly_cli.distributed.build import _create_build_command, getgid, getuid, build

from ..helpers import onerror


CWD = getcwd()


def test_getuid_getgid_nt(mocker: MockerFixture) -> None:
    mocker.patch('grizzly_cli.distributed.build.os.name', 'nt')

    assert getuid() == 1000
    assert getgid() == 1000

    mocker.patch('grizzly_cli.distributed.build.os.name', 'posix')

    assert getuid() >= 0
    assert getgid() >= 0


def test__create_build_command(mocker: MockerFixture) -> None:
    mocker.patch('grizzly_cli.distributed.build.getuid', return_value=1337)
    mocker.patch('grizzly_cli.distributed.build.getgid', return_value=2147483647)
    args = Namespace(container_system='test')

    mocker.patch('grizzly_cli.distributed.build.get_dependency_versions', return_value=(('1.1.1', None, ), '2.8.4'))

    assert _create_build_command(args, 'Containerfile.test', 'grizzly-cli:test', '/home/grizzly-cli/') == [
        'test',
        'image',
        'build',
        '--ssh',
        'default',
        '--build-arg', 'GRIZZLY_EXTRA=base',
        '--build-arg', 'GRIZZLY_UID=1337',
        '--build-arg', 'GRIZZLY_GID=2147483647',
        '-f', 'Containerfile.test',
        '-t', 'grizzly-cli:test',
        '/home/grizzly-cli/',
    ]

    mocker.patch('grizzly_cli.distributed.build.get_dependency_versions', return_value=(('1.1.1', [], ), '2.8.4'))

    assert _create_build_command(args, 'Containerfile.test', 'grizzly-cli:test', '/home/grizzly-cli/') == [
        'test',
        'image',
        'build',
        '--ssh',
        'default',
        '--build-arg', 'GRIZZLY_EXTRA=base',
        '--build-arg', 'GRIZZLY_UID=1337',
        '--build-arg', 'GRIZZLY_GID=2147483647',
        '-f', 'Containerfile.test',
        '-t', 'grizzly-cli:test',
        '/home/grizzly-cli/',
    ]

    mocker.patch('grizzly_cli.distributed.build.get_dependency_versions', return_value=(('1.1.1', ['dev', 'ci', 'mq'], ), '2.8.4'))

    assert _create_build_command(args, 'Containerfile.test', 'grizzly-cli:test', '/home/grizzly-cli/') == [
        'test',
        'image',
        'build',
        '--ssh',
        'default',
        '--build-arg', 'GRIZZLY_EXTRA=mq',
        '--build-arg', 'GRIZZLY_UID=1337',
        '--build-arg', 'GRIZZLY_GID=2147483647',
        '-f', 'Containerfile.test',
        '-t', 'grizzly-cli:test',
        '/home/grizzly-cli/',
    ]

    try:
        environ['IBM_MQ_LIB_HOST'] = 'https://localhost:8003'

        assert _create_build_command(args, 'Containerfile.test', 'grizzly-cli:test', '/home/grizzly-cli/') == [
            'test',
            'image',
            'build',
            '--ssh',
            'default',
            '--build-arg', 'GRIZZLY_EXTRA=mq',
            '--build-arg', 'GRIZZLY_UID=1337',
            '--build-arg', 'GRIZZLY_GID=2147483647',
            '--build-arg', 'IBM_MQ_LIB_HOST=https://localhost:8003',
            '-f', 'Containerfile.test',
            '-t', 'grizzly-cli:test',
            '/home/grizzly-cli/',
        ]

        environ['IBM_MQ_LIB_HOST'] = 'http://host.docker.internal:8000'

        mocker.patch('grizzly_cli.distributed.build.gethostbyname', return_value='1.2.3.4')

        assert _create_build_command(args, 'Containerfile.test', 'grizzly-cli:test', '/home/grizzly-cli/') == [
            'test',
            'image',
            'build',
            '--ssh',
            'default',
            '--build-arg', 'GRIZZLY_EXTRA=mq',
            '--build-arg', 'GRIZZLY_UID=1337',
            '--build-arg', 'GRIZZLY_GID=2147483647',
            '--build-arg', 'IBM_MQ_LIB_HOST=http://host.docker.internal:8000',
            '--add-host', 'host.docker.internal:1.2.3.4',
            '-f', 'Containerfile.test',
            '-t', 'grizzly-cli:test',
            '/home/grizzly-cli/',
        ]

        mocker.patch('grizzly_cli.distributed.build.gethostbyname', side_effect=[gaierror] * 2)

        assert _create_build_command(args, 'Containerfile.test', 'grizzly-cli:test', '/home/grizzly-cli/') == [
            'test',
            'image',
            'build',
            '--ssh',
            'default',
            '--build-arg', 'GRIZZLY_EXTRA=mq',
            '--build-arg', 'GRIZZLY_UID=1337',
            '--build-arg', 'GRIZZLY_GID=2147483647',
            '--build-arg', 'IBM_MQ_LIB_HOST=http://host.docker.internal:8000',
            '--add-host', 'host.docker.internal:host-gateway',
            '-f', 'Containerfile.test',
            '-t', 'grizzly-cli:test',
            '/home/grizzly-cli/',
        ]

        environ['IBM_MQ_LIB'] = 'mqm.tar.gz'

        assert _create_build_command(args, 'Containerfile.test', 'grizzly-cli:test', '/home/grizzly-cli/') == [
            'test',
            'image',
            'build',
            '--ssh',
            'default',
            '--build-arg', 'GRIZZLY_EXTRA=mq',
            '--build-arg', 'GRIZZLY_UID=1337',
            '--build-arg', 'GRIZZLY_GID=2147483647',
            '--build-arg', 'IBM_MQ_LIB_HOST=http://host.docker.internal:8000',
            '--add-host', 'host.docker.internal:host-gateway',
            '--build-arg', 'IBM_MQ_LIB=mqm.tar.gz',
            '-f', 'Containerfile.test',
            '-t', 'grizzly-cli:test',
            '/home/grizzly-cli/',
        ]

    finally:
        try:
            del environ['IBM_MQ_LIB_HOST']
        except KeyError:
            pass
        try:
            del environ['IBM_MQ_LIB']
        except KeyError:
            pass


def test_build(capsys: CaptureFixture, mocker: MockerFixture, tmp_path_factory: TempPathFactory) -> None:
    test_context = tmp_path_factory.mktemp('test_context')

    try:
        chdir(test_context)
        mocker.patch('grizzly_cli.EXECUTION_CONTEXT', str(test_context))
        mocker.patch('grizzly_cli.distributed.build.EXECUTION_CONTEXT', str(test_context))
        mocker.patch('grizzly_cli.distributed.build.PROJECT_NAME', 'grizzly-scenarios')
        mocker.patch('grizzly_cli.distributed.build.getuser', return_value='test-user')
        mocker.patch('grizzly_cli.distributed.build.getuid', return_value=1337)
        mocker.patch('grizzly_cli.distributed.build.getgid', return_value=2147483647)
        run_command = mocker.patch('grizzly_cli.distributed.build.run_command', side_effect=[254, 133, 0, 1, 0, 0, 2, 0, 0, 0])
        setattr(getattr(build, '__wrapped__'), '__value__', str(test_context))

        test_args = Namespace(container_system='test', force_build=False)

        static_context = path.realpath(path.join(path.dirname(getfile(_create_build_command)), '..', 'static'))

        assert build(test_args) == 254

        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == (
            '!! created a default requirements.txt with one dependency:\n'
            'grizzly-loadtester\n\n'
        )
        assert run_command.call_count == 1
        args, kwargs = run_command.call_args_list[-1]

        assert args[0] == [
            'test',
            'image',
            'build',
            '--ssh',
            'default',
            '--build-arg', 'GRIZZLY_EXTRA=base',
            '--build-arg', 'GRIZZLY_UID=1337',
            '--build-arg', 'GRIZZLY_GID=2147483647',
            '-f', f'{static_context}/Containerfile',
            '-t', 'grizzly-scenarios:test-user',
            str(test_context),
        ]

        actual_env = kwargs.get('env', None)
        assert actual_env is not None
        assert actual_env.get('DOCKER_BUILDKIT', None) == environ.get('DOCKER_BUILDKIT', None)

        test_args = Namespace(container_system='docker', force_build=True)

        mocker.patch('grizzly_cli.distributed.build.get_dependency_versions', return_value=(('1.1.1', ['mq', 'dev'], ), '2.8.4'))

        assert build(test_args) == 133
        assert run_command.call_count == 2
        args, kwargs = run_command.call_args_list[-1]

        assert args[0] == [
            'docker',
            'image',
            'build',
            '--ssh',
            'default',
            '--build-arg', 'GRIZZLY_EXTRA=mq',
            '--build-arg', 'GRIZZLY_UID=1337',
            '--build-arg', 'GRIZZLY_GID=2147483647',
            '-f', f'{static_context}/Containerfile',
            '-t', 'grizzly-scenarios:test-user',
            str(test_context),
            '--no-cache'
        ]

        actual_env = kwargs.get('env', None)
        assert actual_env is not None
        assert actual_env.get('DOCKER_BUILDKIT', None) == '1'

        image_name = 'grizzly-scenarios:test-user'
        test_args = Namespace(container_system='docker', force_build=False, registry='ghcr.io/biometria-se/')

        assert build(test_args) == 1

        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == (
            f'\n!! failed to tag image {image_name} -> ghcr.io/biometria-se/{image_name}\n'
        )

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
    finally:
        chdir(CWD)
        rmtree(test_context, onerror=onerror)
