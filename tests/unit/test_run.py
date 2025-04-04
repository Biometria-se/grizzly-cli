import logging
from os import path
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from _pytest.capture import CaptureFixture
from _pytest.logging import LogCaptureFixture
from _pytest.tmpdir import TempPathFactory
from pytest_mock import MockerFixture
from jinja2 import Environment
from azure.core.exceptions import ClientAuthenticationError, ServiceRequestError
from azure.identity import ChainedTokenCredential
from azure.keyvault.secrets import SecretClient, SecretProperties, KeyVaultSecret

from grizzly_cli.run import run, create_parser, ScenarioTag, load_configuration_file, load_configuration, load_configuration_keyvault
from grizzly_cli.utils import setup_logging

from tests.helpers import CaseInsensitive, rm_rf, cwd, ANY


def test_run(capsys: CaptureFixture, mocker: MockerFixture, tmp_path_factory: TempPathFactory) -> None:
    setup_logging()

    original_tmp_path = tmp_path_factory._basetemp
    tmp_path_factory._basetemp = Path.cwd() / '.pytest_tmp'
    test_context = tmp_path_factory.mktemp('test_context')
    execution_context = test_context / 'execution-context'
    execution_context.mkdir()
    mount_context = test_context / 'mount-context'
    mount_context.mkdir()
    feature_file = execution_context / 'features' / 'test.feature'
    feature_file.parent.mkdir(parents=True, exist_ok=True)
    feature_file.write_text('Feature: this feature is testing something')
    (execution_context / 'configuration.yaml').write_text('configuration:')

    parser = ArgumentParser()

    sub_parsers = parser.add_subparsers(dest='test')

    create_parser(sub_parsers, parent='local')

    try:
        mocker.patch('grizzly_cli.run.grizzly_cli.EXECUTION_CONTEXT', str(execution_context))
        mocker.patch('grizzly_cli.run.grizzly_cli.MOUNT_CONTEXT', str(mount_context))
        mocker.patch('grizzly_cli.run.get_hostname', return_value='localhost')
        mocker.patch('grizzly_cli.run.find_variable_names_in_questions', side_effect=[['foo', 'bar'], [], [], [], [], [], [], []])
        mocker.patch('grizzly_cli.run.find_metadata_notices', side_effect=[[], ['is the event log cleared?'], ['hello world', 'foo bar'], [], [], [], [], []])
        mocker.patch('grizzly_cli.run.distribution_of_users_per_scenario', autospec=True)
        ask_yes_no_mock = mocker.patch('grizzly_cli.run.ask_yes_no', autospec=True)
        distributed_mock = mocker.MagicMock(return_value=0)
        local_mock = mocker.MagicMock(return_value=0)
        get_input_mock = mocker.patch('grizzly_cli.run.get_input', side_effect=['bar', 'foo'])

        setattr(getattr(run, '__wrapped__'), '__value__', str(execution_context))

        arguments = parser.parse_args([
            'run',
            '-e', f'{execution_context}/configuration.yaml',
            f'{execution_context}/features/test.feature',
            '--verbose'
        ])
        setattr(arguments, 'file', ' '.join(arguments.file))

        assert run(arguments, distributed_mock) == 0

        capture = capsys.readouterr()
        assert capture.out == ''
        assert capture.err == '''feature file requires values for 2 variables
the following values was provided:
foo = bar
bar = foo
'''

        local_mock.assert_not_called()
        distributed_mock.assert_called_once_with(
            arguments,
            {
                'GRIZZLY_CLI_HOST': 'localhost',
                'GRIZZLY_EXECUTION_CONTEXT': str(execution_context),
                'GRIZZLY_MOUNT_CONTEXT': str(mount_context),
                'GRIZZLY_CONFIGURATION_FILE': CaseInsensitive(path.join(execution_context, 'configuration.lock.yaml')),
                'TESTDATA_VARIABLE_foo': 'bar',
                'TESTDATA_VARIABLE_bar': 'foo',
            }, {
                'master': [],
                'worker': [],
                'common': ['--verbose', '--no-logcapture', '--no-capture', '--no-capture-stderr'],
            }
        )
        distributed_mock.reset_mock()

        ask_yes_no_mock.assert_called_once_with('continue?')
        ask_yes_no_mock.reset_mock()
        assert get_input_mock.call_count == 2
        args, kwargs = get_input_mock.call_args_list[0]
        assert kwargs == {}
        assert args[0] == 'initial value for "foo": '
        args, kwargs = get_input_mock.call_args_list[1]
        assert kwargs == {}
        assert args[0] == 'initial value for "bar": '
        get_input_mock.reset_mock()

        assert capture.out == ''
        assert capture.err == (
            'feature file requires values for 2 variables\n'
            'the following values was provided:\n'
            'foo = bar\n'
            'bar = foo\n'
        )

        arguments = parser.parse_args([
            'run',
            '-e', f'{execution_context}/configuration.yaml',
            f'{execution_context}/features/test.feature',
        ])
        setattr(arguments, 'file', ' '.join(arguments.file))

        assert run(arguments, local_mock) == 0

        capture = capsys.readouterr()

        distributed_mock.assert_not_called()
        local_mock.assert_called_once_with(
            arguments,
            {
                'GRIZZLY_CLI_HOST': 'localhost',
                'GRIZZLY_EXECUTION_CONTEXT': str(execution_context),
                'GRIZZLY_MOUNT_CONTEXT': str(mount_context),
                'GRIZZLY_CONFIGURATION_FILE': CaseInsensitive(path.join(execution_context, 'configuration.lock.yaml')),
            }, {
                'master': [],
                'worker': [],
                'common': [],
            }
        )
        local_mock.reset_mock()

        ask_yes_no_mock.assert_called_once_with('is the event log cleared?')
        ask_yes_no_mock.reset_mock()
        get_input_mock.assert_not_called()

        assert capture.err == ''
        assert capture.out == ''

        # with --yes, notices should only be printed, and not needed to be confirmed via ask_yes_no
        arguments = parser.parse_args([
            'run',
            '-e', f'{execution_context}/configuration.yaml',
            '--yes',
            f'{execution_context}/features/test.feature',
        ])
        setattr(arguments, 'file', ' '.join(arguments.file))

        assert run(arguments, local_mock) == 0

        distributed_mock.assert_not_called()

        local_mock.assert_called_once_with(
            arguments,
            {
                'GRIZZLY_CLI_HOST': 'localhost',
                'GRIZZLY_EXECUTION_CONTEXT': str(execution_context),
                'GRIZZLY_MOUNT_CONTEXT': str(mount_context),
                'GRIZZLY_CONFIGURATION_FILE': CaseInsensitive(path.join(execution_context, 'configuration.lock.yaml')),
            }, {
                'master': [],
                'worker': [],
                'common': [],
            }
        )
        local_mock.reset_mock()

        ask_yes_no_mock.assert_not_called()
        get_input_mock.assert_not_called()

        assert capture.err == ''
        assert capture.out == ''

        # no `csv_prefix` nothing should be added
        arguments = parser.parse_args([
            'run',
            '-e', f'{execution_context}/configuration.yaml',
            '--yes',
            f'{execution_context}/features/test.feature',
            '--csv-interval', '20',
        ])
        setattr(arguments, 'file', ' '.join(arguments.file))

        assert run(arguments, local_mock) == 0

        local_mock.assert_called_once_with(
            arguments,
            {
                'GRIZZLY_CLI_HOST': 'localhost',
                'GRIZZLY_EXECUTION_CONTEXT': str(execution_context),
                'GRIZZLY_MOUNT_CONTEXT': str(mount_context),
                'GRIZZLY_CONFIGURATION_FILE': CaseInsensitive(path.join(execution_context, 'configuration.lock.yaml')),
            }, {
                'master': [],
                'worker': [],
                'common': [],
            }
        )
        local_mock.reset_mock()
        distributed_mock.assert_not_called()

        # static csv-prefix
        arguments = parser.parse_args([
            'run',
            '-e', f'{execution_context}/configuration.yaml',
            '--yes',
            f'{execution_context}/features/test.feature',
            '--csv-interval', '20',
            '--csv-prefix', 'test test',
        ])
        setattr(arguments, 'file', ' '.join(arguments.file))

        assert run(arguments, local_mock) == 0

        distributed_mock.assert_not_called()
        local_mock.assert_called_once_with(
            arguments,
            {
                'GRIZZLY_CLI_HOST': 'localhost',
                'GRIZZLY_EXECUTION_CONTEXT': str(execution_context),
                'GRIZZLY_MOUNT_CONTEXT': str(mount_context),
                'GRIZZLY_CONFIGURATION_FILE': CaseInsensitive(path.join(execution_context, 'configuration.lock.yaml')),
            }, {
                'master': [],
                'worker': [],
                'common': ['-Dcsv-prefix="test test"', '-Dcsv-interval=20'],
            }
        )
        local_mock.reset_mock()

        # dynamic csv-prefix
        datetime_mock = mocker.patch(
            'grizzly_cli.run.datetime',
            side_effect=lambda *args, **kwargs: datetime(*args, **kwargs)
        )
        datetime_mock.now.return_value = datetime(2022, 12, 6, 13, 1, 13)
        arguments = parser.parse_args([
            'run',
            '-e', f'{execution_context}/configuration.yaml',
            '--yes',
            f'{execution_context}/features/test.feature',
            '--csv-prefix',
            '--csv-interval', '20',
            '--csv-flush-interval', '60',
        ])
        setattr(arguments, 'file', ' '.join(arguments.file))

        assert run(arguments, distributed_mock) == 0

        local_mock.assert_not_called()
        distributed_mock.assert_called_once_with(
            arguments,
            {
                'GRIZZLY_CLI_HOST': 'localhost',
                'GRIZZLY_EXECUTION_CONTEXT': str(execution_context),
                'GRIZZLY_MOUNT_CONTEXT': str(mount_context),
                'GRIZZLY_CONFIGURATION_FILE': CaseInsensitive(path.join(execution_context, 'configuration.lock.yaml')),
            }, {
                'master': [],
                'worker': [],
                'common': ['-Dcsv-prefix="this_feature_is_testing_something_20221206T130113"', '-Dcsv-interval=20', '-Dcsv-flush-interval=60'],
            }
        )
        distributed_mock.reset_mock()

        setattr(arguments, 'csv_prefix', None)
        setattr(arguments, 'csv_flush_interval', None)

        # --log-dir
        arguments = parser.parse_args([
            'run',
            '-e', f'{execution_context}/configuration.yaml',
            '--yes',
            '--log-dir', 'foobar',
            f'{execution_context}/features/test.feature',
        ])
        setattr(arguments, 'file', ' '.join(arguments.file))

        assert run(arguments, distributed_mock) == 0

        local_mock.assert_not_called()
        distributed_mock.assert_called_once_with(
            arguments,
            {
                'GRIZZLY_CLI_HOST': 'localhost',
                'GRIZZLY_EXECUTION_CONTEXT': str(execution_context),
                'GRIZZLY_MOUNT_CONTEXT': str(mount_context),
                'GRIZZLY_CONFIGURATION_FILE': CaseInsensitive(path.join(execution_context, 'configuration.lock.yaml')),
                'GRIZZLY_LOG_DIR': 'foobar',
            }, {
                'master': [],
                'worker': [],
                'common': [],
            }
        )
        distributed_mock.reset_mock()

        capsys.readouterr()

        # --dry-run
        arguments = parser.parse_args([
            'run',
            '-e', f'{execution_context}/configuration.yaml',
            '--yes',
            '--log-dir', 'foobar',
            f'{execution_context}/features/test.feature',
            '--dry-run'
        ])
        setattr(arguments, 'file', ' '.join(arguments.file))

        assert run(arguments, distributed_mock) == 0

        local_mock.assert_not_called()
        distributed_mock.assert_called_once_with(
            arguments,
            {
                'GRIZZLY_CLI_HOST': 'localhost',
                'GRIZZLY_EXECUTION_CONTEXT': str(execution_context),
                'GRIZZLY_MOUNT_CONTEXT': str(mount_context),
                'GRIZZLY_CONFIGURATION_FILE': CaseInsensitive(path.join(execution_context, 'configuration.lock.yaml')),
                'GRIZZLY_LOG_DIR': 'foobar',
                'GRIZZLY_DRY_RUN': 'true',
            }, {
                'master': [],
                'worker': [],
                'common': [],
            }
        )
        distributed_mock.reset_mock()

        capsys.readouterr()

        # --dump
        arguments = parser.parse_args([
            'run',
            '-e', f'{execution_context}/configuration.yaml',
            '--yes',
            f'{execution_context}/features/test.feature',
            '--dump',
        ])
        setattr(arguments, 'file', ' '.join(arguments.file))

        assert run(arguments, distributed_mock) == 0

        distributed_mock.assert_not_called()
        local_mock.assert_not_called()

        capture = capsys.readouterr()

        assert capture.out == 'Feature: this feature is testing something\n'
        assert capture.err == ''
    finally:
        tmp_path_factory._basetemp = original_tmp_path
        rm_rf(test_context)


