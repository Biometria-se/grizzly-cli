from shutil import rmtree
from typing import Dict, Optional, List, cast
from argparse import ArgumentParser as CoreArgumentParser, Namespace
from os import chdir, getcwd, environ, path
from textwrap import dedent
from tempfile import gettempdir
from importlib import reload

import pytest

from _pytest.capture import CaptureFixture
from _pytest.tmpdir import TempdirFactory
from pytest_mock import MockerFixture
from behave.model import Scenario, Step

from grizzly_cli.cli import (
    _get_distributed_system,
    _create_parser,
    _parse_arguments,
    _find_variable_names_in_questions,
    _distribution_of_users_per_scenario,
    _run_distributed,
    _run_local,
    _ask_yes_no,
    main,
)

from .helpers import onerror

CWD = getcwd()


def create_scenario(name: str, background_steps: List[str], steps: List[str]) -> Scenario:
    scenario = Scenario('', '', '', name)

    for background_step in background_steps:
        [keyword, name] = background_step.split(' ', 1)
        step = Step('', '', keyword.strip(), keyword.strip(), name.strip())
        if scenario._background_steps is None:
            scenario._background_steps = []
        scenario._background_steps.append(step)

    for step in steps:
        [keyword, name] = step.split(' ', 1)
        step = Step('', '', keyword.strip(), keyword.strip(), name.strip())
        scenario.steps.append(step)

    return scenario

def test__get_distributed_system(capsys: CaptureFixture, mocker: MockerFixture) -> None:
    which = mocker.patch('grizzly_cli.cli.which', side_effect=[
        None,               # test 1
        None,               # - " -
        'podman',           # test 2
        None,               # - " -
        'podman',           # test 3
        'podman-compose',   # - " -
        None,               # test 4
        'docker',           # - " -
        None,               # - " -
        None,               # test 5
        'docker',           # - " -
        'docker-compose',   # - " -
    ])

    # test 1
    assert _get_distributed_system() is None # neither
    capture = capsys.readouterr()
    assert capture.out == 'neither "podman" nor "docker" found in PATH\n'
    assert which.call_count == 2
    which.reset_mock()

    # test 2
    assert _get_distributed_system() is None
    capture = capsys.readouterr()
    assert which.call_count == 2
    assert capture.out == (
        '!! podman might not work due to buildah missing support for `RUN --mount=type=ssh`: https://github.com/containers/buildah/issues/2835\n'
        '"podman-compose" not found in PATH\n'
    )
    which.reset_mock()

    # test 3
    assert _get_distributed_system() == 'podman'
    capture = capsys.readouterr()
    assert which.call_count == 2
    assert capture.out == (
        '!! podman might not work due to buildah missing support for `RUN --mount=type=ssh`: https://github.com/containers/buildah/issues/2835\n'
    )
    which.reset_mock()

    # test 4
    assert _get_distributed_system() is None
    capture = capsys.readouterr()
    assert which.call_count == 3
    assert capture.out == (
        '"docker-compose" not found in PATH\n'
    )
    which.reset_mock()

    # test 5
    assert _get_distributed_system() == 'docker'
    capture = capsys.readouterr()
    assert which.call_count == 3
    assert capture.out == ''
    which.reset_mock()


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
    assert len(cast(Dict[str, Optional[CoreArgumentParser]], subparser.choices).keys()) == 1

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
        '--force-build', '--build',
        '--workers',
        '--id',
        '--limit-nofile',
        '--container-system',
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


