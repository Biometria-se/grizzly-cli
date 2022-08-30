from shutil import rmtree
from os import getcwd, environ
from tempfile import gettempdir
from argparse import ArgumentParser, Namespace

import pytest

from _pytest.capture import CaptureFixture
from _pytest.tmpdir import TempPathFactory
from pytest_mock import MockerFixture

from grizzly_cli.distributed import create_parser, distributed_run, distributed

from ..helpers import onerror

CWD = getcwd()


def test_distributed(mocker: MockerFixture) -> None:
    run_mocked = mocker.patch('grizzly_cli.distributed.run', return_value=0)
    build_mocked = mocker.patch('grizzly_cli.distributed.do_build', return_value=5)

    arguments = Namespace(subcommand='run')
    assert distributed(arguments) == 0

    assert run_mocked.call_count == 1
    args, _ = run_mocked.call_args_list[0]
    assert args[0] is arguments
    assert args[1] is distributed_run

    assert build_mocked.call_count == 0

    arguments = Namespace(subcommand='build')
    assert distributed(arguments) == 5

    assert run_mocked.call_count == 1
    assert build_mocked.call_count == 1
    args, _ = build_mocked.call_args_list[0]
    assert args[0] is arguments

    arguments = Namespace(subcommand='foo')
    with pytest.raises(ValueError) as ve:
        distributed(arguments)
    assert 'unknown subcommand foo' == str(ve.value)


