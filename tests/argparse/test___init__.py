from argparse import ArgumentError, ArgumentParser as CoreArgumentParser
from typing import Tuple
import pytest

from _pytest.capture import CaptureFixture

from grizzly_cli.argparse import ArgumentParser
from grizzly_cli.argparse.markdown import MarkdownFormatter

@pytest.fixture
def parsers() -> Tuple[CoreArgumentParser, ...]:
    parser = ArgumentParser(prog='test-prog', description='test parser', markdown_help=True, bash_completion=True)

    parser.add_argument('--root-parser', type=str, default='root-parser', help='root parser argument')

    parsers = parser.add_subparsers(description='sub parser a')
    a_sub_parser = parsers.add_parser('a')
    a_sub_parser.add_argument('--a-parser', action='store_true', default=False, help='a parser [argument](http://localhost)')

    b_sub_parser = parsers.add_parser('b')
    b_sub_parser.add_argument('--b-parser', type=str, help='b parser argument')

    return parser, a_sub_parser, b_sub_parser


class TestArgumentParser:
    def test___init__(self) -> None:
        parser = ArgumentParser(description='test parser')

        assert not parser.markdown_help
        assert not parser.bash_completion
        assert len(parser._actions) == 1

        parser = ArgumentParser(description='test parser', markdown_help=True, bash_completion=True)

        assert parser.markdown_help
        assert parser.bash_completion
        assert len(parser._actions) == 3

        option_strings = [option for action in parser._actions for option in action.option_strings]

        assert option_strings == ['-h', '--help', '--md-help', '--bash-completion']

        parser = ArgumentParser(bash_completion=True, description='test parser')

        assert not parser.markdown_help
        assert parser.bash_completion
        assert len(parser._actions) == 2

        option_strings = [option for action in parser._actions for option in action.option_strings]

        assert option_strings == ['-h', '--help', '--bash-completion']

        parser = ArgumentParser(markdown_help=True, description='test parser')

        assert parser.markdown_help
        assert not parser.bash_completion
        assert len(parser._actions) == 2

        option_strings = [option for action in parser._actions for option in action.option_strings]

        assert option_strings == ['-h', '--help', '--md-help']

        parser = ArgumentParser(markdown_help=False, bash_completion=False, description='test parser')

        assert not parser.markdown_help
        assert not parser.bash_completion
        assert len(parser._actions) == 1

        option_strings = [option for action in parser._actions for option in action.option_strings]

        assert option_strings == ['-h', '--help']

    def test_error_no_help(self, capsys: CaptureFixture) -> None:
        parser = ArgumentParser(markdown_help=False, description='test parser', prog='test-prog')
        with pytest.raises(SystemExit) as e:
            parser.error_no_help('test test test')
        assert e.type == SystemExit
        assert e.value.code == 2

        capture = capsys.readouterr()
        assert capture.err == 'test-prog: error: test test test\n'
        assert capture.out == ''

    def test_print_help_HelpFormatter(self, capsys: CaptureFixture, parsers: Tuple[ArgumentParser, ...]) -> None:
        parser, a_sub_parser, b_sub_parser = parsers

        parser.markdown_help = False
        parser.print_help()
        capture = capsys.readouterr()

        assert capture.out == '''usage: test-prog [-h] [--root-parser ROOT_PARSER] {a,b} ...

test parser

optional arguments:
  -h, --help            show this help message and exit
  --root-parser ROOT_PARSER
                        root parser argument

subcommands:
  sub parser a

  {a,b}
'''
        parser.markdown_help = True
        parser.print_help()
        capture = capsys.readouterr()

        assert capture.out == '''usage: test-prog [-h] [--root-parser ROOT_PARSER] {a,b} ...

test parser

optional arguments:
  -h, --help            show this help message and exit
  --root-parser ROOT_PARSER
                        root parser argument

subcommands:
  sub parser a

  {a,b}
'''

        a_sub_parser.markdown_help = False
        a_sub_parser.print_help()
        capture = capsys.readouterr()

        assert capture.out == '''usage: test-prog a [-h] [--a-parser]

optional arguments:
  -h, --help  show this help message and exit
  --a-parser  a parser [argument](http://localhost)
'''

        a_sub_parser.markdown_help = True
        a_sub_parser.print_help()
        capture = capsys.readouterr()

        assert capture.out == '''usage: test-prog a [-h] [--a-parser]

optional arguments:
  -h, --help  show this help message and exit
  --a-parser  a parser argument
'''

        b_sub_parser.print_help()
        capture = capsys.readouterr()

        assert capture.out == '''usage: test-prog b [-h] [--b-parser B_PARSER]

optional arguments:
  -h, --help           show this help message and exit
  --b-parser B_PARSER  b parser argument
'''

    def test_print_help_MarkdownFormatter(self, capsys: CaptureFixture, parsers: Tuple[ArgumentParser, ...]) -> None:
        parser, _, _ = parsers
        parser.formatter_class = MarkdownFormatter

        parser.print_help()
        capture = capsys.readouterr()

        assert capture.out == '''# `test-prog`

### Usage

```bash
test-prog [-h] [--root-parser ROOT_PARSER] {a,b} ...
```
test parser
## Optional arguments

| argument | default | help |
| -------- | ------- | ---- |
| `--root-parser` | `root-parser` | root parser argument |

## Subcommands
sub parser a
'''

    def test_parse_args(self, parsers: Tuple[ArgumentParser, ...]) -> None:
        parser, a_sub_parser, b_sub_parser = parsers

        parser.parse_args([])

        # parser
        all_option_strings = [option for action in parser._actions for option in action.option_strings]
        assert '--bash-complete' in all_option_strings

        # a_sub_parser
        all_option_strings = [option for action in a_sub_parser._actions for option in action.option_strings]
        assert '--bash-complete' in all_option_strings

        # b_sub_parser
        all_option_strings = [option for action in b_sub_parser._actions for option in action.option_strings]
        assert '--bash-complete' in all_option_strings

        try:
            parser.parse_args([])
        except ArgumentError as e:
            pytest.fail(str(e))

    def test_md_help_action_from_parser(self, capsys: CaptureFixture, parsers: Tuple[ArgumentParser, ...]) -> None:
        parser, _, _ = parsers

        with pytest.raises(SystemExit) as e:
            parser.parse_args(['--md-help'])
        assert e.type == SystemExit
        assert e.value.code == 0

        capture = capsys.readouterr()

        print(capture)

        assert capture.out == '''# `test-prog`

test parser

### Usage

```bash
test-prog [-h] [--root-parser ROOT_PARSER] {a,b} ...
```

## Optional arguments

| argument | default | help |
| -------- | ------- | ---- |
| `--root-parser` | `root-parser` | root parser argument |

## Subcommands
sub parser a

### `test-prog a`

#### Usage

```bash
test-prog a [-h] [--a-parser]
```

#### Optional arguments

| argument | default | help |
| -------- | ------- | ---- |
| `--a-parser` | `False` | a parser [argument](http://localhost) |

### `test-prog b`

#### Usage

```bash
test-prog b [-h] [--b-parser B_PARSER]
```

#### Optional arguments

| argument | default | help |
| -------- | ------- | ---- |
| `--b-parser` |  | b parser argument |
'''

