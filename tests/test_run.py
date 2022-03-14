from shutil import rmtree
from argparse import Namespace
from os import getcwd, environ, path
from tempfile import gettempdir

from _pytest.capture import CaptureFixture
from _pytest.tmpdir import TempPathFactory
from pytest_mock import MockerFixture

from grizzly_cli.run import distributed, local, run

from .helpers import onerror

CWD = getcwd()


def test_distributed(capsys: CaptureFixture, mocker: MockerFixture) -> None:
    mocker.patch('grizzly_cli.run.getuser', side_effect=['test-user'] * 3)
    mocker.patch('grizzly_cli.run.get_default_mtu', side_effect=[None, '1400', '1800'])
    mocker.patch('grizzly_cli.run.build', side_effect=[255, 0])
    mocker.patch('grizzly_cli.run.list_images', side_effect=[{}, {'grizzly-cli-test-project': {'test-user': {}}}, {'grizzly-cli-test-project': {'test-user': {}}}])

    import grizzly_cli.run
    mocker.patch.object(grizzly_cli.run, 'EXECUTION_CONTEXT', '/tmp/execution-context')
    mocker.patch.object(grizzly_cli.run, 'STATIC_CONTEXT', '/tmp/static-context')
    mocker.patch.object(grizzly_cli.run, 'MOUNT_CONTEXT', '/tmp/mount-context')
    mocker.patch.object(grizzly_cli.run, 'PROJECT_NAME', 'grizzly-cli-test-project')

    run_command = mocker.patch('grizzly_cli.run.run_command', side_effect=[0, 0, 1, 0, 13])

    arguments = Namespace(
        file='test.feature',
        workers=3,
        container_system='docker',
        id=None,
        build=True,
        force_build=False,
        health_interval=5,
        health_timeout=3,
        health_retries=3,
        registry='',
    )

    try:
        # this is set in the devcontainer
        for key in environ.keys():
            if key.startswith('GRIZZLY_'):
                del environ[key]

        assert distributed(arguments, {}, {}) == 255
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
        assert environ.get('GRIZZLY_USER_TAG', None) == 'test-user'
        assert environ.get('GRIZZLY_EXPECTED_WORKERS', None) == '3'
        assert environ.get('GRIZZLY_MASTER_RUN_ARGS', None) is None
        assert environ.get('GRIZZLY_WORKER_RUN_ARGS', None) is None
        assert environ.get('GRIZZLY_COMMON_RUN_ARGS', None) is None
        assert environ.get('GRIZZLY_IMAGE_REGISTRY', None) == ''
        assert environ.get('GRIZZLY_ENVIRONMENT_FILE', '').startswith(gettempdir())
        assert environ.get('GRIZZLY_HEALTH_CHECK_INTERVAL', None) == '5'
        assert environ.get('GRIZZLY_HEALTH_CHECK_TIMEOUT', None) == '3'
        assert environ.get('GRIZZLY_HEALTH_CHECK_RETRIES', None) == '3'

        # this is set in the devcontainer
        for key in environ.keys():
            if key.startswith('GRIZZLY_'):
                del environ[key]

        arguments = Namespace(
            file='test.feature',
            workers=3,
            container_system='docker',
            id=None,
            build=True,
            force_build=False,
            health_interval=10,
            health_timeout=8,
            health_retries=30,
            registry='gchr.io/biometria-se',
        )

        assert distributed(
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

        assert run_command.call_count == 4
        args, _ = run_command.call_args_list[-3]
        assert args[0] == [
            'docker-compose',
            '-p', 'grizzly-cli-test-project-test-user',
            '-f', '/tmp/static-context/compose.yaml',
            'config',
        ]
        args, _ = run_command.call_args_list[-2]
        assert args[0] == [
            'docker-compose',
            '-p', 'grizzly-cli-test-project-test-user',
            '-f', '/tmp/static-context/compose.yaml',
            'up',
            '--scale', 'worker=3',
            '--remove-orphans',
        ]
        args, _ = run_command.call_args_list[-1]
        assert args[0] == [
            'docker-compose',
            '-p', 'grizzly-cli-test-project-test-user',
            '-f', '/tmp/static-context/compose.yaml',
            'stop',
        ]

        assert environ.get('GRIZZLY_RUN_FILE', None) == 'test.feature'
        assert environ.get('GRIZZLY_MTU', None) == '1400'
        assert environ.get('GRIZZLY_EXECUTION_CONTEXT', None) == '/tmp/execution-context'
        assert environ.get('GRIZZLY_STATIC_CONTEXT', None) == '/tmp/static-context'
        assert environ.get('GRIZZLY_MOUNT_CONTEXT', None) == '/tmp/mount-context'
        assert environ.get('GRIZZLY_PROJECT_NAME', None) == 'grizzly-cli-test-project'
        assert environ.get('GRIZZLY_USER_TAG', None) == 'test-user'
        assert environ.get('GRIZZLY_EXPECTED_WORKERS', None) == '3'
        assert environ.get('GRIZZLY_MASTER_RUN_ARGS', None) == '--foo bar --master'
        assert environ.get('GRIZZLY_WORKER_RUN_ARGS', None) == '--bar foo --worker'
        assert environ.get('GRIZZLY_COMMON_RUN_ARGS', None) == '--common true'
        assert environ.get('GRIZZLY_ENVIRONMENT_FILE', '').startswith(gettempdir())
        assert environ.get('GRIZZLY_HEALTH_CHECK_INTERVAL', None) == '10'
        assert environ.get('GRIZZLY_HEALTH_CHECK_TIMEOUT', None) == '8'
        assert environ.get('GRIZZLY_HEALTH_CHECK_RETRIES', None) == '30'
        assert environ.get('GRIZZLY_IMAGE_REGISTRY', None) == 'gchr.io/biometria-se'

        # this is set in the devcontainer
        for key in environ.keys():
            if key.startswith('GRIZZLY_'):
                del environ[key]

        arguments = Namespace(
            file='test.feature',
            workers=1,
            container_system='docker',
            id='suffix',
            build=False,
            force_build=False,
            validate_config=True,
            health_interval=10,
            health_timeout=8,
            health_retries=30,
            registry='',
        )

        assert distributed(
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

        assert run_command.call_count == 5
        args, _ = run_command.call_args_list[-1]
        assert args[0] == [
            'docker-compose',
            '-p', 'grizzly-cli-test-project-suffix-test-user',
            '-f', '/tmp/static-context/compose.yaml',
            'config',
        ]

        assert environ.get('GRIZZLY_RUN_FILE', None) == 'test.feature'
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
        assert environ.get('GRIZZLY_HEALTH_CHECK_INTERVAL', None) == '10'
        assert environ.get('GRIZZLY_HEALTH_CHECK_TIMEOUT', None) == '8'
        assert environ.get('GRIZZLY_HEALTH_CHECK_RETRIES', None) == '30'

    finally:
        for key in environ.keys():
            if key.startswith('GRIZZLY_'):
                del environ[key]


def test_local(mocker: MockerFixture) -> None:
    run_command = mocker.patch('grizzly_cli.run.run_command', side_effect=[0])

    arguments = Namespace(file='test.feature')

    assert environ.get('GRIZZLY_TEST_VAR', None) is None

    try:
        assert local(
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
            'test.feature',
            '--foo', 'bar', '--master',
            '--bar', 'foo', '--worker',
            '--common', 'true',
        ]

        assert environ.get('GRIZZLY_TEST_VAR', None) == 'True'
    finally:
        try:
            del environ['GRIZZLY_TEST_VAR']
        except:
            pass


def test_run(capsys: CaptureFixture, mocker: MockerFixture, tmp_path_factory: TempPathFactory) -> None:
    test_context = tmp_path_factory.mktemp('test_context')
    execution_context = test_context / 'execution-context'
    execution_context.mkdir()
    mount_context = test_context / 'mount-context'
    mount_context.mkdir()

    try:
        mocker.patch('grizzly_cli.run.EXECUTION_CONTEXT', str(execution_context))
        mocker.patch('grizzly_cli.run.MOUNT_CONTEXT', str(mount_context))
        mocker.patch('grizzly_cli.run.get_hostname', side_effect=['localhost'] * 3)
        mocker.patch('grizzly_cli.run.find_variable_names_in_questions', side_effect=[['foo', 'bar'], []])
        mocker.patch('grizzly_cli.run.distribution_of_users_per_scenario', autospec=True)
        ask_yes_no_mock = mocker.patch('grizzly_cli.run.ask_yes_no', autospec=True)
        distributed_mock = mocker.patch('grizzly_cli.run.distributed', side_effect=[0])
        local_mock = mocker.patch('grizzly_cli.run.local', side_effect=[0])
        get_input_mock = mocker.patch('grizzly_cli.run.get_input', side_effect=['bar', 'foo'])


        arguments = Namespace(file='test.feature', environment_file='configuration.yaml', category='run', mode='dist', verbose=True)

        #from grizzly_cli.run import run

        assert run(arguments) == 0

        capture = capsys.readouterr()

        assert local_mock.call_count == 0
        assert distributed_mock.call_count == 1
        args, _ = distributed_mock.call_args_list[-1]

        assert args[0] is arguments

        # windows hack... one place uses C:\ and getcwd uses c:\
        args[1]['GRIZZLY_CONFIGURATION_FILE'] = args[1]['GRIZZLY_CONFIGURATION_FILE'].lower()
        assert args[1] == {
            'GRIZZLY_CLI_HOST': 'localhost',
            'GRIZZLY_EXECUTION_CONTEXT': str(execution_context),
            'GRIZZLY_MOUNT_CONTEXT': str(mount_context),
            'GRIZZLY_CONFIGURATION_FILE': path.join(getcwd(), 'configuration.yaml').lower(),
            'TESTDATA_VARIABLE_foo': 'bar',
            'TESTDATA_VARIABLE_bar': 'foo',
        }
        assert args[2] == {
            'master': [],
            'worker': [],
            'common': ['--stop', '--verbose', '--no-logcapture', '--no-capture', '--no-capture-stderr'],
        }

        assert ask_yes_no_mock.call_count == 1
        assert get_input_mock.call_count == 2
        args,  _ = get_input_mock.call_args_list[0]
        assert args[0] == 'initial value for "foo": '
        args,  _ = get_input_mock.call_args_list[1]
        assert args[0] == 'initial value for "bar": '

        assert capture.err == ''
        assert capture.out == (
            'feature file requires values for 2 variables\n'
            'the following values was provided:\n'
            'foo = bar\n'
            'bar = foo\n'
        )

        arguments = Namespace(file='test.feature', environment_file='configuration.yaml', category='run', mode='local', verbose=False)

        assert run(arguments) == 0

        capture = capsys.readouterr()

        assert local_mock.call_count == 1
        assert distributed_mock.call_count == 1
        args, _ = local_mock.call_args_list[-1]

        assert args[0] is arguments

        # windows hack... one place uses C:\ and getcwd uses c:\
        args[1]['GRIZZLY_CONFIGURATION_FILE'] = args[1]['GRIZZLY_CONFIGURATION_FILE'].lower()

        assert args[1] == {
            'GRIZZLY_CLI_HOST': 'localhost',
            'GRIZZLY_EXECUTION_CONTEXT': str(execution_context),
            'GRIZZLY_MOUNT_CONTEXT': str(mount_context),
            'GRIZZLY_CONFIGURATION_FILE': path.join(getcwd(), 'configuration.yaml').lower(),
        }
        assert args[2] == {
            'master': [],
            'worker': [],
            'common': ['--stop'],
        }

        assert ask_yes_no_mock.call_count == 1
        assert get_input_mock.call_count == 2

        assert capture.err == ''
        assert capture.out == ''
    finally:
        rmtree(test_context, onerror=onerror)