def test_distributed_run(capsys: CaptureFixture, mocker: MockerFixture, tmp_path_factory: TempPathFactory) -> None:
    test_context = tmp_path_factory.mktemp('test_context')
    (test_context / 'test.feature').write_text('Feature:')

    mocker.patch('grizzly_cli.distributed.getuser', return_value='test-user')
    mocker.patch('grizzly_cli.distributed.get_default_mtu', side_effect=['1500', None, '1400', '1330', '1800'])
    mocker.patch('grizzly_cli.distributed.do_build', side_effect=[255, 0, 0])
    mocker.patch('grizzly_cli.distributed.list_images', side_effect=[{}, {}, {}, {'grizzly-cli-test-project': {'test-user': {}}}, {'grizzly-cli-test-project': {'test-user': {}}}])

    import grizzly_cli.distributed
    mocker.patch.object(grizzly_cli.distributed, 'EXECUTION_CONTEXT', '/tmp/execution-context')
    mocker.patch.object(grizzly_cli.distributed, 'STATIC_CONTEXT', '/tmp/static-context')
    mocker.patch.object(grizzly_cli.distributed, 'MOUNT_CONTEXT', '/tmp/mount-context')
    mocker.patch.object(grizzly_cli.distributed, 'PROJECT_NAME', 'grizzly-cli-test-project')

    mocker.patch('grizzly_cli.distributed.is_docker_compose_v2', return_value=False)

    run_command_mock = mocker.patch('grizzly_cli.distributed.run_command', side_effect=[111, 0, 0, 1, 0, 0, 1, 0, 13])

    parser = ArgumentParser()

    sub_parsers = parser.add_subparsers(dest='test')

    create_parser(sub_parsers)

    try:
        arguments = parser.parse_args(['dist', '--workers', '3', '--tty', 'run', f'{test_context}/test.feature'])
        setattr(arguments, 'container_system', 'docker')

        # this is set in the devcontainer
        for key in environ.keys():
            if key.startswith('GRIZZLY_'):
                del environ[key]

        assert distributed_run(arguments, {}, {}) == 111
        capture = capsys.readouterr()
        import sys
        assert capture.err == ''
        assert capture.out == (
            '!! something in the compose project is not valid, check with:\n'
            f'grizzly-cli {" ".join(sys.argv[1:])} --validate-config\n'
        )

        try:
            del environ['GRIZZLY_MTU']
        except KeyError:
            pass

        assert distributed_run(arguments, {}, {}) == 255
        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == (
            '!! unable to determine MTU, try manually setting GRIZZLY_MTU environment variable if anything other than 1500 is needed\n'
            '!! failed to build grizzly-cli-test-project, rc=255\n'
        )
        assert environ.get('GRIZZLY_MTU', None) == '1500'
        assert environ.get('GRIZZLY_EXECUTION_CONTEXT', None) == '/tmp/execution-context'
        assert environ.get('GRIZZLY_STATIC_CONTEXT', None) == '/tmp/static-context'
        assert environ.get('GRIZZLY_MOUNT_CONTEXT', None) == '/tmp/mount-context'
        assert environ.get('GRIZZLY_PROJECT_NAME', None) == 'grizzly-cli-test-project'
        assert environ.get('GRIZZLY_IMAGE_NAME', None) == 'grizzly-cli-test-project'
        assert environ.get('GRIZZLY_USER_TAG', None) == 'test-user'
        assert environ.get('GRIZZLY_EXPECTED_WORKERS', None) == '3'
        assert environ.get('GRIZZLY_MASTER_RUN_ARGS', None) is None
        assert environ.get('GRIZZLY_WORKER_RUN_ARGS', None) is None
        assert environ.get('GRIZZLY_COMMON_RUN_ARGS', None) is None
        assert environ.get('GRIZZLY_IMAGE_REGISTRY', None) == ''
        assert environ.get('GRIZZLY_ENVIRONMENT_FILE', '').startswith(gettempdir())
        assert environ.get('GRIZZLY_LIMIT_NOFILE', None) == '10001'
        assert environ.get('GRIZZLY_HEALTH_CHECK_INTERVAL', None) == '5'
        assert environ.get('GRIZZLY_HEALTH_CHECK_TIMEOUT', None) == '3'
        assert environ.get('GRIZZLY_HEALTH_CHECK_RETRIES', None) == '3'
        assert environ.get('GRIZZLY_CONTAINER_TTY', None) == 'true'
        assert environ.get('LOCUST_WAIT_FOR_WORKERS_REPORT_AFTER_RAMP_UP', None) is None

        # this is set in the devcontainer
        for key in environ.keys():
            if key.startswith('GRIZZLY_') or key.startswith('LOCUST_'):
                del environ[key]

        arguments = parser.parse_args([
            'dist',
            '--workers', '3',
            '--build',
            '--limit-nofile', '133700',
            '--health-interval', '10',
            '--health-timeout', '8',
            '--health-retries', '30',
            '--registry', 'gchr.io/biometria-se',
            '--wait-for-worker', '10000',
            '--image-name', 'foobar'
            'run',
            f'{test_context}/test.feature',
        ])
        setattr(arguments, 'container_system', 'docker')

        mocker.patch('grizzly_cli.distributed.is_docker_compose_v2', side_effect=[True, False])

        # docker-compose v2
        assert distributed_run(
            arguments,
            {
                'GRIZZLY_CONFIGURATION_FILE': '/tmp/execution-context/configuration.yaml',
                'GRIZZLY_TEST_VAR': 'True',
            },
            {
                'master': ['--foo', 'bar', '--master'],
                'worker': ['--bar', 'foo', '--worker'],
                'common': ['--common', 'true'],
            },
        ) == 1
        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == (
            '\n!! something went wrong, check container logs with:\n'
            'docker container logs grizzly-cli-test-project-test-user-master-1\n'
            'docker container logs grizzly-cli-test-project-test-user-worker-2\n'
            'docker container logs grizzly-cli-test-project-test-user-worker-3\n'
            'docker container logs grizzly-cli-test-project-test-user-worker-4\n'
        )

        assert run_command_mock.call_count == 5
        args, _ = run_command_mock.call_args_list[-3]
        assert args[0] == [
            'docker-compose',
            '-p', 'grizzly-cli-test-project-test-user',
            '-f', '/tmp/static-context/compose.yaml',
            'config',
        ]
        args, _ = run_command_mock.call_args_list[-2]
        assert args[0] == [
            'docker-compose',
            '-p', 'grizzly-cli-test-project-test-user',
            '-f', '/tmp/static-context/compose.yaml',
            'up',
            '--scale', 'worker=3',
            '--remove-orphans',
        ]
        args, _ = run_command_mock.call_args_list[-1]
        assert args[0] == [
            'docker-compose',
            '-p', 'grizzly-cli-test-project-test-user',
            '-f', '/tmp/static-context/compose.yaml',
            'stop',
        ]

        assert environ.get('GRIZZLY_RUN_FILE', None) == f'{test_context}/test.feature'
        assert environ.get('GRIZZLY_MTU', None) == '1400'
        assert environ.get('GRIZZLY_EXECUTION_CONTEXT', None) == '/tmp/execution-context'
        assert environ.get('GRIZZLY_STATIC_CONTEXT', None) == '/tmp/static-context'
        assert environ.get('GRIZZLY_MOUNT_CONTEXT', None) == '/tmp/mount-context'
        assert environ.get('GRIZZLY_PROJECT_NAME', None) == 'grizzly-cli-test-project'
        assert environ.get('GRIZZLY_IMAGE_NAME', None) == 'foobar'
        assert environ.get('GRIZZLY_USER_TAG', None) == 'test-user'
        assert environ.get('GRIZZLY_EXPECTED_WORKERS', None) == '3'
        assert environ.get('GRIZZLY_MASTER_RUN_ARGS', None) == '--foo bar --master'
        assert environ.get('GRIZZLY_WORKER_RUN_ARGS', None) == '--bar foo --worker'
        assert environ.get('GRIZZLY_COMMON_RUN_ARGS', None) == '--common true'
        assert environ.get('GRIZZLY_ENVIRONMENT_FILE', '').startswith(gettempdir())
        assert environ.get('GRIZZLY_LIMIT_NOFILE', None) == '133700'
        assert environ.get('GRIZZLY_HEALTH_CHECK_INTERVAL', None) == '10'
        assert environ.get('GRIZZLY_HEALTH_CHECK_TIMEOUT', None) == '8'
        assert environ.get('GRIZZLY_HEALTH_CHECK_RETRIES', None) == '30'
        assert environ.get('GRIZZLY_IMAGE_REGISTRY', None) == 'gchr.io/biometria-se'
        assert environ.get('GRIZZLY_CONTAINER_TTY', None) == 'false'
        assert environ.get('LOCUST_WAIT_FOR_WORKERS_REPORT_AFTER_RAMP_UP', None) == '10000'

        # docker-compose v1
        assert distributed_run(
            arguments,
            {
                'GRIZZLY_CONFIGURATION_FILE': '/tmp/execution-context/configuration.yaml',
                'GRIZZLY_TEST_VAR': 'True',
            },
            {
                'master': ['--foo', 'bar', '--master'],
                'worker': ['--bar', 'foo', '--worker'],
                'common': ['--common', 'true'],
            },
        ) == 1
        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == (
            '\n!! something went wrong, check container logs with:\n'
            'docker container logs grizzly-cli-test-project-test-user_master_1\n'
            'docker container logs grizzly-cli-test-project-test-user_worker_1\n'
            'docker container logs grizzly-cli-test-project-test-user_worker_2\n'
            'docker container logs grizzly-cli-test-project-test-user_worker_3\n'
        )

        mocker.patch('grizzly_cli.distributed.is_docker_compose_v2', return_value=False)

        # this is set in the devcontainer
        for key in environ.keys():
            if key.startswith('GRIZZLY_') or key.startswith('LOCUST_'):
                del environ[key]

        arguments = parser.parse_args([
            'dist',
            '--workers', '1',
            '--id', 'suffix',
            '--validate-config',
            '--limit-nofile', '20000',
            '--health-interval', '10',
            '--health-timeout', '8',
            '--health-retries', '30',
            '--wait-for-worker', '1.25 * WORKER_REPORT_INTERVAL',
            'run', f'{test_context}/test.feature',
        ])
        setattr(arguments, 'container_system', 'docker')

        assert distributed_run(
            arguments,
            {
                'GRIZZLY_CONFIGURATION_FILE': '/tmp/execution-context/configuration.yaml',
                'GRIZZLY_TEST_VAR': 'True',
            },
            {
                'master': ['--foo', 'bar', '--master'],
                'worker': ['--bar', 'foo', '--worker'],
                'common': ['--common', 'true'],
            },
        ) == 13
        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == ''

        assert run_command_mock.call_count == 9
        args, _ = run_command_mock.call_args_list[-1]
        assert args[0] == [
            'docker-compose',
            '-p', 'grizzly-cli-test-project-suffix-test-user',
            '-f', '/tmp/static-context/compose.yaml',
            'config',
        ]

        assert environ.get('GRIZZLY_RUN_FILE', None) == f'{test_context}/test.feature'
        assert environ.get('GRIZZLY_MTU', None) == '1800'
        assert environ.get('GRIZZLY_EXECUTION_CONTEXT', None) == '/tmp/execution-context'
        assert environ.get('GRIZZLY_STATIC_CONTEXT', None) == '/tmp/static-context'
        assert environ.get('GRIZZLY_MOUNT_CONTEXT', None) == '/tmp/mount-context'
        assert environ.get('GRIZZLY_PROJECT_NAME', None) == 'grizzly-cli-test-project'
        assert environ.get('GRIZZLY_USER_TAG', None) == 'test-user'
        assert environ.get('GRIZZLY_EXPECTED_WORKERS', None) == '1'
        assert environ.get('GRIZZLY_MASTER_RUN_ARGS', None) == '--foo bar --master'
        assert environ.get('GRIZZLY_WORKER_RUN_ARGS', None) == '--bar foo --worker'
        assert environ.get('GRIZZLY_COMMON_RUN_ARGS', None) == '--common true'
        assert environ.get('GRIZZLY_ENVIRONMENT_FILE', '').startswith(gettempdir())
        assert environ.get('GRIZZLY_LIMIT_NOFILE', None) == '20000'
        assert environ.get('GRIZZLY_HEALTH_CHECK_INTERVAL', None) == '10'
        assert environ.get('GRIZZLY_HEALTH_CHECK_TIMEOUT', None) == '8'
        assert environ.get('GRIZZLY_HEALTH_CHECK_RETRIES', None) == '30'
        assert environ.get('LOCUST_WAIT_FOR_WORKERS_REPORT_AFTER_RAMP_UP', None) == '1.25 * WORKER_REPORT_INTERVAL'

    finally:
        rmtree(test_context, onerror=onerror)
        for key in environ.keys():
            if key.startswith('GRIZZLY_'):
                del environ[key]
