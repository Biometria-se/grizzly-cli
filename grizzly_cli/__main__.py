import argparse
import os

from shutil import which
from typing import Tuple, Optional, List

from .argparse import ArgumentParser
from .utils import ask_yes_no, get_distributed_system, get_dependency_versions
from .init import init
from .local import local
from .distributed import distributed
from . import __version__, register_parser


def _create_parser() -> ArgumentParser:
    parser = ArgumentParser(
        description=(
            'the command line interface for grizzly, which makes it easer to start a test with all features of grizzly wrapped up nicely.\n\n'
            'installing it is a matter of:\n\n'
            '```bash\n'
            'pip install grizzly-loadtester-cli\n'
            '```\n\n'
            'enable bash completion by adding the following to your shell profile:\n\n'
            '```bash\n'
            'eval "$(grizzly-cli --bash-completion)"\n'
            '```'
        ),
        markdown_help=True,
        bash_completion=True,
    )

    if parser.prog != 'grizzly-cli':
        parser.prog = 'grizzly-cli'

    parser.add_argument(
        '--version',
        nargs='?',
        default=None,
        const=True,
        choices=['all'],
        help='print version of command line interface, and exit. add argument `all` to get versions of dependencies',
    )

    sub_parser = parser.add_subparsers(dest='command')

    for create_parser in register_parser.registered:
        create_parser(sub_parser)

    return parser


def _parse_arguments() -> argparse.Namespace:
    parser = _create_parser()
    args = parser.parse_args()

    if args.version:
        if __version__ == '0.0.0':
            version = '(development)'
        else:
            version = __version__

        grizzly_versions: Optional[Tuple[str, Optional[List[str]]]] = None

        if args.version == 'all':
            grizzly_versions, locust_version = get_dependency_versions()
        else:
            grizzly_versions, locust_version = None, None

        print(f'grizzly-cli {version}')
        if grizzly_versions is not None:
            grizzly_version, grizzly_extras = grizzly_versions
            print(f'????????? grizzly {grizzly_version}', end='')
            if grizzly_extras is not None and len(grizzly_extras) > 0:
                print(f' ?????? extras: {", ".join(grizzly_extras)}', end='')
            print('')

        if locust_version is not None:
            print(f'    ????????? locust {locust_version}')

        raise SystemExit(0)

    if args.command is None:
        parser.error('no command specified')

    if getattr(args, 'subcommand', None) is None and args.command not in ['init']:
        parser.error_no_help(f'no subcommand for {args.command} specified')

    if args.command == 'dist':
        args.container_system = get_distributed_system()

        if args.container_system is None:
            parser.error_no_help('cannot run distributed')

        if args.registry is not None and not args.registry.endswith('/'):
            setattr(args, 'registry', f'{args.registry}/')
    elif args.command == 'init':
        setattr(args, 'subcommand', None)

    if args.subcommand == 'run':
        if args.command == 'dist':
            if args.limit_nofile < 10001 and not args.yes:
                print('!! this will cause warning messages from locust later on')
                ask_yes_no('are you sure you know what you are doing?')
        elif args.command == 'local':
            if which('behave') is None:
                parser.error_no_help('"behave" not found in PATH, needed when running local mode')

        if args.testdata_variable is not None:
            for variable in args.testdata_variable:
                try:
                    [name, value] = variable.split('=', 1)
                    os.environ[f'TESTDATA_VARIABLE_{name}'] = value
                except ValueError:
                    parser.error_no_help('-T/--testdata-variable needs to be in the format NAME=VALUE')
    elif args.command == 'dist' and args.subcommand == 'build':
        setattr(args, 'force_build', args.no_cache)
        setattr(args, 'build', not args.no_cache)

    return args


def main() -> int:
    try:
        args = _parse_arguments()

        if args.command == 'local':
            return local(args)
        elif args.command == 'dist':
            return distributed(args)
        elif args.command == 'init':
            return init(args)
        else:
            raise ValueError(f'unknown command {args.command}')
    except (KeyboardInterrupt, ValueError) as e:
        print('')
        if isinstance(e, ValueError):
            print(str(e))

        print('\n!! aborted grizzly-cli')
        return 1