def test_run_dump(capsys: CaptureFixture, mocker: MockerFixture, tmp_path_factory: TempPathFactory) -> None:
    setup_logging()

    original_tmp_path = tmp_path_factory._basetemp
    tmp_path_factory._basetemp = Path.cwd() / '.pytest_tmp'
    test_context = tmp_path_factory.mktemp('test_context')
    execution_context = test_context / 'execution-context'
    execution_context.mkdir()
    mount_context = test_context / 'mount-context'
    mount_context.mkdir()
    feature_file = execution_context / 'features' / 'test.feature'
    feature_file.parent.mkdir(parents=True, exist_ok=True)
    feature_file.write_text('Feature: this feature is testing something')
    (execution_context / 'configuration.yaml').write_text('configuration:')

    parser = ArgumentParser()

    sub_parsers = parser.add_subparsers(dest='test')

    create_parser(sub_parsers, parent='local')

    try:
        mocker.patch('grizzly_cli.run.grizzly_cli.EXECUTION_CONTEXT', str(execution_context))
        mocker.patch('grizzly_cli.run.grizzly_cli.MOUNT_CONTEXT', str(mount_context))
        mocker.patch('grizzly_cli.run.get_hostname', return_value='localhost')
        mocker.patch('grizzly_cli.run.find_variable_names_in_questions', side_effect=[['foo', 'bar'], [], [], [], [], [], [], []])
        mocker.patch('grizzly_cli.run.find_metadata_notices', side_effect=[[], ['is the event log cleared?'], ['hello world', 'foo bar'], [], [], [], [], []])
        mocker.patch('grizzly_cli.run.distribution_of_users_per_scenario', autospec=True)
        distributed_mock = mocker.MagicMock(return_value=0)
        local_mock = mocker.MagicMock(return_value=0)

        setattr(getattr(run, '__wrapped__'), '__value__', str(execution_context))

        # --dump output.feature
        feature_file.write_text("""Feature: a feature
    Background: common
        Given a common step

    Scenario: first
        Given a variable with value "{{foo * 0.25 | int }}" and another value " {{ bar |int + 12}}"
        And a variable with value "{{ hello }}"
        And a variable with value "{{ thisshouldwork | upper }}"
        And a variable with value "{{thisshouldalsowork |bigtime}}"
        And a variable with value "{{andthis|too}}"

    Scenario: second
        {% scenario "second", feature="../second.feature" %}

    Scenario: third
        Given a variable with value "{{ some*0.25 | more}}" and another value "{{yes|box }}"

    Scenario: fourth
        {% scenario "fourth", feature="./fourth.feature", foo="bar" %}
""")
        feature_file_2 = execution_context / 'second.feature'
        feature_file_2.write_text("""Feature: a second feature
    Background: common
        Given a common step

    Scenario: second
        Given a variable with value "{{ foobar }}"
        Then run a bloody test
""")
        feature_file_3 = execution_context / 'features' / 'fourth.feature'
        feature_file_3.write_text("""Feature: a fourth feature
    Background: common
        Given a common step

    Scenario: fourth
        Given a variable with value "{{ {$ foo $}_barfoo }}"
        Then get "{{ bar{$ foo $}foo }}" from "{{ {$ foo $}_barfoo }}"
        Then run a bloody test
""")

        arguments = parser.parse_args([
            'run',
            '-e', f'{execution_context}/configuration.yaml',
            '--yes',
            f'{execution_context}/features/test.feature',
            '--dump', f'{execution_context}/output.feature'
        ])
        setattr(arguments, 'file', ' '.join(arguments.file))

        assert run(arguments, local_mock) == 0

        distributed_mock.assert_not_called()
        local_mock.assert_not_called()

        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == ''

        output_file = execution_context / 'output.feature'
        assert output_file.read_text() == """Feature: a feature
    Background: common
        Given a common step

    Scenario: first
        Given a variable with value "{{foo * 0.25 | int }}" and another value " {{ bar |int + 12}}"
        And a variable with value "{{ hello }}"
        And a variable with value "{{ thisshouldwork | upper }}"
        And a variable with value "{{thisshouldalsowork |bigtime}}"
        And a variable with value "{{andthis|too}}"

    Scenario: second
        Given a variable with value "{{ foobar }}"
        Then run a bloody test

    Scenario: third
        Given a variable with value "{{ some*0.25 | more}}" and another value "{{yes|box }}"

    Scenario: fourth
        Given a variable with value "{{ bar_barfoo }}"
        Then get "{{ barbarfoo }}" from "{{ bar_barfoo }}"
        Then run a bloody test
"""

        feature_file.write_text("""Feature: a feature
    Scenario: first
        Given a variable with value "{{ hello }}"

    Scenario: second
        {% scenario "second", feature="../second.feature", prefix="s1" %}

    # Scenario: third
    #     {% scenario "inactive-second", feature="./second.feature", prefix="s1" %}

    Scenario: third
        {% scenario "third", feature="../second.feature", prefix="s1" %}
""")
        feature_file_2 = execution_context / 'second.feature'
        feature_file_2.write_text("""Feature: a second feature
    Background: common
        Given a common step

    Scenario: second
        Given a variable with value "{{ {$ prefix $}foobar }}"
        Then run a bloody test
            \"\"\"
            with step text
            that spans
            more than
            one line
            \"\"\"

    Scenario: third
        Given a variable with value "{{ {$ prefix $}value }}"
        Then run a bloody test, with table
          | hello | world |
          | foo   | bar   |
          | bar   |       |
          |       | foo   |
""")

        output_file.unlink(missing_ok=True)

        arguments = parser.parse_args([
            'run',
            '-e', f'{execution_context}/configuration.yaml',
            '--yes',
            f'{execution_context}/features/test.feature',
            '--dump', f'{execution_context}/output.feature'
        ])
        setattr(arguments, 'file', ' '.join(arguments.file))

        assert run(arguments, local_mock) == 0

        distributed_mock.assert_not_called()
        local_mock.assert_not_called()

        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == ''

        output_file = execution_context / 'output.feature'
        assert output_file.read_text() == """Feature: a feature
    Scenario: first
        Given a variable with value "{{ hello }}"

    Scenario: second
        Given a variable with value "{{ s1foobar }}"
        Then run a bloody test
            \"\"\"
            with step text
            that spans
            more than
            one line
            \"\"\"

    # Scenario: third
    #     {% scenario "inactive-second", feature="./second.feature", prefix="s1" %}

    Scenario: third
        Given a variable with value "{{ s1value }}"
        Then run a bloody test, with table
          | hello | world |
          | foo   | bar   |
          | bar   |       |
          |       | foo   |
"""
        assert feature_file.read_text() == """Feature: a feature
    Scenario: first
        Given a variable with value "{{ hello }}"

    Scenario: second
        {% scenario "second", feature="../second.feature", prefix="s1" %}

    # Scenario: third
    #     {% scenario "inactive-second", feature="./second.feature", prefix="s1" %}

    Scenario: third
        {% scenario "third", feature="../second.feature", prefix="s1" %}
"""

        feature_file.write_text("""Feature: a feature
    Scenario: first
        Given a variable with value "{{ hello }}"

    Scenario: second
        {% scenario "second", feature="../second.feature", foo="bar" %}
""")
        feature_file_2 = execution_context / 'second.feature'
        feature_file_2.write_text("""Feature: a second feature
    Background: common
        Given a common step

    Scenario: second
        Given a variable with value "{{ {$ bar $}foobar }}"
        Then run a bloody test
            \"\"\"
            with step text
            that spans
            more than
            one line
            \"\"\"
""")

        output_file.unlink(missing_ok=True)

        arguments = parser.parse_args([
            'run',
            '-e', f'{execution_context}/configuration.yaml',
            '--yes',
            f'{execution_context}/features/test.feature',
            '--dump', f'{execution_context}/output.feature'
        ])
        setattr(arguments, 'file', ' '.join(arguments.file))

        with pytest.raises(ValueError) as ve:
            run(arguments, local_mock)

        assert str(ve.value) == '''the following variables has been declared in scenario tag but not used in ../second.feature#second:
  foo

the following variables was used in ../second.feature#second but was not declared in scenario tag:
  bar
'''

        distributed_mock.assert_not_called()
        local_mock.assert_not_called()

        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == ''

        feature_file.write_text("""Feature: a feature
    Scenario: first
        Given a variable with value "{{ hello }}"

    Scenario: second
        {% scenario "second", feature="../second.feature", foo="bar" %}
""")
        feature_file_2 = execution_context / 'second.feature'
        feature_file_2.write_text("""Feature: a second feature
    Background: common
        Given a common step

    Scenario: second
        Given a variable with value "{{ {$ foo $}foobar }}"
        {% scenario "fourth", feature="./features/fourth.feature", foo="{$ foo $}", bar="foo", condition=True %}

        Then run a bloody test
            \"\"\"
            with step text
            that spans
            more than
            one line
            \"\"\"
""")

        feature_file_3.write_text("""Feature: a fourth feature
    Background: common
        Given a common step

    Scenario: fourth
        Then could it be "{$ foo $}" and "{$ bar $}"

        # <!-- this step is conditional -->
        {%- if {$ condition $} %}
        Then alert me!
        {%- endif %}
""")

        output_file.unlink(missing_ok=True)

        arguments = parser.parse_args([
            'run',
            '-e', f'{execution_context}/configuration.yaml',
            '--yes',
            f'{execution_context}/features/test.feature',
            '--dump', f'{execution_context}/output.feature'
        ])
        setattr(arguments, 'file', ' '.join(arguments.file))

        assert run(arguments, local_mock) == 0

        distributed_mock.assert_not_called()
        local_mock.assert_not_called()

        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == ''
        assert output_file.read_text() == """Feature: a feature
    Scenario: first
        Given a variable with value "{{ hello }}"

    Scenario: second
        Given a variable with value "{{ barfoobar }}"
        Then could it be "bar" and "foo"

        # <!-- this step is conditional -->
        Then alert me!

        Then run a bloody test
            \"\"\"
            with step text
            that spans
            more than
            one line
            \"\"\"
"""

        feature_file_2.write_text("""Feature: a second feature
    Background: common
        Given a common step

    Scenario: second
        Given a variable with value "{{ {$ foo $}foobar }}"
        {% scenario "fourth", feature="./features/fourth.feature", foo="{$ foo $}", bar="foo", condition=False %}

        Then run a bloody test
            \"\"\"
            with step text
            that spans
            more than
            one line
            \"\"\"
""")

        output_file.unlink(missing_ok=True)

        arguments = parser.parse_args([
            'run',
            '-e', f'{execution_context}/configuration.yaml',
            '--yes',
            f'{execution_context}/features/test.feature',
            '--dump', f'{execution_context}/output.feature'
        ])
        setattr(arguments, 'file', ' '.join(arguments.file))

        assert run(arguments, local_mock) == 0

        distributed_mock.assert_not_called()
        local_mock.assert_not_called()

        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == ''
        assert output_file.read_text() == """Feature: a feature
    Scenario: first
        Given a variable with value "{{ hello }}"

    Scenario: second
        Given a variable with value "{{ barfoobar }}"
        Then could it be "bar" and "foo"

        # <!-- this step is conditional -->

        Then run a bloody test
            \"\"\"
            with step text
            that spans
            more than
            one line
            \"\"\"
"""

        feature_file_3.write_text("""Feature: a fourth feature
    Background: common
        Given a common step

    Scenario: fourth
        Then could it be "{$ foo $}" and "{$ bar $}"
        \"\"\"
        hello world
        \"\"\"

        # <!-- this step is conditional -->
        {%- if {$ condition $} %}
        Then alert me!
        {%- endif %}

    Scenario: fifth
        Given a scenario after the included scenario
""")

        output_file.unlink(missing_ok=True)

        assert run(arguments, distributed_mock) == 0

        distributed_mock.assert_not_called()
        local_mock.assert_not_called()

        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == ''
        assert output_file.read_text() == """Feature: a feature
    Scenario: first
        Given a variable with value "{{ hello }}"

    Scenario: second
        Given a variable with value "{{ barfoobar }}"
        Then could it be "bar" and "foo"
        \"\"\"
        hello world
        \"\"\"

        # <!-- this step is conditional -->

        Then run a bloody test
            \"\"\"
            with step text
            that spans
            more than
            one line
            \"\"\"
"""
    finally:
        tmp_path_factory._basetemp = original_tmp_path
        rm_rf(test_context)


