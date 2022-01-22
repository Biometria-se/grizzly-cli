from pydoc import describe
from re import A
import pytest

import argparse

from pytest_mock import mocker, MockerFixture

from grizzly_cli.argparse.markdown import MarkdownFormatter, MarkdownHelpAction


class TestMarkdownHelpAction:
    def test___init__(self) -> None:
        action = MarkdownHelpAction(['-t', '--test'])

        assert isinstance(action, argparse.Action)
        assert action.option_strings == ['-t', '--test']
        assert action.dest == argparse.SUPPRESS
        assert action.default == argparse.SUPPRESS
        assert action.nargs == 0

    def test___call__(self, mocker: MockerFixture) -> None:
        parser = argparse.ArgumentParser(description='test parser')
        parser.add_argument('--md-help', action=MarkdownHelpAction)

        print_help = mocker.patch.object(parser._actions[-1], 'print_help', autospec=True)

        with pytest.raises(SystemExit) as e:
            parser.parse_args(['--md-help'])
        assert e.type == SystemExit
        assert e.value.code == 0

        assert print_help.call_count == 1
        args, _ = print_help.call_args_list[0]
        assert args[0] is parser

    def test_print_help(self, mocker: MockerFixture) -> None:
        action = MarkdownHelpAction(['-t', '--test'])
        parser = argparse.ArgumentParser(description='test parser')
        parser.add_argument('--md-help', action=MarkdownHelpAction)

        subparsers = parser.add_subparsers(dest='subparser')

        a_parser = subparsers.add_parser('a', description='parser a')
        subparsers.add_parser('b', description='parser b')

        a_subparsers = a_parser.add_subparsers(dest='a_subparsers')
        a_subparsers.add_parser('aa', description='parser aa')

        print_help = mocker.patch('argparse.ArgumentParser.print_help', autospec=True)

        action.print_help(parser)

        assert print_help.call_count == 4
        assert parser.formatter_class == MarkdownFormatter
        assert parser._subparsers is not None

        _subparsers = getattr(parser, '_subparsers', None)
        assert _subparsers is not None
        for subparsers in _subparsers._group_actions:
            for name, subparser in subparsers.choices.items():
                assert subparser.formatter_class == MarkdownFormatter
                if name == 'a':
                    _subsubparsers = getattr(subparser, '_subparsers', None)
                    assert _subsubparsers is not None
                    for subsubparsers in _subsubparsers._group_actions:
                        for subsubparser in subsubparsers.choices.values():
                            assert subsubparser.formatter_class == MarkdownFormatter

    def test_print_help__format_help_markdown(self, mocker: MockerFixture) -> None:
        action = MarkdownHelpAction(['-t', '--test'])
        parser = argparse.ArgumentParser(description='test parser')

        formatter = MarkdownFormatter('test-prog')

        _get_formatter = mocker.patch.object(parser, '_get_formatter', side_effect=[formatter])
        add_text = mocker.patch.object(formatter, 'add_text', autospec=True)
        add_usage = mocker.patch.object(formatter, 'add_usage', autospec=True)
        start_section = mocker.patch.object(formatter, 'start_section', autospec=True)
        end_section = mocker.patch.object(formatter, 'end_section', autospec=True)
        add_arguments = mocker.patch.object(formatter, 'add_arguments', autospec=True)

        action.print_help(parser)

        assert _get_formatter.call_count == 1
        assert add_text.call_count == 5
        assert add_usage.call_count == 1
        assert start_section.call_count == 2
        assert start_section.call_args_list[0][0][0] == 'positional arguments'
        assert start_section.call_args_list[1][0][0] == 'optional arguments'
        assert end_section.call_count == 2
        assert add_arguments.call_count == 2

class TestMarkdownFormatter:
    def test___init__(self) -> None:
        formatter = MarkdownFormatter('test')
        assert formatter._root_section is formatter._current_section
        assert formatter._root_section.parent is None
        assert MarkdownFormatter.level == 0
        assert formatter.current_level == 1

    def test__format_usage(self) -> None:
        formatter = MarkdownFormatter('test')
        usage = formatter._format_usage('test', None, None, 'a prefix')
        assert usage == '''
### Usage

```bash
test
```
'''
        parser = argparse.ArgumentParser(prog='test', description='test parser')
        parser.add_argument('-t', '--test', type=str, required=True, help='test argument')
        parser.add_argument('file', nargs=1, help='file argument')

        core_formatter = parser.formatter_class(parser.prog)

        usage = core_formatter._format_usage(parser.usage, parser._get_positional_actions(), parser._mutually_exclusive_groups, 'a prefix ')  # type: ignore
        assert usage == '''a prefix test file

'''


        usage = formatter._format_usage(parser.usage, parser._get_positional_actions(), parser._mutually_exclusive_groups, 'a prefix ')
        assert usage == '''
### Usage

```bash
test file
```
'''

    def test_format_help(self) -> None:
        formatter = MarkdownFormatter('test')
        assert formatter.format_help() == ''
        assert formatter._root_section.heading == '# `test`'

    def test_format_text(self) -> None:
        formatter = MarkdownFormatter('test-prog')
        text = '''%(prog)s is awesome!
also, here is a sentence. and here is another one!

```bash
hostname -f
```

you cannot belive it, it's another sentence.
'''
        print(formatter._format_text(text))
        assert formatter._format_text(text) == '''test-prog is awesome!
Also, here is a sentence. And here is another one!

```bash
hostname -f
```

You cannot belive it, it's another sentence.
'''

    def test_start_section(self) -> None:
        formatter = MarkdownFormatter('test-prog')
        assert formatter._root_section is formatter._current_section

        formatter.start_section('test-section-01')

        assert formatter._current_section is not formatter._root_section
        assert formatter._current_section.parent is formatter._root_section
        assert formatter._current_section.heading == '## Test-section-01'
        assert len(formatter._current_section.items) == 0
        assert formatter._current_section.parent.items[0] == (formatter._current_section.format_help, [],)
