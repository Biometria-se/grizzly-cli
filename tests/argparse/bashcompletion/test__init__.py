import argparse
import inspect

from typing import Optional, Generator
from os import path, chdir, getcwd
from shutil import rmtree

import pytest

from pytest_mock import MockerFixture
from _pytest.capture import CaptureFixture, CaptureResult
from _pytest.tmpdir import TempPathFactory

from grizzly_cli.argparse.bashcompletion import BashCompleteAction, BashCompletionAction, hook
from grizzly_cli.argparse import ArgumentParser
from grizzly_cli.__main__ import _create_parser

from ...helpers import onerror


CWD = getcwd()


@pytest.fixture
def test_parser() -> ArgumentParser:
    parser = ArgumentParser(prog='test-prog')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--file', action='append', type=str, required=True)
    parser.add_argument('test', nargs=1, type=str)
    parser.add_argument('--value', type=int)

    subparsers = parser.add_subparsers(dest='subparser')
    subparsers.add_parser('aparser')
    subparsers.add_parser('bparser')

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--test', action='store_true')
    group.add_argument('--foo', action='store_true')
    group.add_argument('--bar', action='store_true')

    return parser


@pytest.fixture
def test_file_structure(tmp_path_factory: TempPathFactory) -> Generator[str, None, None]:
    test_context = tmp_path_factory.mktemp('test_context')
    file = test_context / 'test.txt'
    file.touch()
    file.write_text('test.txt file')

    file = test_context / 'test.json'
    file.touch()
    file.write_text('{"value": "test.json file"}')

    file = test_context / 'test.xml'
    file.touch()
    file.write_text('<value>test.xml file</value>')

    file = test_context / 'test.yaml'
    file.touch()
    file.write_text('test:')

    file = test_context / 'test.feature'
    file.touch()
    file.write_text('Feature:')

    test_dir = test_context / 'test-dir'
    test_dir.mkdir()
    file = test_dir / 'test.yaml'
    file.touch()
    file.write_text('test:')

    file = test_dir / 'test.feature'
    file.touch()
    file.write_text('Feature:')

    hidden_dir = test_context / '.hidden'
    hidden_dir.mkdir()
    file = hidden_dir / 'hidden.txt'
    file.touch()
    file.write_text('hidden.txt file')

    chdir(test_context)
    try:
        yield str(test_context)
    finally:
        chdir(CWD)
        rmtree(test_context, onerror=onerror)


class TestBashCompletionAction:
    def test___init__(self) -> None:
        action = BashCompletionAction(['--bash-completion'])

        assert isinstance(action, argparse.Action)
        assert action.dest == argparse.SUPPRESS
        assert action.default == argparse.SUPPRESS
        assert action.nargs == 0
        assert action.help == argparse.SUPPRESS

    def test___call__(self, capsys: CaptureFixture) -> None:
        parser = argparse.ArgumentParser(prog='test-prog')
        action = BashCompletionAction(['--bash-completion'])

        with pytest.raises(SystemExit) as e:
            action(parser, parser.parse_args([]), None)
        assert e.type == SystemExit
        assert e.value.code == 0

        bash_script_path = path.join(path.dirname(inspect.getfile(action.__class__)), 'bashcompletion.bash')

        with open(bash_script_path, encoding='utf-8') as fd:
            bash_script = fd.read().replace('bashcompletion_template', parser.prog) + '\n'

        capture = capsys.readouterr()
        assert capture.err == ''
        assert capture.out == bash_script