def test_if_condition_with_scenario_tag_ext(caplog: LogCaptureFixture) -> None:
    environment = Environment(autoescape=False, extensions=[ScenarioTag])

    template = environment.from_string("{% if False %}hello {{ name }}!{% endif %}")
    with caplog.at_level(logging.DEBUG):
        assert template.render() == ''

    template = environment.from_string("{% if True %}hello {{ name }}!{% endif %}")
    assert template.render() == 'hello {{ name }}!'

    template = environment.from_string("""foobar

{%- if True %}
hello {{ name }}!
{%- endif %}
world""")
    assert template.render() == 'foobar\nhello {{ name }}!\nworld'

    template = environment.from_string("""Feature: a fourth feature
    Background: common
        Given a common step

    Scenario: fourth
        Then could it be "{$ foo $}" and "{$ bar $}"

        # <!-- this step is conditional -->
        {%- if True %}
        Then show me the "{{ money }}"
        {%- endif %}""")

    assert template.render() == """Feature: a fourth feature
    Background: common
        Given a common step

    Scenario: fourth
        Then could it be "{$ foo $}" and "{$ bar $}"

        # <!-- this step is conditional -->
        Then show me the "{{ money }}"
        """.rstrip()

    template = environment.from_string("""Feature: a fourth feature
    Background: common
        Given a common step

    Scenario: fourth
        Then could it be "{$ foo $}" and "{$ bar $}"

        # <!-- this step is conditional -->
        {%- if False %}
        Then show me the "{{ money }}"
        {%- endif %}""")

    assert template.render() == """Feature: a fourth feature
    Background: common
        Given a common step

    Scenario: fourth
        Then could it be "{$ foo $}" and "{$ bar $}"

        # <!-- this step is conditional -->"""