def test__parse_argument(capsys: CaptureFixture, mocker: MockerFixture, tmpdir_factory: TempdirFactory) -> None:
    test_context = tmpdir_factory.mktemp('test_context')
    test_context.join('test.feature').write('Feature:')
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

        mocker.patch('grizzly_cli.cli._get_distributed_system', side_effect=[None])

        with pytest.raises(SystemExit) as se:
            _parse_arguments()
        assert se.type == SystemExit
        assert se.value.code == 2
        capture = capsys.readouterr()
        assert capture.out == ''
        assert capture.err == 'grizzly-cli: error: cannot run distributed\n'

        import grizzly_cli.cli
        reload(grizzly_cli.cli)
        mocker.patch.object(grizzly_cli.cli, 'EXECUTION_CONTEXT', getcwd())
        mocker.patch('grizzly_cli.cli._get_distributed_system', side_effect=['docker'])

        with pytest.raises(SystemExit) as se:
            _parse_arguments()
        assert se.type == SystemExit
        assert se.value.code == 2
        capture = capsys.readouterr()
        assert capture.out == ''
        assert capture.err == f'grizzly-cli: error: there is no requirements.txt in {getcwd()}, building of container image not possible\n'

        sys.argv = ['grizzly-cli', 'run', 'dist', 'test.feature', '--limit-nofile', '100']
        test_context.join('requirements.txt').write('grizzly-loadtester')
        mocker.patch('grizzly_cli.cli._get_distributed_system', side_effect=['docker'])
        ask_yes_no = mocker.patch('grizzly_cli.cli._ask_yes_no', autospec=True)

        arguments = _parse_arguments()
        capture = capsys.readouterr()
        assert arguments.limit_nofile == 100
        assert not arguments.yes
        assert capture.out == '!! this will cause warning messages from locust later on\n'
        assert capture.err == ''
        assert ask_yes_no.call_count == 1
        args, _ = ask_yes_no.call_args_list[-1]
        assert args[0] == 'are you sure you know what you are doing?'

        sys.argv = ['grizzly-cli', 'run', 'local', 'test.feature']
        mocker.patch('grizzly_cli.cli.which', side_effect=[None])

        with pytest.raises(SystemExit) as se:
            _parse_arguments()
        assert se.type == SystemExit
        assert se.value.code == 2

        capture = capsys.readouterr()
        assert capture.out == ''
        assert capture.err == 'grizzly-cli: error: "behave" not found in PATH, needed when running local mode\n'

        sys.argv = ['grizzly-cli', 'run', '-T', 'variable', 'local', 'test.feature']
        mocker.patch('grizzly_cli.cli.which', side_effect=['behave'])

        with pytest.raises(SystemExit) as se:
            _parse_arguments()
        assert se.type == SystemExit
        assert se.value.code == 2

        capture = capsys.readouterr()
        assert capture.out == ''
        assert capture.err == 'grizzly-cli: error: -T/--testdata-variable needs to be in the format NAME=VALUE\n'

        sys.argv = ['grizzly-cli', 'run', '-T', 'key=value', 'local', 'test.feature']
        mocker.patch('grizzly_cli.cli.which', side_effect=['behave'])

        assert environ.get('TESTDATA_VARIABLE_key', None) is None

        arguments = _parse_arguments()
        assert arguments.category == 'run'
        assert arguments.mode == 'local'
        assert arguments.file == 'test.feature'

        assert environ.get('TESTDATA_VARIABLE_key', None) == 'value'

    finally:
        chdir(CWD)
        rmtree(test_context_root, onerror=onerror)

def test__find_variable_names_in_questions(mocker: MockerFixture) -> None:
    import grizzly_cli.cli
    reload(grizzly_cli.cli)
    mocker.patch.object(grizzly_cli.cli, 'SCENARIOS', [])
    mocker.patch('grizzly_cli.cli.parse_feature_file', autospec=True)

    assert _find_variable_names_in_questions('test.feature') == []

    mocker.patch.object(grizzly_cli.cli, 'SCENARIOS', [
        create_scenario(
            'scenario-1',
            [],
            [
                'Given a user of type "RestApi" load testing "https://localhost"',
                'And ask for value of variable test_variable_1',
            ]
        ),
    ])

    with pytest.raises(ValueError) as ve:
        _find_variable_names_in_questions('test.feature')
    assert 'could not find variable name in "ask for value of variable test_variable_1"' in str(ve)

    mocker.patch.object(grizzly_cli.cli, 'SCENARIOS', [
        create_scenario(
            'scenario-1',
            [],
            [
                'Given a user of type "RestApi" load testing "https://localhost"',
                'And ask for value of variable "test_variable_2"',
                'And ask for value of variable "test_variable_1"',
            ]
        ),
        create_scenario(
            'scenario-2',
            [
                'And ask for value of variable "bar"',
            ],
            [
                'Given a user of type "MessageQueueUser" load testing "mqs://localhost"',
                'And ask for value of variable "foo"',
            ]
        )
    ])
    variables = _find_variable_names_in_questions('test.feature')
    assert len(variables) == 4
    assert variables == ['bar', 'foo', 'test_variable_1', 'test_variable_2']