class TestBashCompleteAction:
    def test___init__(self) -> None:
        action = BashCompleteAction(['--bash-complete'])

        assert isinstance(action, argparse.Action)
        assert action.dest == argparse.SUPPRESS
        assert action.default == argparse.SUPPRESS
        assert action.nargs is None
        assert action.help == argparse.SUPPRESS

    def test_get_suggestions(self) -> None:
        parser = ArgumentParser(prog='test-prog')
        action = BashCompleteAction(['--bash-complete'])

        suggestions = action.get_suggestions(parser)
        assert list(suggestions.keys()) == ['-h', '--help']
        assert isinstance(suggestions.get('--help', None), argparse.Action)

        parser.add_argument('--verbose', action='store_true')
        parser.add_argument('--file', type=str, required=True)
        parser.add_argument('test', nargs=1, type=str)

        subparsers = parser.add_subparsers(dest='subparser')

        subparsers.add_parser('a')
        subparsers.add_parser('b')

        suggestions = action.get_suggestions(parser)
        assert list(suggestions.keys()) == ['-h', '--help', '--verbose', '--file', 'test', 'a', 'b']
        assert isinstance(suggestions.get('--verbose', None), argparse._StoreTrueAction)
        assert isinstance(suggestions.get('--file', None), argparse._StoreAction)
        assert isinstance(suggestions.get('test', None), argparse._StoreAction)
        assert isinstance(suggestions.get('a', None), argparse._SubParsersAction)
        assert isinstance(suggestions.get('b', None), argparse._SubParsersAction)

    def test_get_exclusive_suggestions(self, test_parser: ArgumentParser) -> None:
        parser = ArgumentParser(prog='test-prog')
        action = BashCompleteAction(['--bash-complete'])

        assert action.get_exclusive_suggestions(parser) == {}

        assert action.get_exclusive_suggestions(test_parser) == {
            '--test': ['--foo', '--bar'],
            '--foo': ['--test', '--bar'],
            '--bar': ['--test', '--foo'],
        }

    def test_get_provided_options(self) -> None:
        action = BashCompleteAction(['--bash-complete'])

        assert action.get_provided_options('test-prog', None) == []
        assert action.get_provided_options('test-prog', []) == []
        assert action.get_provided_options('test-prog', '') == []
        assert action.get_provided_options('test-prog', 'test-prog') == []
        assert action.get_provided_options('test-prog', 'test-prog --foo hello --bar') == ['--foo', 'hello', '--bar']
        assert action.get_provided_options('test-prog', ['test-prog', '--foo', 'hello', '--bar']) == ['--foo', 'hello', '--bar']

    def test_remove_completed(self, test_parser: ArgumentParser) -> None:
        action = BashCompleteAction(['--bash-complete'])

        suggestions = action.get_suggestions(test_parser)
        all_suggestions = suggestions.copy()
        all_options_sorted = sorted(list(all_suggestions.keys()))
        exclusive_suggestions = action.get_exclusive_suggestions(test_parser)

        assert action.remove_completed([], suggestions, exclusive_suggestions) == []
        assert sorted(list(suggestions.keys())) == all_options_sorted
        assert action.remove_completed(['--verbose'], suggestions, exclusive_suggestions) == ['--verbose']
        assert sorted(list(suggestions.keys())) == all_options_sorted

        assert action.remove_completed(['--verbose', '--file'], suggestions, exclusive_suggestions) == ['--file']
        assert sorted(list(suggestions.keys()) + ['--verbose']) == all_options_sorted

        assert action.remove_completed(['--verbose', '--file', 'test.txt'], suggestions, exclusive_suggestions) == []
        assert sorted(list(suggestions.keys()) + ['--verbose']) == all_options_sorted

        assert action.remove_completed(['--verbose', '--file', 'test.txt', 'a'], suggestions, exclusive_suggestions) == ['a']
        assert sorted(list(suggestions.keys()) + ['--verbose']) == all_options_sorted

        # if subparsers are completed, then we move to another parser, with its own arguments

        assert action.remove_completed(['--verbose', '--file', 'test.txt', '--value'], suggestions, exclusive_suggestions) == ['--value']
        assert sorted(list(suggestions.keys()) + ['--verbose']) == all_options_sorted

        assert action.remove_completed(['--verbose', '--file', 'test.txt', '--value', '8'], suggestions, exclusive_suggestions) == ['--value', '8']
        assert sorted(list(suggestions.keys()) + ['--verbose']) == all_options_sorted

        # only one of --foo, --bar, --test is valid (mutually exclusive), so all should be removed from suggestions if one of them is specified
        assert action.remove_completed(['--verbose', '--file', 'test.txt', '--value', '8', '--foo'], suggestions, exclusive_suggestions) == []
        assert sorted(list(suggestions.keys()) + ['--verbose', '--value', '--foo', '--bar', '--test']) == all_options_sorted

    def test_filter_suggestions(self, test_parser: ArgumentParser) -> None:
        action = BashCompleteAction(['--bash-complete'])

        suggestions = action.get_suggestions(test_parser)
        all_suggestions = suggestions.copy()

        assert action.filter_suggestions([], suggestions) == all_suggestions
        assert sorted(list(action.filter_suggestions(['--'], suggestions).keys())) == sorted(['--help', '--test', '--foo', '--bar', '--value', '--verbose', '--file'])
        assert sorted(list(action.filter_suggestions(['--v'], suggestions).keys())) == sorted(['--verbose', '--value'])
        assert sorted(list(action.filter_suggestions(['--f'], suggestions).keys())) == sorted(['--file', '--foo'])

    @pytest.mark.parametrize(
        'input,expected',
        [
            ('grizzly-cli ', '-h --help --version init local dist',),
            ('grizzly-cli -', '-h --help --version'),
            ('grizzly-cli --', '--help --version'),
            ('grizzly-cli lo', 'local'),
            ('grizzly-cli -h', ''),
        ]
    )
    def test___call__(self, input: str, expected: str, capsys: CaptureFixture) -> None:
        parser = _create_parser()

        with pytest.raises(SystemExit):
            parser.parse_args([f'--bash-complete={input}'])
        capture = capsys.readouterr()
        assert capture.out == f'{expected}\n'

    @pytest.mark.parametrize(
        'input,expected', [
            ('grizzly-cli local run ', '-h --help --verbose -T --testdata-variable -y --yes -e --environment-file test.feature test-dir'),
            ('grizzly-cli local run -', '-h --help --verbose -T --testdata-variable -y --yes -e --environment-file'),
            ('grizzly-cli local run --', '--help --verbose --testdata-variable --yes --environment-file'),
            ('grizzly-cli local run --yes', '-h --help --verbose -T --testdata-variable -e --environment-file'),
            ('grizzly-cli local run --help --yes', ''),
            ('grizzly-cli local run --yes -T', ''),
            ('grizzly-cli local run --yes -T key=value', '-h --help --verbose -T --testdata-variable -e --environment-file test.feature test-dir'),
            ('grizzly-cli local run --yes -T key=value --env', '--environment-file'),
            ('grizzly-cli local run --yes -T key=value --environment-file', 'test.yaml test-dir'),
            ('grizzly-cli local run --yes -T key=value --environment-file test', 'test.yaml test-dir'),
            ('grizzly-cli local run --yes -T key=value --environment-file test-', 'test-dir'),
            ('grizzly-cli local run --yes -T key=value --environment-file test-dir', '-h --help --verbose -T --testdata-variable'),
            ('grizzly-cli local run --yes -T key=value --environment-file test.', 'test.yaml'),
            ('grizzly-cli local run --yes -T key=value --environment-file test.yaml', '-h --help --verbose -T --testdata-variable'),
            ('grizzly-cli local run --yes -T key=value --environment-file test.yaml --test', '--testdata-variable'),
            ('grizzly-cli local run --yes -T key=value --environment-file test.yaml --testdata-variable', ''),
            (
                'grizzly-cli local run --yes -T key=value --environment-file test.yaml --testdata-variable key=value',
                '-h --help --verbose -T --testdata-variable test.feature test-dir',
            ),
            ('grizzly-cli local run --yes -T key=value --environment-file test.yaml --testdata-variable key=value test', 'test.feature test-dir'),
            ('grizzly-cli local run --yes -T key=value --environment-file test.yaml --testdata-variable key=value test.fe', 'test.feature'),
            ('grizzly-cli local run --yes -T key=value --environment-file test.yaml --testdata-variable key=value --help', ''),
            ('grizzly-cli local run --yes -T key=value --environment-file test.yaml --testdata-variable key=value --help d', ''),
        ]
    )
    def test___call___local_run(self, input: str, expected: str, capsys: CaptureFixture, test_file_structure: None) -> None:
        capture: Optional[CaptureResult] = None

        try:
            parser = _create_parser()
            hook(parser)
            _subparsers = getattr(parser, '_subparsers', None)
            assert _subparsers is not None
            subparser: Optional[argparse.ArgumentParser]
            for subparsers in _subparsers._group_actions:
                for name, subparser in subparsers.choices.items():
                    if name == 'local':
                        break

            assert subparser is not None
            assert subparser.prog == 'grizzly-cli local'

            _subparsers = getattr(subparser, '_subparsers', None)
            assert _subparsers is not None
            for subparsers in _subparsers._group_actions:
                for name, subparser in subparsers.choices.items():
                    if name == 'run':
                        break

            assert subparser is not None
            assert subparser.prog == 'grizzly-cli local run'

            with pytest.raises(SystemExit):
                subparser.parse_args([f'--bash-complete={input}'])
            capture = capsys.readouterr()
            assert capture.out == f'{expected}\n'
        except:
            print(f'input={input}')
            print(f'expected={expected}')
            if capture is not None:
                print(f'actual={capture.out}')
            raise
        finally:
            chdir(CWD)

    @pytest.mark.parametrize(
        'input,expected', [
            ('grizzly-cli dist run ', '-h --help --verbose -T --testdata-variable -y --yes -e --environment-file test.feature test-dir'),
            ('grizzly-cli dist run -', '-h --help --verbose -T --testdata-variable -y --yes -e --environment-file'),
            ('grizzly-cli dist run --', '--help --verbose --testdata-variable --yes --environment-file'),
            ('grizzly-cli dist run --yes', '-h --help --verbose -T --testdata-variable -e --environment-file'),
            ('grizzly-cli dist run --help --yes', ''),
            ('grizzly-cli dist run --yes -T', ''),
            ('grizzly-cli dist run --yes -T key=value', '-h --help --verbose -T --testdata-variable -e --environment-file test.feature test-dir'),
            ('grizzly-cli dist run --yes -T key=value --env', '--environment-file'),
            ('grizzly-cli dist run --yes -T key=value --environment-file', 'test.yaml test-dir'),
            ('grizzly-cli dist run --yes -T key=value --environment-file test', 'test.yaml test-dir'),
            ('grizzly-cli dist run --yes -T key=value --environment-file test-', 'test-dir'),
            ('grizzly-cli dist run --yes -T key=value --environment-file test-dir', '-h --help --verbose -T --testdata-variable'),
            ('grizzly-cli dist run --yes -T key=value --environment-file test.', 'test.yaml'),
            ('grizzly-cli dist run --yes -T key=value --environment-file test.yaml', '-h --help --verbose -T --testdata-variable'),
            ('grizzly-cli dist run --yes -T key=value --environment-file test.yaml --test', '--testdata-variable'),
            ('grizzly-cli dist run --yes -T key=value --environment-file test.yaml --testdata-variable', ''),
            (
                'grizzly-cli dist run --yes -T key=value --environment-file test.yaml --testdata-variable key=value',
                '-h --help --verbose -T --testdata-variable test.feature test-dir',
            ),
            ('grizzly-cli dist run --yes -T key=value --environment-file test.yaml --testdata-variable key=value test', 'test.feature test-dir'),
            ('grizzly-cli dist run --yes -T key=value --environment-file test.yaml --testdata-variable key=value test.fe', 'test.feature'),
            ('grizzly-cli dist run --yes -T key=value --environment-file test.yaml --testdata-variable key=value --help', ''),
            ('grizzly-cli dist run --yes -T key=value --environment-file test.yaml --testdata-variable key=value --help d', ''),
        ]
    )
    def test___call___dist_run(self, input: str, expected: str, capsys: CaptureFixture, test_file_structure: None) -> None:
        capture: Optional[CaptureResult] = None

        try:
            parser = _create_parser()
            hook(parser)
            _subparsers = getattr(parser, '_subparsers', None)
            assert _subparsers is not None
            subparser: Optional[argparse.ArgumentParser]
            for subparsers in _subparsers._group_actions:
                for name, subparser in subparsers.choices.items():
                    if name == 'dist':
                        break

            assert subparser is not None
            assert subparser.prog == 'grizzly-cli dist'

            _subparsers = getattr(subparser, '_subparsers', None)
            assert _subparsers is not None
            for subparsers in _subparsers._group_actions:
                for name, subparser in subparsers.choices.items():
                    if name == 'run':
                        break

            assert subparser is not None
            assert subparser.prog == 'grizzly-cli dist run'

            with pytest.raises(SystemExit):
                subparser.parse_args([f'--bash-complete={input}'])
            capture = capsys.readouterr()
            assert capture.out == f'{expected}\n'
        except:
            print(f'input={input}')
            print(f'expected={expected}')
            if capture is not None:
                print(f'actual={capture.out}')
            raise
        finally:
            chdir(CWD)

    @pytest.mark.parametrize(
        'input,expected',
        [
            (
                'grizzly-cli dist',
                (
                    '-h --help --workers --id --limit-nofile --health-retries --health-timeout --health-interval --registry '
                    '--tty --wait-for-worker --force-build --build --validate-config build run'
                )
            ),
            (
                'grizzly-cli dist -',
                (
                    '-h --help --workers --id --limit-nofile --health-retries --health-timeout --health-interval --registry '
                    '--tty --wait-for-worker --force-build --build --validate-config'
                ),
            ),
            (
                'grizzly-cli dist --',
                (
                    '--help --workers --id --limit-nofile --health-retries --health-timeout --health-interval --registry '
                    '--tty --wait-for-worker --force-build --build --validate-config'
                ),
            ),
            (
                'grizzly-cli dist --workers',
                '',
            ),
            (
                'grizzly-cli dist --workers asdf',
                '',
            ),
            (
                'grizzly-cli dist --workers 8',
                (
                    '-h --help --id --limit-nofile --health-retries --health-timeout --health-interval --registry --tty '
                    '--wait-for-worker --force-build --build --validate-config build run'
                ),
            ),
            (
                'grizzly-cli dist --workers 8 --force-build',
                '-h --help --id --limit-nofile --health-retries --health-timeout --health-interval --registry --tty --wait-for-worker build run',
            ),
        ],
    )
    def test___call__dist(self, input: str, expected: str, capsys: CaptureFixture, test_file_structure: None) -> None:
        capture: Optional[CaptureResult] = None

        try:
            parser = _create_parser()
            hook(parser)
            _subparsers = getattr(parser, '_subparsers', None)
            assert _subparsers is not None
            subparser: Optional[argparse.ArgumentParser]
            for subparsers in _subparsers._group_actions:
                for name, subparser in subparsers.choices.items():
                    if name == 'dist':
                        break

            assert subparser is not None
            assert subparser.prog == 'grizzly-cli dist'

            with pytest.raises(SystemExit):
                subparser.parse_args([f'--bash-complete={input}'])
            capture = capsys.readouterr()
            assert capture.out == f'{expected}\n'
        except:
            print(f'input={input}')
            print(f'expected={expected}')
            if capture is not None:
                print(f'actual={capture.out}')
            raise
        finally:
            chdir(CWD)