class TestScenarioTag:
    def test_get_scenario_text(self, tmp_path_factory: TempPathFactory) -> None:
        original_tmp_path = tmp_path_factory._basetemp
        tmp_path_factory._basetemp = Path.cwd() / '.pytest_tmp'
        test_context = tmp_path_factory.mktemp('context')
        test_feature = test_context / 'test.feature'

        try:
            test_feature.write_text("""Feature: test
    Background: common
        Then some steps here
        And other useful stuff

    Scenario: first
        \"\"\"
        this is just some comments
        for the scenario, that spans
        multiple lines.
        \"\"\"
        Given the first scenario
        And it's steps

    Scenario: second
        Given the second scenario

        # <!-- comment -->
        And it's steps
        \"\"\"
        step text
        \"\"\"

    Scenario: third
        \"\"\"
        this is just some comments
        for the scenario, that spans
        multiple lines.
        \"\"\"
        Given the third scenario
        And it's steps
        | foo | bar |
        | bar | foo |

        And one more step
""")

            assert ScenarioTag.get_scenario_text('first', test_feature) == """Given the first scenario
        And it's steps"""

            assert ScenarioTag.get_scenario_text('second', test_feature) == """Given the second scenario

        # <!-- comment -->
        And it's steps
        \"\"\"
        step text
        \"\"\""""

            assert ScenarioTag.get_scenario_text('third', test_feature) == """Given the third scenario
        And it's steps
        | foo | bar |
        | bar | foo |

        And one more step"""
        finally:
            tmp_path_factory._basetemp = original_tmp_path
            rm_rf(test_context)