def test__distribution_of_users_per_scenario(capsys: CaptureFixture, mocker: MockerFixture) -> None:
    arguments = Namespace(file='test.feature', yes=False)

    import grizzly_cli.cli
    reload(grizzly_cli.cli)
    ask_yes_no = mocker.patch('grizzly_cli.cli._ask_yes_no', autospec=True)

    mocker.patch.object(grizzly_cli.cli, 'SCENARIOS', [
        create_scenario(
            'scenario-1',
            [],
            [
                'Given a user of type "RestApi" load testing "https://localhost"',
                'And ask for value of variable "test_variable_2"',
                'And ask for value of variable "test_variable_1"',
            ],
        ),
        create_scenario(
            'scenario-2',
            [
                'And ask for value of variable "bar"',
            ],
            [
                'Given a user of type "MessageQueueUser" load testing "mqs://localhost"',
                'And ask for value of variable "foo"',
            ],
        )
    ])

    _distribution_of_users_per_scenario(arguments, { })
    capture = capsys.readouterr()

    assert capture.err == ''
    assert capture.out == dedent('''
        feature file test.feature will execute in total 2 iterations

        each scenario will execute accordingly:

        identifier  symbol  weight  iter    description
        -----------|-------|-------|-------|------------|
        02ce541f       A        1.0       1 scenario-1
        91d624d8       B        1.0       1 scenario-2
        -----------|-------|-------|-------|------------|

        timeline of user scheduling will look as following:
        AB

    ''')
    assert ask_yes_no.call_count == 1
    args, _ = ask_yes_no.call_args_list[-1]
    assert args[0] == 'continue?'

    mocker.patch.object(grizzly_cli.cli, 'SCENARIOS', [
        create_scenario(
            'scenario-1',
            [],
            [],
        ),
    ])

    with pytest.raises(ValueError) as ve:
        _distribution_of_users_per_scenario(arguments, {})
    assert 'scenario-1 does not have any steps' in str(ve)

    mocker.patch.object(grizzly_cli.cli, 'SCENARIOS', [
        create_scenario(
            'scenario-1',
            [],
            ['And repeat for "10" iterations'],
        ),
    ])

    with pytest.raises(ValueError) as ve:
        _distribution_of_users_per_scenario(arguments, {})
    assert 'scenario-1 does not have a user type' in str(ve)

    mocker.patch.object(grizzly_cli.cli, 'SCENARIOS', [
        create_scenario(
            'scenario-1',
            [],
            [
                'Given a user of type "RestApi" with weight "10" load testing "https://localhost"',
                'And repeat for "{{ integer * 0.10 }}" iterations'
                'And ask for value of variable "test_variable_2"',
                'And ask for value of variable "test_variable_1"',
            ]
        ),
        create_scenario(
            'scenario-2',
            [
                'And ask for value of variable "bar"',
            ],
            [
                'Given a user of type "MessageQueueUser" load testing "mqs://localhost"',
                'And ask for value of variable "foo"',
            ],
        )
    ])

    import grizzly_cli.cli
    render = mocker.spy(grizzly_cli.cli.Template, 'render')  # type: ignore

    _distribution_of_users_per_scenario(arguments, {
        'TESTDATA_VARIABLE_boolean': 'True',
        'TESTDATA_VARIABLE_integer': '100',
        'TESTDATA_VARIABLE_float': '1.33',
        'TESTDATA_VARIABLE_string': 'foo bar',
        'TESTDATA_VARIABLE_neg_integer': '-100',
        'TESTDATA_VARIABLE_neg_float': '-1.33',
        'TESTDATA_VARIABLE_pad_integer': '001',
    })
    capture = capsys.readouterr()

    assert capture.err == ''
    assert capture.out == dedent('''
        feature file test.feature will execute in total 11 iterations

        each scenario will execute accordingly:

        identifier  symbol  weight  iter    description
        -----------|-------|-------|-------|------------|
        02ce541f       A       10.0      10 scenario-1
        91d624d8       B        1.0       1 scenario-2
        -----------|-------|-------|-------|------------|

        timeline of user scheduling will look as following:
        AAAAABAAAAA

    ''')
    assert ask_yes_no.call_count == 2
    args, _ = ask_yes_no.call_args_list[-1]
    assert args[0] == 'continue?'

    assert render.call_count == 1
    _, kwargs = render.call_args_list[-1]

    assert kwargs.get('boolean', None)
    assert kwargs.get('integer', None) == 100
    assert kwargs.get('float', None) == 1.33
    assert kwargs.get('string', None) == 'foo bar'
    assert kwargs.get('neg_integer', None) == -100
    assert kwargs.get('neg_float', None) == -1.33
    assert kwargs.get('pad_integer', None) == '001'

    mocker.patch.object(grizzly_cli.cli, 'SCENARIOS', [
        create_scenario(
            'scenario-1 testing a lot of stuff',
            [],
            [
                'Given a user of type "RestApi" with weight "10" load testing "https://localhost"',
                'And repeat for "500" iterations'
                'And ask for value of variable "test_variable_2"',
                'And ask for value of variable "test_variable_1"',
            ]
        ),
        create_scenario(
            'scenario-2 testing a lot more of many different things that scenario-1 does not test',
            [
                'And ask for value of variable "bar"',
            ],
            [
                'Given a user of type "MessageQueueUser" with weight "5" load testing "mqs://localhost"',
                'And repeat for "750" iterations'
                'And ask for value of variable "foo"',
            ],
        )
    ])

    arguments = Namespace(file='integration.feature', yes=True)

    _distribution_of_users_per_scenario(arguments, {})
    capture = capsys.readouterr()

    assert capture.err == ''
    assert capture.out == dedent('''
        feature file integration.feature will execute in total 1250 iterations

        each scenario will execute accordingly:

        identifier  symbol  weight  iter    description
        -----------|-------|-------|-------|-------------------------------------------------------------------------------------|
        5b66789b       A       10.0     500 scenario-1 testing a lot of stuff
        d06b7314       B        5.0     750 scenario-2 testing a lot more of many different things that scenario-1 does not test
        -----------|-------|-------|-------|-------------------------------------------------------------------------------------|

        timeline of user scheduling will look as following:
        ABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABA \\
        ABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABA \\
        ABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABA \\
        ABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABA \\
        ABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABA \\
        ...
        ABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABA \\
        ABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABA \\
        ABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABA \\
        ABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABA \\
        ABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAABAAB

    ''')
    assert ask_yes_no.call_count == 2


