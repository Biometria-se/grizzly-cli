from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from base64 import b64encode

import pytest
from _pytest.tmpdir import TempPathFactory
from pytest_mock import MockerFixture
from azure.core.exceptions import ClientAuthenticationError, ServiceRequestError
from azure.identity import ChainedTokenCredential
from azure.keyvault.secrets import SecretClient, SecretProperties, KeyVaultSecret

from grizzly_cli.utils import setup_logging, chunker
from grizzly_cli.utils.configuration import (
    ScenarioTag,
    load_configuration_file,
    load_configuration,
    load_configuration_keyvault,
    get_keyvault_client,
    _get_metadata,
    _write_file,
    _import_files,
)

from tests.helpers import rm_rf, cwd, ANY


def create_secret_property(name: str, content_type: str | None = None) -> SecretProperties:
    return SecretProperties(vault_id=f'https://grizzly.keyvault.com/foo/{name}', content_type=content_type)


def create_secret(name: str, value: str | None, content_type: str | None = None) -> KeyVaultSecret:
    return KeyVaultSecret(create_secret_property(name, content_type), value)


def mock_keyvault(client: MagicMock, keyvault: dict[str, tuple[str | None, str | None]]) -> None:
    secret_properties: list[SecretProperties] = []
    secrets: list[KeyVaultSecret] = []

    for key, (value, content_type) in keyvault.items():
        secret = create_secret(key, value, content_type)
        secret_properties.append(secret.properties)
        if key.startswith('grizzly--'):
            secrets.append(secret)

    client.reset_mock()
    client.list_properties_of_secrets.return_value = secret_properties
    client.get_secret.side_effect = secrets


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


def test_get_keyvault_client(mocker: MockerFixture) -> None:
    secrets_client_mock = mocker.patch('grizzly_cli.utils.configuration.SecretClient', return_value=MagicMock(spec=SecretClient))

    assert get_keyvault_client('https://grizzly.keyvault.azure.com') == secrets_client_mock.return_value

    secrets_client_mock.assert_called_once_with(vault_url='https://grizzly.keyvault.azure.com', credential=ANY(ChainedTokenCredential))
    secrets_client_mock.reset_mock()


def test__get_metadata() -> None:
    assert _get_metadata('hello', 'file') is None
    assert _get_metadata('file:foo.bar.txt', 'file') == 'foo.bar.txt'
    assert _get_metadata('foobar,file:test.txt,noconf', 'file') == 'test.txt'


def test__write_file(tmp_path_factory: TempPathFactory) -> None:
    test_context = tmp_path_factory.mktemp('test_context')

    try:
        assert _write_file(test_context, 'file:foo/bar.txt', b64encode(b'foo bar').decode('utf-8')) == 'files/foo/bar.txt'
        assert (test_context / 'files' / 'foo' / 'bar.txt').read_text() == 'foo bar'

        f = test_context / 'files' / 'foobar.txt'
        f.touch()

        chunks = chunker(b64encode(b'foobarfoobarfoobar').decode('utf-8'), 8)
        number_of_chunks = len(chunks)
        processed_chunks: list[str] = []

        for index, chunk in enumerate(chunks):
            content_type = f'file:foobar.txt,chunk:{index},chunks:{number_of_chunks}'
            processed_chunks.append(chunk)

            assert _write_file(test_context, content_type, chunk) == 'files/foobar.txt'
            f = test_context / 'files' / 'foobar.txt'
            if index < number_of_chunks - 1:
                expected = ''.join(processed_chunks)
            else:
                expected = 'foobarfoobarfoobar'

            assert f.read_text() == expected

        with pytest.raises(ValueError, match='could not find `file:` in content type'):
            _write_file(test_context, 'noconf,chunk:0,chunks:2', 'foobar')
    finally:
        rm_rf(test_context)