def test_load_configuration(mocker: MockerFixture, tmp_path_factory: TempPathFactory) -> None:
    test_context = tmp_path_factory.mktemp('test_context')

    load_configuration_keyvault_mock = mocker.patch('grizzly_cli.run.load_configuration_keyvault', return_value={})

    try:
        env_file_local = test_context / 'local.yaml'

        env_file_local.write_text('''configuration:
    authentication:
        admin:
            username: administrator
            password: hunter
''')

        env_file_lock_name = load_configuration(env_file_local.as_posix())
        assert env_file_lock_name == f'{test_context.as_posix()}/local.lock.yaml'

        env_file_lock = Path(env_file_lock_name)

        assert env_file_lock.read_text() == env_file_local.read_text()
        load_configuration_keyvault_mock.assert_not_called()

        with cwd(test_context):
            env_file_lock_name = load_configuration('local.yaml')
            assert env_file_lock_name == 'local.lock.yaml'

            env_file_lock = Path(env_file_lock_name)
            assert env_file_lock.read_text() == env_file_local.read_text()
            load_configuration_keyvault_mock.assert_not_called()

        env_file_local.write_text('''configuration:
    keyvault: https://grizzly.keyvault.azure.com
    authentication:
        admin:
            username: administrator
            password: hunter
''')

        env_file_lock_name = load_configuration(env_file_local.as_posix())
        assert env_file_lock_name == f'{test_context.as_posix()}/local.lock.yaml'

        env_file_lock = Path(env_file_lock_name)

        assert env_file_lock.read_text() == env_file_local.read_text()
        load_configuration_keyvault_mock.assert_called_once_with(url='https://grizzly.keyvault.azure.com', environment='local')
        load_configuration_keyvault_mock.reset_mock()

        env_file_local.write_text('''configuration:
    env: test
    keyvault: https://grizzly.keyvault.azure.com
    authentication:
        admin:
            username: administrator
            password: hunter
''')

        env_file_lock_name = load_configuration(env_file_local.as_posix())
        assert env_file_lock_name == f'{test_context.as_posix()}/local.lock.yaml'

        env_file_lock = Path(env_file_lock_name)

        assert env_file_lock.read_text() == env_file_local.read_text()
        load_configuration_keyvault_mock.assert_called_once_with(url='https://grizzly.keyvault.azure.com', environment='test')
        load_configuration_keyvault_mock.reset_mock()
    finally:
        rm_rf(test_context)