def test_hook(mocker: MockerFixture) -> None:
    parser = argparse.ArgumentParser(prog='test-prog')
    action = parser.add_argument('--test')

    assert len(parser._actions) == 2

    hook(parser)

    assert len(parser._actions) == 3

    option_strings = [option for action in parser._actions for option in action.option_strings]

    assert option_strings == ['-h', '--help', '--test', '--bash-complete']

    try:
        hook(parser)
    except argparse.ArgumentError as e:
        pytest.fail(str(e))

    subparsers = parser.add_subparsers(dest='test')
    subparser = subparsers.add_parser('test')

    assert len(subparser._actions) == 1

    hook(parser)

    assert len(subparser._actions) == 2

    option_strings = [option for action in subparser._actions for option in action.option_strings]

    assert option_strings == ['-h', '--help', '--bash-complete']

    mocker.patch.object(parser, 'add_argument', side_effect=[
        argparse.ArgumentError(message='unrecognized arguments: --bash-completion', argument=action),
        RuntimeError('something else'),
    ])

    with pytest.raises(argparse.ArgumentError) as ae:
        hook(parser)
    assert 'unrecognized arguments: --bash-completion' in ae.value.message

    with pytest.raises(RuntimeError) as re:
        hook(parser)
    assert 'something else' in str(re)
