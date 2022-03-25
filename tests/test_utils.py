from typing import Any, Dict, List, Tuple, Union
from os import chdir, getcwd
from textwrap import dedent
from importlib import reload
from shutil import rmtree
from argparse import Namespace
from tempfile import gettempdir

import pytest

from _pytest.tmpdir import TempPathFactory
from _pytest.capture import CaptureFixture
from pytest_mock import MockerFixture
from unittest.mock import mock_open, patch as unittest_patch
from requests_mock import Mocker as RequestsMocker

from grizzly_cli.utils import (
    get_docker_compose_version,
    is_docker_compose_v2,
    parse_feature_file,
    list_images,
    get_default_mtu,
    requirements,
    run_command,
    get_distributed_system,
    find_variable_names_in_questions,
    distribution_of_users_per_scenario,
    ask_yes_no,
    get_dependency_versions,
)

from .helpers import onerror, create_scenario

CWD = getcwd()


def test_parse_feature_file(tmp_path_factory: TempPathFactory) -> None:
    test_context = tmp_path_factory.mktemp('test_context')
    test_context_root = str(test_context)
    feature_file = test_context / 'test.feature'
    feature_file.touch()
    feature_file.write_text(dedent('''
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
        reload(grizzly_cli.utils)

        assert len(grizzly_cli.SCENARIOS) == 0
        print(id(grizzly_cli.SCENARIOS))

        parse_feature_file('test.feature')

        import grizzly_cli

        cached_scenarios = grizzly_cli.SCENARIOS.copy()
        assert len(grizzly_cli.SCENARIOS) == 2
        assert list(grizzly_cli.SCENARIOS)[0].name == 'scenario-1'
        assert len(list(grizzly_cli.SCENARIOS)[0].steps) == 2
        assert len(list(grizzly_cli.SCENARIOS)[0].background_steps) == 2
        assert list(grizzly_cli.SCENARIOS)[1].name == 'scenario-2'
        assert len(list(grizzly_cli.SCENARIOS)[1].steps) == 3
        assert len(list(grizzly_cli.SCENARIOS)[1].background_steps) == 2

        parse_feature_file('test.feature')

        import grizzly_cli

        assert grizzly_cli.SCENARIOS == cached_scenarios

    finally:
        chdir(CWD)
        rmtree(test_context_root, onerror=onerror)


def test_list_images(mocker: MockerFixture) -> None:
    check_output = mocker.patch('grizzly_cli.utils.subprocess.check_output', side_effect=[(
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
    check_output = mocker.patch('grizzly_cli.utils.subprocess.check_output', side_effect=[
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
    terminate = mocker.patch('grizzly_cli.utils.subprocess.Popen.terminate', autospec=True)
    wait = mocker.patch('grizzly_cli.utils.subprocess.Popen.wait', autospec=True)

    def popen___init___no_stdout(*args: Tuple[Any, ...], **kwargs: Dict[str, Any]) -> None:
        setattr(args[0], 'returncode', 133)
        setattr(args[0], 'stdout', None)

    mocker.patch('grizzly_cli.utils.subprocess.Popen.__init__', popen___init___no_stdout)
    poll_mock = mocker.patch('grizzly_cli.utils.subprocess.Popen.poll', side_effect=[None])
    kill_mock = mocker.patch('grizzly_cli.utils.subprocess.Popen.kill', side_effect=[RuntimeError, None])

    assert run_command([]) == 133

    capture = capsys.readouterr()
    assert capture.err == ''
    assert capture.out == ''

    assert terminate.call_count == 1
    assert wait.call_count == 1
    assert poll_mock.call_count == 1
    assert kill_mock.call_count == 1

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

    mocker.patch('grizzly_cli.utils.subprocess.Popen.terminate', side_effect=[KeyboardInterrupt])
    mocker.patch('grizzly_cli.utils.subprocess.Popen.__init__', popen___init__)
    poll_mock = mocker.patch('grizzly_cli.utils.subprocess.Popen.poll', side_effect=[None] * 3)

    assert run_command([], {}) == 0

    capture = capsys.readouterr()
    assert capture.err == ''
    assert capture.out == (
        'first line\n'
        'second line\n'
    )

    assert wait.call_count == 2
    assert poll_mock.call_count == 3
    assert kill_mock.call_count == 2


def test_get_distributed_system(capsys: CaptureFixture, mocker: MockerFixture) -> None:
    which = mocker.patch('grizzly_cli.utils.which', side_effect=[
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
    assert get_distributed_system() is None  # neither
    capture = capsys.readouterr()
    assert capture.out == 'neither "podman" nor "docker" found in PATH\n'
    assert which.call_count == 2
    which.reset_mock()

    # test 2
    assert get_distributed_system() is None
    capture = capsys.readouterr()
    assert which.call_count == 2
    assert capture.out == (
        '!! podman might not work due to buildah missing support for `RUN --mount=type=ssh`: https://github.com/containers/buildah/issues/2835\n'
        '"podman-compose" not found in PATH\n'
    )
    which.reset_mock()

    # test 3
    assert get_distributed_system() == 'podman'
    capture = capsys.readouterr()
    assert which.call_count == 2
    assert capture.out == (
        '!! podman might not work due to buildah missing support for `RUN --mount=type=ssh`: https://github.com/containers/buildah/issues/2835\n'
    )
    which.reset_mock()

    # test 4
    assert get_distributed_system() is None
    capture = capsys.readouterr()
    assert which.call_count == 3
    assert capture.out == (
        '"docker-compose" not found in PATH\n'
    )
    which.reset_mock()

    # test 5
    assert get_distributed_system() == 'docker'
    capture = capsys.readouterr()
    assert which.call_count == 3
    assert capture.out == ''
    which.reset_mock()


def test_find_variable_names_in_questions(mocker: MockerFixture) -> None:
    mocker.patch('grizzly_cli.SCENARIOS', [])
    mocker.patch('grizzly_cli.utils.parse_feature_file', autospec=True)

    assert find_variable_names_in_questions('test.feature') == []

    mocker.patch('grizzly_cli.SCENARIOS', [
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
        find_variable_names_in_questions('test.feature')
    assert 'could not find variable name in "ask for value of variable test_variable_1"' in str(ve)

    mocker.patch('grizzly_cli.SCENARIOS', [
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
    variables = find_variable_names_in_questions('test.feature')
    assert len(variables) == 4
    assert variables == ['bar', 'foo', 'test_variable_1', 'test_variable_2']


def test_distribution_of_users_per_scenario(capsys: CaptureFixture, mocker: MockerFixture) -> None:
    arguments = Namespace(file='test.feature', yes=False)

    ask_yes_no = mocker.patch('grizzly_cli.utils.ask_yes_no', autospec=True)

    mocker.patch('grizzly_cli.SCENARIOS', [
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

    distribution_of_users_per_scenario(arguments, {})
    capture = capsys.readouterr()

    assert capture.err == ''
    print(capture.out)
    assert capture.out == dedent('''
        feature file test.feature will execute in total 2 iterations

        each scenario will execute accordingly:

        identifier   symbol   weight  #  description
        -----------|--------|-------|--|-------------|
        02ce541f       A         1.0  1  scenario-1
        91d624d8       B         1.0  1  scenario-2
        -----------|--------|-------|--|-------------|

        timeline of user scheduling will look as following:
        AB

    ''')
    capsys.readouterr()
    assert ask_yes_no.call_count == 1
    args, _ = ask_yes_no.call_args_list[-1]
    assert args[0] == 'continue?'

    mocker.patch('grizzly_cli.SCENARIOS', [
        create_scenario(
            'scenario-1',
            [],
            [],
        ),
    ])

    with pytest.raises(ValueError) as ve:
        distribution_of_users_per_scenario(arguments, {})
    assert 'scenario-1 does not have any steps' in str(ve)

    mocker.patch('grizzly_cli.SCENARIOS', [
        create_scenario(
            'scenario-1',
            [],
            ['And repeat for "10" iterations'],
        ),
    ])

    with pytest.raises(ValueError) as ve:
        distribution_of_users_per_scenario(arguments, {})
    assert 'scenario-1 does not have a user type' in str(ve)

    mocker.patch('grizzly_cli.SCENARIOS', [
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

    import grizzly_cli.utils

    render = mocker.spy(grizzly_cli.utils.Template, 'render')  # type: ignore

    distribution_of_users_per_scenario(arguments, {
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
    print(capture.out)
    assert capture.out == dedent('''
        feature file test.feature will execute in total 11 iterations

        each scenario will execute accordingly:

        identifier   symbol   weight   #  description
        -----------|--------|-------|---|-------------|
        02ce541f       A        10.0  10  scenario-1
        91d624d8       B         1.0   1  scenario-2
        -----------|--------|-------|---|-------------|

        timeline of user scheduling will look as following:
        AAAAABAAAAA

    ''')
    capsys.readouterr()
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

    mocker.patch('grizzly_cli.SCENARIOS', [
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

    distribution_of_users_per_scenario(arguments, {})
    capture = capsys.readouterr()

    assert capture.err == ''
    print(capture.out)
    assert capture.out == dedent('''
        feature file integration.feature will execute in total 1250 iterations

        each scenario will execute accordingly:

        identifier   symbol   weight    #  description
        -----------|--------|-------|----|--------------------------------------------------------------------------------------|
        5b66789b       A        10.0  500  scenario-1 testing a lot of stuff
        d06b7314       B         5.0  750  scenario-2 testing a lot more of many different things that scenario-1 does not test
        -----------|--------|-------|----|--------------------------------------------------------------------------------------|

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
    capsys.readouterr()
    assert ask_yes_no.call_count == 2


def test_ask_yes_no(capsys: CaptureFixture, mocker: MockerFixture) -> None:
    get_input = mocker.patch('grizzly_cli.utils.get_input', side_effect=['yeah', 'n', 'y'])

    with pytest.raises(KeyboardInterrupt):
        ask_yes_no('continue?')

    capture = capsys.readouterr()
    assert capture.err == ''
    assert capture.out == 'you must answer y (yes) or n (no)\n'

    assert get_input.call_count == 2
    for args, _ in get_input.call_args_list:
        assert args[0] == 'continue? [y/n]: '
    get_input.reset_mock()

    ask_yes_no('are you sure you know what you are doing?')
    capture = capsys.readouterr()
    assert capture.err == ''
    assert capture.out == ''

    assert get_input.call_count == 1
    for args, _ in get_input.call_args_list:
        assert args[0] == 'are you sure you know what you are doing? [y/n]: '


def test_get_dependency_versions_git(mocker: MockerFixture, tmp_path_factory: TempPathFactory, capsys: CaptureFixture) -> None:
    test_context = tmp_path_factory.mktemp('test_context')
    requirements_file = test_context / 'requirements.txt'

    mocker.patch('grizzly_cli.EXECUTION_CONTEXT', str(test_context))

    try:
        with pytest.raises(FileNotFoundError) as fne:
            get_dependency_versions()
        capsys.readouterr()

        assert fne.value.errno == 2
        assert fne.value.strerror == 'No such file or directory'

        requirements_file.touch()

        assert ('(unknown)', '(unknown)',) == get_dependency_versions()

        capture = capsys.readouterr()
        assert capture.err == f'!! unable to find grizzly dependency in {requirements_file.absolute()}\n'
        assert capture.out == ''

        requirements_file.write_text('git+https://github.com/Biometria-se/grizzly.git@v1.5.3#egg=grizzly-loadtester')
        import subprocess
        with mocker.patch.context_manager(subprocess, 'check_call', return_value=1):
            assert ('(unknown)', '(unknown)',) == get_dependency_versions()

            capture = capsys.readouterr()
            assert capture.err == '!! unable to get git repo https://github.com/Biometria-se/grizzly.git and branch v1.5.3\n'
            assert capture.out == ''

            assert subprocess.check_call.call_count == 2  # type: ignore  # pylint: disable=no-member

            # git clone...
            args, kwargs = subprocess.check_call.call_args_list[0]  # type: ignore  # pylint: disable=no-member
            assert len(args) == 1
            args = args[0]
            assert args[:-1] == ['git', 'clone', '--filter=blob:none', '-q', 'https://github.com/Biometria-se/grizzly.git']
            assert args[-1].startswith(gettempdir())
            assert args[-1].endswith('grizzly-loadtester_3f210f1809f6ca85ef414b2b4d450bf54353b5e0')
            assert not kwargs.get('shell', True)
            assert kwargs.get('stdout', None) == subprocess.DEVNULL
            assert kwargs.get('stderr', None) == subprocess.DEVNULL

            # git checkout...
            args, kwargs = subprocess.check_call.call_args_list[1]  # type: ignore  # pylint: disable=no-member
            assert len(args) == 1
            args = args[0]
            assert args == ['git', 'checkout', '-b', 'v1.5.3', '--track', 'origin/v1.5.3']
            assert kwargs.get('cwd', '').startswith(gettempdir())
            assert kwargs.get('cwd', '').endswith('grizzly-loadtester_3f210f1809f6ca85ef414b2b4d450bf54353b5e0')
            assert not kwargs.get('shell', True)
            assert kwargs.get('stdout', None) == subprocess.DEVNULL
            assert kwargs.get('stderr', None) == subprocess.DEVNULL

        with mocker.patch.context_manager(subprocess, 'check_call', return_value=0):
            with pytest.raises(FileNotFoundError) as fne:
                get_dependency_versions()
            assert fne.value.errno == 2
            assert fne.value.strerror == 'No such file or directory'

            with unittest_patch('builtins.open', side_effect=[
                mock_open(read_data='git+https://github.com/Biometria-se/grizzly.git@v1.5.3#egg=grizzly-loadtester\n').return_value,
                mock_open(read_data='').return_value,
            ]) as open_mock:
                assert ('(unknown)', '(unknown)',) == get_dependency_versions()

                capture = capsys.readouterr()
                assert capture.err == '!! unable to find "__version__" declaration in grizzly/__init__.py from https://github.com/Biometria-se/grizzly.git\n'
                assert capture.out == ''
                assert open_mock.call_count == 2

            with unittest_patch('builtins.open', side_effect=[
                mock_open(read_data='git+https://github.com/Biometria-se/grizzly.git@v1.5.3#egg=grizzly-loadtester\n').return_value,
                mock_open(read_data="__version__ = '0.0.0'").return_value,
                mock_open(read_data='').return_value,
            ]) as open_mock:
                assert ('(development)', '(unknown)',) == get_dependency_versions()

                capture = capsys.readouterr()
                assert capture.err == '!! unable to find "locust" dependency in requirements.txt from https://github.com/Biometria-se/grizzly.git\n'
                assert capture.out == ''

                assert open_mock.call_count == 3

            with unittest_patch('builtins.open', side_effect=[
                mock_open(read_data='git+https://github.com/Biometria-se/grizzly.git@v1.5.3#egg=grizzly-loadtester\n').return_value,
                mock_open(read_data="__version__ = '1.5.3'").return_value,
                mock_open(read_data='locust').return_value,
            ]) as open_mock:
                assert ('1.5.3', '(unknown)',) == get_dependency_versions()

                capture = capsys.readouterr()
                assert capture.err == '!! unable to find locust version in "locust" specified in requirements.txt from https://github.com/Biometria-se/grizzly.git\n'
                assert capture.out == ''

                assert open_mock.call_count == 3

            with unittest_patch('builtins.open', side_effect=[
                mock_open(read_data='git+https://github.com/Biometria-se/grizzly.git@v1.5.3#egg=grizzly-loadtester\n').return_value,
                mock_open(read_data="__version__ = '1.5.3'").return_value,
                mock_open(read_data='locust==2.2.1 \\ ').return_value,
            ]) as open_mock:
                assert ('1.5.3', '2.2.1',) == get_dependency_versions()

                capture = capsys.readouterr()
                assert capture.err == ''
                assert capture.out == ''

                assert open_mock.call_count == 3
    finally:
        rmtree(test_context, onerror=onerror)


def test_get_dependency_versions_pypi(mocker: MockerFixture, tmp_path_factory: TempPathFactory, capsys: CaptureFixture, requests_mock: RequestsMocker) -> None:
    test_context = tmp_path_factory.mktemp('test_context')
    requirements_file = test_context / 'requirements.txt'

    mocker.patch('grizzly_cli.EXECUTION_CONTEXT', str(test_context))

    try:
        with pytest.raises(FileNotFoundError) as fne:
            get_dependency_versions()
        capsys.readouterr()

        assert fne.value.errno == 2
        assert fne.value.strerror == 'No such file or directory'

        requirements_file.touch()

        assert ('(unknown)', '(unknown)',) == get_dependency_versions()

        capture = capsys.readouterr()
        assert capture.err == f'!! unable to find grizzly dependency in {requirements_file.absolute()}\n'
        assert capture.out == ''

        requirements_file.write_text('grizzly-loadtester')

        requests_mock.register_uri('GET', 'https://pypi.org/pypi/grizzly-loadtester/json', status_code=404)

        assert ('(unknown)', '(unknown)',) == get_dependency_versions()

        capture = capsys.readouterr()
        assert capture.err == '!! unable to get grizzly package information from https://pypi.org/pypi/grizzly-loadtester/json (404)\n'
        assert capture.out == ''

        requests_mock.register_uri('GET', 'https://pypi.org/pypi/grizzly-loadtester/json', status_code=200, text='{"info": {"version": "1.1.1"}}')
        requests_mock.register_uri('GET', 'https://pypi.org/pypi/grizzly-loadtester/1.1.1/json', status_code=400)

        assert ('1.1.1', '(unknown)',) == get_dependency_versions()

        capture = capsys.readouterr()
        assert capture.err == '!! unable to get grizzly 1.1.1 package information from https://pypi.org/pypi/grizzly-loadtester/1.1.1/json (400)\n'
        assert capture.out == ''

        requests_mock.register_uri('GET', 'https://pypi.org/pypi/grizzly-loadtester/1.1.1/json', status_code=200, text='{"info": {"requires_dist": []}}')

        assert ('1.1.1', '(unknown)',) == get_dependency_versions()

        capture = capsys.readouterr()
        assert capture.err == '!! could not find "locust" in requires_dist information for grizzly-loadtester 1.1.1\n'
        assert capture.out == ''

        requests_mock.register_uri('GET', 'https://pypi.org/pypi/grizzly-loadtester/1.1.1/json', status_code=200, text='{"info": {"requires_dist": ["requests", "locust"]}}')

        assert ('1.1.1', '(unknown)',) == get_dependency_versions()

        capture = capsys.readouterr()
        assert capture.err == '!! unable to find locust version in "locust" specified in pypi for grizzly-loadtester 1.1.1\n'
        assert capture.out == ''

        requests_mock.register_uri('GET', 'https://pypi.org/pypi/grizzly-loadtester/1.1.1/json', status_code=200, text='{"info": {"requires_dist": ["locust (==2.8.5)"]}}')

        assert ('1.1.1', '2.8.5',) == get_dependency_versions()

        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == ''

    finally:
        rmtree(test_context, onerror=onerror)


def test_requirements(mocker: MockerFixture, capsys: CaptureFixture, tmp_path_factory: TempPathFactory) -> None:
    test_context = tmp_path_factory.mktemp('test_context')
    requirements_file = test_context / 'requirements.txt'

    def wrapped_test(args: Namespace) -> int:
        return 1337

    try:
        assert not requirements_file.exists()

        wrapped = requirements(str(test_context))(wrapped_test)
        assert getattr(wrapped, '__wrapped__', None) is wrapped_test
        assert getattr(getattr(wrapped, '__wrapped__'), '__value__') == str(test_context)

        assert wrapped(Namespace()) == 1337

        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == (
            '!! created a default requirements.txt with one dependency:\n'
            'grizzly-loadtester\n\n'
        )
        assert requirements_file.exists()

    finally:
        rmtree(test_context, onerror=onerror)


def test_get_docker_compose_version(mocker: MockerFixture) -> None:
    mocker.patch('grizzly_cli.utils.subprocess.getoutput', side_effect=[
        '''docker-compose version 1.29.2, build 5becea4c
docker-py version: 5.0.0
CPython version: 3.7.10
OpenSSL version: OpenSSL 1.1.0l 10 Sep 2019''',
        'Docker Compose version v2.1.0'
    ])

    assert get_docker_compose_version() == (1, 29, 2,)
    assert get_docker_compose_version() == (2, 1, 0,)


def test_is_docker_compose_v2(mocker: MockerFixture) -> None:
    mocker.patch('grizzly_cli.utils.subprocess.getoutput', side_effect=[
        '''docker-compose version 1.29.2, build 5becea4c
docker-py version: 5.0.0
CPython version: 3.7.10
OpenSSL version: OpenSSL 1.1.0l 10 Sep 2019''',
        'Docker Compose version v2.1.0'
    ])

    assert not is_docker_compose_v2()
    assert is_docker_compose_v2()