def test__run_distributed(capsys: CaptureFixture, mocker: MockerFixture) -> None:
    mocker.patch('grizzly_cli.cli.getuser', side_effect=['test-user'] * 2)
    mocker.patch('grizzly_cli.cli.get_default_mtu', side_effect=[None, '1400'])
    mocker.patch('grizzly_cli.cli.build', side_effect=[255, 0])
    mocker.patch('grizzly_cli.cli.list_images', side_effect=[{}, {'grizzly-cli-test-project': {'test-user': {}}}])

    import grizzly_cli.cli
    mocker.patch.object(grizzly_cli.cli, 'EXECUTION_CONTEXT', '/tmp/execution-context')
    mocker.patch.object(grizzly_cli.cli, 'STATIC_CONTEXT', '/tmp/static-context')
    mocker.patch.object(grizzly_cli.cli, 'MOUNT_CONTEXT', '/tmp/mount-context')
    mocker.patch.object(grizzly_cli.cli, 'PROJECT_NAME', 'grizzly-cli-test-project')

    run_command = mocker.patch('grizzly_cli.cli.run_command', side_effect=[1, 0])

    arguments = Namespace(file='test.feature', workers=3, container_system='docker', id=None, build=True, force_build=False)

    try:
        # this is set in the devcontainer
        for key in environ.keys():
            if key.startswith('GRIZZLY_'):
                del environ[key]

        assert _run_distributed(arguments, {}, {}) == 255
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
        assert environ.get('GRIZZLY_ENVIRONMENT_FILE', None) is None

        # this is set in the devcontainer
        for key in environ.keys():
            if key.startswith('GRIZZLY_'):
                del environ[key]

        assert _run_distributed(
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
            '!! something went wrong, check container logs with:\n'
            'docker container logs grizzly-cli-test-project-test-user_master_1\n'
            'docker container logs grizzly-cli-test-project-test-user_worker_1\n'
            'docker container logs grizzly-cli-test-project-test-user_worker_2\n'
            'docker container logs grizzly-cli-test-project-test-user_worker_3\n'
        )

        assert run_command.call_count == 2
        args, _ = run_command.call_args_list[0]
        assert args[0] == [
            'docker-compose',
            '-p', 'grizzly-cli-test-project-test-user',
            '-f', '/tmp/static-context/compose.yaml',
            'up',
            '--scale', 'worker=3',
            '--remove-orphans',
        ]
        args, _ = run_command.call_args_list[1]
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
    finally:
        for key in environ.keys():
            if key.startswith('GRIZZLY_'):
                del environ[key]

