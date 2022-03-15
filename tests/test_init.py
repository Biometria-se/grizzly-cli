from re import template
from shutil import rmtree
from argparse import Namespace

from _pytest.tmpdir import TempPathFactory
from _pytest.capture import CaptureFixture
from pytest_mock import MockerFixture

from grizzly_cli.init import tree, init

from .helpers import onerror


def test_tree(tmp_path_factory: TempPathFactory) -> None:
    test_context = tmp_path_factory.mktemp('test_context')

    (test_context / 'a' / 'b' / 'c').mkdir(parents=True)

    (test_context / 'a' / 'file-a1.txt').touch()
    (test_context / 'a' / 'file-a2.txt').touch()

    (test_context / 'a' / 'b' / 'file-b1.txt').touch()

    (test_context / 'a' / 'b' / 'c' / 'file-c1.txt').touch()
    (test_context / 'a' / 'b' / 'c' / 'file-c2.txt').touch()

    (test_context / 'root.yaml').touch()

    try:
        assert '\n'.join([line for line in tree(test_context)]) == '''├── a
│   ├── b
│   │   ├── file-b1.txt
│   │   └── c
│   │       ├── file-c2.txt
│   │       └── file-c1.txt
│   ├── file-a1.txt
│   └── file-a2.txt
└── root.yaml'''
    finally:
        rmtree(test_context, onerror=onerror)


def test_init(tmp_path_factory: TempPathFactory, capsys: CaptureFixture, mocker: MockerFixture) -> None:
    test_context = tmp_path_factory.mktemp('test_context')

    test_existing = test_context / 'foobar'
    test_existing.mkdir()

    mocker.patch('grizzly_cli.init.EXECUTION_CONTEXT', str(test_context))

    try:
        arguments = Namespace(project='foobar', with_mq=False, grizzly_version=None)

        assert init(arguments) == 1

        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == f'"foobar" already exists in {test_context}\n'

        (test_existing / 'environments').mkdir()
        (test_existing / 'features').mkdir()
        (test_existing / 'requirements.txt').touch()

        mocker.patch('grizzly_cli.init.EXECUTION_CONTEXT', str(test_existing))

        assert init(arguments) == 1

        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == f'''oops, looks like you are already in a grizzly project directory

{test_existing}
├── features
├── environments
└── requirements.txt
'''

        rmtree(test_existing, onerror=onerror)

        question_mock = mocker.patch('grizzly_cli.init.ask_yes_no', side_effect=[None] * 4)
        mocker.patch('grizzly_cli.init.EXECUTION_CONTEXT', str(test_context))

        assert init(arguments) == 0

        assert question_mock.call_count == 1
        args, _ = question_mock.call_args_list[-1]
        assert args[0] == '''the following structure will be created:

    foobar
    ├── features
    │   ├── environment.py
    │   ├── steps
    │   │   └── steps.py
    │   ├── foobar.feature
    │   └── requests
    ├── environments
    │   └── foobar.yaml
    └── requirements.txt

do you want to create grizzly project "foobar"?'''

        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == '''successfully created project "foobar", with the following options:
  • without IBM MQ support
  • latest grizzly version
'''

        template_root = test_context / 'foobar'
        assert template_root.is_dir()
        assert (template_root / 'environments').is_dir()
        environments_file = template_root / 'environments' / 'foobar.yaml'
        assert environments_file.is_file()
        assert environments_file.read_text() == '''configuration:
  template:
    host: https://localhost
'''

        assert (template_root / 'features').is_dir()
        feature_file = template_root / 'features' / 'foobar.feature'
        assert feature_file.is_file()
        assert feature_file.read_text() == '''Feature: Template feature file
  Scenario: Template scenario
    Given a user of type "RestApi" with weight "1" load testing "$conf::template.host"
'''

        environment_file = template_root / 'features' / 'environment.py'
        assert environment_file.is_file()
        assert environment_file.read_text() == 'from grizzly.environment import *\n\n'

        assert (template_root / 'features' / 'requests').is_dir()

        assert (template_root / 'features' / 'steps').is_dir()

        steps_file = template_root / 'features' / 'steps' / 'steps.py'
        assert steps_file.is_file()
        assert steps_file.read_text() == 'from grizzly.steps import *\n\n'

        requirements_file = template_root / 'requirements.txt'
        assert requirements_file.is_file()
        assert requirements_file.read_text() == 'grizzly-loadtester\n'

        created_structure = '\n'.join([line for line in tree(template_root)])
        assert created_structure == '''├── features
│   ├── environment.py
│   ├── steps
│   │   └── steps.py
│   ├── foobar.feature
│   └── requests
├── environments
│   └── foobar.yaml
└── requirements.txt'''

        rmtree(template_root, onerror=onerror)

        capsys.readouterr()

        arguments.with_mq = True

        assert init(arguments) == 0

        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == '''successfully created project "foobar", with the following options:
  • with IBM MQ support
  • latest grizzly version
'''
        requirements_file = template_root / 'requirements.txt'
        assert requirements_file.is_file()
        assert requirements_file.read_text() == 'grizzly-loadtester[mq]\n'

        rmtree(template_root, onerror=onerror)
        arguments.with_mq = False
        arguments.grizzly_version = '1.2.4'

        assert init(arguments) == 0

        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == '''successfully created project "foobar", with the following options:
  • without IBM MQ support
  • pinned to grizzly version 1.2.4
'''
        requirements_file = template_root / 'requirements.txt'
        assert requirements_file.is_file()
        assert requirements_file.read_text() == 'grizzly-loadtester==1.2.4\n'

        rmtree(template_root, onerror=onerror)

        arguments.with_mq = True
        arguments.grizzly_version = '1.5.0'

        assert init(arguments) == 0

        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == '''successfully created project "foobar", with the following options:
  • with IBM MQ support
  • pinned to grizzly version 1.5.0
'''
        requirements_file = template_root / 'requirements.txt'
        assert requirements_file.is_file()
        assert requirements_file.read_text() == 'grizzly-loadtester[mq]==1.5.0\n'

    finally:
        rmtree(test_context, onerror=onerror)