def test__import_files(mocker: MockerFixture, tmp_path_factory: TempPathFactory) -> None:
    test_context = tmp_path_factory.mktemp('test_context')

    client_mock = mocker.MagicMock(spec=SecretClient)
    client_mock._vault_url = 'https://grizzly.keyvault.com'

    secret = create_secret('grizzly--local--foo-bar', None)

    with pytest.raises(ValueError, match='secret grizzly--local--foo-bar has no value'):
        _import_files(client_mock, test_context, secret)

    secret = create_secret('grizzly--local--foo-bar', 'grizzly--local--bar-foo')
    mock_keyvault(client_mock, {
        'grizzly--local-bar-foo': ('barfoo', None),
    })

    with pytest.raises(ValueError, match='secret grizzly--local--bar-foo has no content type'):
        _import_files(client_mock, test_context, secret)

    secret = create_secret('grizzly--local--foo-bar', 'grizzly--local--bar-foo')
    mock_keyvault(client_mock, {
        'grizzly--local--bar-foo': (None, 'file:foobar.txt,chunk:0,chunks:2'),
    })

    with pytest.raises(ValueError, match='secret grizzly--local--bar-foo has no value'):
        _import_files(client_mock, test_context, secret)

    secret = create_secret('grizzly--local--foo-bar', 'grizzly--local--bar-foo')
    mock_keyvault(client_mock, {
        'grizzly--local--bar-foo': (b64encode(b'foobar').decode('utf-8'), 'file:foobar.txt'),
    })

    f = test_context / 'files' / 'foobar.txt'

    assert _import_files(client_mock, test_context, secret) == 'files/foobar.txt'
    assert f.read_text() == 'foobar'

    secret = create_secret('grizzly--local--foo-bar', 'grizzly--local--bar-foo')
    mock_keyvault(client_mock, {
        'grizzly--local--bar-foo': ('grizzly--local--foo-baz,grizzly--local--baz-foo', 'files'),
        'grizzly--local--foo-baz': (b64encode(b'foo baz').decode('utf-8'), 'file:foo/baz.txt,noconf'),
        'grizzly--local--baz-foo': (b64encode(b'baz foo').decode('utf-8'), 'file:baz/foo.txt,noconf'),
    })

    assert _import_files(client_mock, test_context, secret) == 'files/baz/foo.txt'

    f = test_context / 'files' / 'foo' / 'baz.txt'
    assert f.read_text() == 'foo baz'

    f = test_context / 'files' / 'baz' / 'foo.txt'
    assert f.read_text() == 'baz foo'


def test_load_configuration(mocker: MockerFixture, tmp_path_factory: TempPathFactory) -> None:
    test_context = tmp_path_factory.mktemp('test_context')

    load_configuration_keyvault_mock = mocker.patch('grizzly_cli.utils.configuration.load_configuration_keyvault', return_value={})
    context_root = test_context.parent

    mocker.patch('grizzly_cli.utils.configuration.get_context_root', return_value=context_root)

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
        load_configuration_keyvault_mock.assert_called_once_with(ANY(SecretClient), 'local', context_root)
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
        load_configuration_keyvault_mock.assert_called_once_with(ANY(SecretClient), 'test', context_root)
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


def test_load_configuration_keyvault(mocker: MockerFixture, tmp_path_factory: TempPathFactory) -> None:
    setup_logging()

    context_root = tmp_path_factory.mktemp('test_context')

    client_mock = mocker.MagicMock(spec=SecretClient)
    client_mock._vault_url = 'https://grizzly.keyvault.com'

    # <!-- no matching secrets
    client_mock.list_properties_of_secrets.return_value = [create_secret_property('grizzly--none--foo-bar')]

    assert load_configuration_keyvault(client_mock, 'local', context_root) == ({}, 0)

    client_mock.list_properties_of_secrets.assert_called_once_with()
    client_mock.get_secret.assert_not_called()
    # // -->

    # <!-- one global, one environment specific
    mock_keyvault(client_mock, {
        'some--random--key': ('rando', None),
        'grizzly--global--foo-bar': ('foobar', None),
        'grizzly--local--bar-foo-bar-foo': ('barfoo', None),
        'grizzly--remote--bar-foo-bar-foo': ('foobar', None),
    })
    keyvault_configuration, imported_from_keyvault = load_configuration_keyvault(client_mock, 'local', context_root)
    assert keyvault_configuration == {
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
    }
    assert imported_from_keyvault == 2
    # // -->

    # <!-- ClientAuthenticationError
    client_mock.list_properties_of_secrets.side_effect = [ClientAuthenticationError]

    with pytest.raises(ClientAuthenticationError):
        load_configuration_keyvault(client_mock, 'local', context_root)
    # // -->

    # <!-- ServiceRequestError
    client_mock.list_properties_of_secrets.side_effect = [ServiceRequestError(message='error')]

    with pytest.raises(ServiceRequestError):
        load_configuration_keyvault(client_mock, 'local', context_root)
    # // -->