def test__run_local(mocker: MockerFixture) -> None:
    run_command = mocker.patch('grizzly_cli.cli.run_command', side_effect=[0])

    arguments = Namespace(file='test.feature')

    assert environ.get('GRIZZLY_TEST_VAR', None) is None

    try:
        assert _run_local(
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

def test__ask_yes_no(capsys: CaptureFixture, mocker: MockerFixture) -> None:
    get_input = mocker.patch('grizzly_cli.cli._get_input', side_effect=['yeah', 'n', 'y'])

    with pytest.raises(KeyboardInterrupt):
        _ask_yes_no('continue?')

    capture = capsys.readouterr()
    assert capture.err == ''
    assert capture.out == 'you must answer y (yes) or n (no)\n'

    assert get_input.call_count == 2
    for args, _ in get_input.call_args_list:
        assert args[0] == 'continue? [y/n]: '
    get_input.reset_mock()

    _ask_yes_no('are you sure you know what you are doing?')
    capture = capsys.readouterr()
    assert capture.err == ''
    assert capture.out == ''

    assert get_input.call_count == 1
    for args, _ in get_input.call_args_list:
        assert args[0] == 'are you sure you know what you are doing? [y/n]: '

def test_main(capsys: CaptureFixture, mocker: MockerFixture) -> None:
    mocker.patch('grizzly_cli.cli.get_hostname', side_effect=['localhost'] * 2)
    mocker.patch('grizzly_cli.cli._find_variable_names_in_questions', side_effect=[['foo', 'bar'], []])
    mocker.patch('grizzly_cli.cli._distribution_of_users_per_scenario', autospec=True)
    ask_yes_no = mocker.patch('grizzly_cli.cli._ask_yes_no', autospec=True)
    run_distributed = mocker.patch('grizzly_cli.cli._run_distributed', side_effect=[0])
    run_local = mocker.patch('grizzly_cli.cli._run_local', side_effect=[0])
    get_input = mocker.patch('grizzly_cli.cli._get_input', side_effect=['bar', 'foo'])

    import grizzly_cli.cli
    mocker.patch.object(grizzly_cli.cli, 'EXECUTION_CONTEXT', '/tmp/execution-context')
    mocker.patch.object(grizzly_cli.cli, 'MOUNT_CONTEXT', '/tmp/mount-context')

    arguments = Namespace(file='test.feature', environment_file='configuration.yaml', mode='dist', verbose=True)
    mocker.patch('grizzly_cli.cli._parse_arguments', side_effect=[arguments])

    assert main() == 0

    capture = capsys.readouterr()

    assert run_local.call_count == 0
    assert run_distributed.call_count == 1
    args, _ = run_distributed.call_args_list[-1]

    assert args[0] is arguments

    # windows hack... one place uses C:\ and getcwd uses c:\
    args[1]['GRIZZLY_CONFIGURATION_FILE'] = args[1]['GRIZZLY_CONFIGURATION_FILE'].lower()
    assert args[1] == {
        'GRIZZLY_CLI_HOST': 'localhost',
        'GRIZZLY_EXECUTION_CONTEXT': '/tmp/execution-context',
        'GRIZZLY_MOUNT_CONTEXT': '/tmp/mount-context',
        'GRIZZLY_CONFIGURATION_FILE': path.join(getcwd(), 'configuration.yaml').lower(),
        'TESTDATA_VARIABLE_foo': 'bar',
        'TESTDATA_VARIABLE_bar': 'foo',
    }
    assert args[2] == {
        'master': [],
        'worker': [],
        'common': ['--stop', '--verbose', '--no-logcapture', '--no-capture', '--no-capture-stderr'],
    }

    assert ask_yes_no.call_count == 1
    assert get_input.call_count == 2
    args,  _ = get_input.call_args_list[0]
    assert args[0] == 'initial value for "foo": '
    args,  _ = get_input.call_args_list[1]
    assert args[0] == 'initial value for "bar": '

    assert capture.err == ''
    assert capture.out == (
        'feature file requires values for 2 variables\n'
        'the following values was provided:\n'
        'foo = bar\n'
        'bar = foo\n'
    )

    arguments = Namespace(file='test.feature', environment_file='configuration.yaml', mode='local', verbose=False)
    mocker.patch('grizzly_cli.cli._parse_arguments', side_effect=[arguments])

    assert main() == 0

    capture = capsys.readouterr()

    assert run_local.call_count == 1
    assert run_distributed.call_count == 1
    args, _ = run_local.call_args_list[-1]

    assert args[0] is arguments

    # windows hack... one place uses C:\ and getcwd uses c:\
    args[1]['GRIZZLY_CONFIGURATION_FILE'] = args[1]['GRIZZLY_CONFIGURATION_FILE'].lower()

    assert args[1] == {
        'GRIZZLY_CLI_HOST': 'localhost',
        'GRIZZLY_EXECUTION_CONTEXT': '/tmp/execution-context',
        'GRIZZLY_MOUNT_CONTEXT': '/tmp/mount-context',
        'GRIZZLY_CONFIGURATION_FILE': path.join(getcwd(), 'configuration.yaml').lower(),
    }
    assert args[2] == {
        'master': [],
        'worker': [],
        'common': ['--stop'],
    }

    assert ask_yes_no.call_count == 1
    assert get_input.call_count == 2

    assert capture.err == ''
    assert capture.out == ''

    mocker.patch('grizzly_cli.cli._parse_arguments', side_effect=[KeyboardInterrupt, ValueError('test error')])

    assert main() == 1
    capture = capsys.readouterr()

    assert capture.err == ''
    assert capture.out == (
        '\n'
        '\n!! aborted grizzly-cli\n'
    )

    assert main() == 1
    capture = capsys.readouterr()

    assert capture.err == ''
    assert capture.out == (
        '\n'
        'test error\n'
        '\n!! aborted grizzly-cli\n'
    )