def test_load_configuration_file(tmp_path_factory: TempPathFactory) -> None:
    test_context = tmp_path_factory.mktemp('test_context')

    try:
        env_file_base = test_context / 'base.yaml'

        env_file_base.write_text('''configuration:
    authentication:
        admin:
            username: administrator
            password: hunter
''')

        assert load_configuration_file(env_file_base) == {
            'configuration': {
                'authentication': {
                    'admin': {
                        'username': 'administrator',
                        'password': 'hunter',
                    },
                },
            },
        }

        env_file_local = test_context / 'local.yaml'
        env_file_local.write_text('''{% merge "./base.yaml" %}
configuration:
    authentication:
        admin:
            username: root
            password: null
    logging:
        level: DEBUG
        max_size: 10000
''')
        assert load_configuration_file(env_file_local) == {
            'configuration': {
                'authentication': {
                    'admin': {
                        'username': 'administrator',
                        'password': 'hunter',
                    },
                },
                'logging': {
                    'level': 'DEBUG',
                    'max_size': 10000,
                },
            },
        }

    finally:
        rm_rf(test_context)


def create_secret_property(name: str) -> SecretProperties:
    return SecretProperties(vault_id=f'https://grizzly.keyvault.com/foo/{name}')


def create_secret(name: str, value: str) -> KeyVaultSecret:
    return KeyVaultSecret(create_secret_property(name), value)


