from shutil import rmtree

from _pytest.tmpdir import TempPathFactory
from ..helpers import run_command, onerror

def test_e2e_init_no_mq(tmp_path_factory: TempPathFactory) -> None:
    test_context = tmp_path_factory.mktemp('test_context')

    try:
        rc, output = run_command(
            ['grizzly-cli', 'init', 'foobar', '--yes'],
            cwd=str(test_context),
        )
        assert rc == 0
        assert ''.join(output) == '''the following structure will be created:

    foobar
    ├── environments
    │   └── foobar.yaml
    ├── features
    │   ├── environment.py
    │   ├── steps
    │   │   └── steps.py
    │   ├── foobar.feature
    │   └── requests
    └── requirements.txt

successfully created project "foobar", with the following options:
  • without IBM MQ support
  • latest grizzly version
'''

        assert (test_context / 'foobar').is_dir()
        assert (test_context / 'foobar' / 'environments').is_dir()
        requirements_file = test_context / 'foobar' / 'requirements.txt'
        assert requirements_file.is_file()
        assert requirements_file.read_text() == 'grizzly-loadtester\n'

        environments_file = test_context / 'foobar' / 'environments' / 'foobar.yaml'
        assert environments_file.is_file()
        assert environments_file.read_text() == '''configuration:
  template:
    host: https://localhost
'''

        features_dir = test_context / 'foobar' / 'features'
        assert features_dir.is_dir()

        assert (features_dir / 'requests').is_dir()
        assert list((features_dir / 'requests').rglob('**/*')) == []

        assert (features_dir / 'steps').is_dir()
        steps_file = features_dir / 'steps' / 'steps.py'
        assert steps_file.is_file()
        assert steps_file.read_text() == 'from grizzly.steps import *\n\n'

        environment_file = features_dir / 'environment.py'
        assert environment_file.is_file()
        assert environment_file.read_text() == 'from grizzly.environment import *\n\n'

        feature_file = features_dir / 'foobar.feature'
        assert feature_file.is_file()
        assert feature_file.read_text() == '''Feature: Template feature file
  Scenario: Template scenario
    Given a user of type "RestApi" with weight "1" load testing "$conf::template.host"
'''
    finally:
        rmtree(test_context, onerror=onerror)


def test_e2e_init_mq(tmp_path_factory: TempPathFactory) -> None:
    test_context = tmp_path_factory.mktemp('test_context')

    try:
        rc, output = run_command(
            ['grizzly-cli', 'init', 'foobar', '--yes', '--with-mq'],
            cwd=str(test_context),
        )
        assert rc == 0
        assert ''.join(output) == '''the following structure will be created:

    foobar
    ├── environments
    │   └── foobar.yaml
    ├── features
    │   ├── environment.py
    │   ├── steps
    │   │   └── steps.py
    │   ├── foobar.feature
    │   └── requests
    └── requirements.txt

successfully created project "foobar", with the following options:
  • with IBM MQ support
  • latest grizzly version
'''

        assert (test_context / 'foobar').is_dir()
        assert (test_context / 'foobar' / 'environments').is_dir()
        requirements_file = test_context / 'foobar' / 'requirements.txt'
        assert requirements_file.is_file()
        assert requirements_file.read_text() == 'grizzly-loadtester[mq]\n'

        environments_file = test_context / 'foobar' / 'environments' / 'foobar.yaml'
        assert environments_file.is_file()
        assert environments_file.read_text() == '''configuration:
  template:
    host: https://localhost
'''

        features_dir = test_context / 'foobar' / 'features'
        assert features_dir.is_dir()

        assert (features_dir / 'requests').is_dir()
        assert list((features_dir / 'requests').rglob('**/*')) == []

        assert (features_dir / 'steps').is_dir()
        steps_file = features_dir / 'steps' / 'steps.py'
        assert steps_file.is_file()
        assert steps_file.read_text() == 'from grizzly.steps import *\n\n'

        environment_file = features_dir / 'environment.py'
        assert environment_file.is_file()
        assert environment_file.read_text() == 'from grizzly.environment import *\n\n'

        feature_file = features_dir / 'foobar.feature'
        assert feature_file.is_file()
        assert feature_file.read_text() == '''Feature: Template feature file
  Scenario: Template scenario
    Given a user of type "RestApi" with weight "1" load testing "$conf::template.host"
'''
    finally:
        rmtree(test_context, onerror=onerror)


def test_e2e_init_mq_grizzly_version(tmp_path_factory: TempPathFactory) -> None:
    test_context = tmp_path_factory.mktemp('test_context')

    try:
        rc, output = run_command(
            ['grizzly-cli', 'init', 'foobar', '--yes', '--with-mq', '--grizzly-version', '1.1.1'],
            cwd=str(test_context),
        )
        assert rc == 0
        assert ''.join(output) == '''the following structure will be created:

    foobar
    ├── environments
    │   └── foobar.yaml
    ├── features
    │   ├── environment.py
    │   ├── steps
    │   │   └── steps.py
    │   ├── foobar.feature
    │   └── requests
    └── requirements.txt

successfully created project "foobar", with the following options:
  • with IBM MQ support
  • pinned to grizzly version 1.1.1
'''

        assert (test_context / 'foobar').is_dir()
        assert (test_context / 'foobar' / 'environments').is_dir()
        requirements_file = test_context / 'foobar' / 'requirements.txt'
        assert requirements_file.is_file()
        assert requirements_file.read_text() == 'grizzly-loadtester[mq]==1.1.1\n'

        environments_file = test_context / 'foobar' / 'environments' / 'foobar.yaml'
        assert environments_file.is_file()
        assert environments_file.read_text() == '''configuration:
  template:
    host: https://localhost
'''

        features_dir = test_context / 'foobar' / 'features'
        assert features_dir.is_dir()

        assert (features_dir / 'requests').is_dir()
        assert list((features_dir / 'requests').rglob('**/*')) == []

        assert (features_dir / 'steps').is_dir()
        steps_file = features_dir / 'steps' / 'steps.py'
        assert steps_file.is_file()
        assert steps_file.read_text() == 'from grizzly.steps import *\n\n'

        environment_file = features_dir / 'environment.py'
        assert environment_file.is_file()
        assert environment_file.read_text() == 'from grizzly.environment import *\n\n'

        feature_file = features_dir / 'foobar.feature'
        assert feature_file.is_file()
        assert feature_file.read_text() == '''Feature: Template feature file
  Scenario: Template scenario
    Given a user of type "RestApi" with weight "1" load testing "$conf::template.host"
'''
    finally:
        rmtree(test_context, onerror=onerror)