def mock_keyvault(client: MagicMock, keyvault: dict[str, str]) -> None:
    secret_properties: list[SecretProperties] = []
    secrets: list[KeyVaultSecret] = []

    for key, value in keyvault.items():
        secret = create_secret(key, value)
        secret_properties.append(secret.properties)
        if key.startswith('grizzly--'):
            secrets.append(secret)

    client.reset_mock()
    client.list_properties_of_secrets.return_value = secret_properties
    client.get_secret.side_effect = secrets


def test_load_configuration_keyvault(mocker: MockerFixture, capsys: CaptureFixture) -> None:
    setup_logging()

    secret_client_mock = mocker.patch('grizzly_cli.run.SecretClient', new_callable=mocker.MagicMock, spec=SecretClient)
    client_mock = secret_client_mock.return_value

    # <!-- no matching secrets
    client_mock.list_properties_of_secrets.return_value = [create_secret_property('grizzly--none--foo-bar')]

    assert load_configuration_keyvault(url='https://grizzly.keyvault.com', environment='local') == {'configuration': {}}

    secret_client_mock.assert_called_once_with(vault_url='https://grizzly.keyvault.com', credential=ANY(ChainedTokenCredential))
    client_mock.list_properties_of_secrets.assert_called_once_with()
    client_mock.get_secret.assert_not_called()
    secret_client_mock.reset_mock()
    # // -->

    # <!-- one global, one environment specific
    mock_keyvault(client_mock, {
        'some--random--key': 'rando',
        'grizzly--global--foo-bar': 'foobar',
        'grizzly--local--bar-foo-bar-foo': 'barfoo',
        'grizzly--remote--bar-foo-bar-foo': 'foobar',
    })
    keyvault_configuration = load_configuration_keyvault(url='https://grizzly.keyvault.com', environment='local')
    assert keyvault_configuration == {'configuration': {
        'foo': {
            'bar': 'foobar',
        },
        'bar': {
            'foo': {
                'bar': {
                    'foo': 'barfoo',
                },
            },
        },
    }}
    # // -->

    secret_client_mock.reset_mock()
    capsys.readouterr()

    # <!-- ClientAuthenticationError
    client_mock.list_properties_of_secrets.side_effect = [ClientAuthenticationError]

    with pytest.raises(SystemExit):
        load_configuration_keyvault(url='https://grizzly.keyvault.com', environment='local')

    capture = capsys.readouterr()
    assert capture.err == 'authentication failed, run `az login [--identity]` first.\n'
    # // -->

    # <!-- ServiceRequestError
    client_mock.list_properties_of_secrets.side_effect = [ServiceRequestError(message='error')]

    with pytest.raises(SystemExit):
        load_configuration_keyvault(url='https://grizzly.keyvault.com', environment='local')

    capture = capsys.readouterr()
    assert capture.err == 'https://grizzly.keyvault.com does not resolve to an azure keyvault\n'
    # // -->


@pytest.mark.skip(reason='needs real credentials and keyvault')
def test_load_configuration_keyvault_real() -> None:
    """
    <keyvault> needs to contain the following secrets:
    grizzly--global--test-env-var = foobar
    grizzly--local--foo-bar = foobaz

    before running, get AzureCliCredential by running `az login`.
    """
    assert load_configuration_keyvault(url='https://<keyvault>.vault.azure.net/', environment='local') == {
        'configuration': {
            'test': {
                'env': {
                    'var': 'foobar',
                },
            },
            'foo': {
                'bar': 'foobaz',
            }
        }
    }


@pytest.mark.skip(reason='needs real credentials and keyvault')
def test_load_configuration_real(tmp_path_factory: TempPathFactory) -> None:
    """
    <keyvault> needs to contain the following secrets:
    grizzly--global--test-env-var = foobar
    grizzly--local--foo-bar = foobaz

    before running, get AzureCliCredential by running `az login`.
    """
    test_context = tmp_path_factory.mktemp('test_context')

    try:
        env_file_local = test_context / 'local.yaml'
        env_file_local.write_text('''configuration:
    env: <environment>
    keyvault: https://<vault>.vault.azure.net
    authentication:
        admin:
            username: administrator
            password: hunter
    test:
        env:
            var: local
''')

        env_file_lock_name = load_configuration(env_file_local.as_posix())
        assert env_file_lock_name == f'{test_context.as_posix()}/local.lock.yaml'

        env_file_lock = Path(env_file_lock_name)

        assert env_file_lock.read_text() == '''configuration:
    foo:
        bar: foobaz
    test:
        env:
            var: local
    env: tau
    authentication:
        admin:
            username: administrator
            password: hunter
'''
    finally:
        rm_rf(test_context)
