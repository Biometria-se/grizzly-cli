import argparse
import os

from shutil import which
from typing import Tuple, Optional, List

from .argparse import ArgumentParser
from .utils import ask_yes_no, get_distributed_system, get_dependency_versions
from .run import run
from .build import build
from .init import init
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

    sub_parser = parser.add_subparsers(dest='category')

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
            print(f'└── grizzly {grizzly_version}', end='')
            if grizzly_extras is not None and len(grizzly_extras) > 0:
                print(f' ── extras: {", ".join(grizzly_extras)}', end='')
            print('')

        if locust_version is not None:
            print(f'    └── locust {locust_version}')

        raise SystemExit(0)

    if args.category is None:
        parser.error('no subcommand specified')

    if getattr(args, 'mode', None) is None and args.category == 'run':
        parser.error(f'no subcommand for {args.category} specified')

    if args.category == 'build' or (args.category == 'run' and args.mode == 'dist'):
        args.container_system = get_distributed_system()

        if args.container_system is None:
            parser.error_no_help('cannot run distributed')

        if args.registry is not None and not args.registry.endswith('/'):
            setattr(args, 'registry', f'{args.registry}/')

    if args.category == 'run':
        if args.mode == 'dist':
            if args.limit_nofile < 10001 and not args.yes:
                print('!! this will cause warning messages from locust later on')
                ask_yes_no('are you sure you know what you are doing?')
        elif args.mode == 'local':
            if which('behave') is None:
                parser.error_no_help('"behave" not found in PATH, needed when running local mode')

        if args.testdata_variable is not None:
            for variable in args.testdata_variable:
                try:
                    [name, value] = variable.split('=', 1)
                    os.environ[f'TESTDATA_VARIABLE_{name}'] = value
                except ValueError:
                    parser.error_no_help('-T/--testdata-variable needs to be in the format NAME=VALUE')
    elif args.category == 'build':
        setattr(args, 'force_build', args.no_cache)
        setattr(args, 'build', not args.no_cache)

    return args


def main() -> int:
    try:
        args = _parse_arguments()

        if args.category == 'run':
            return run(args)
        elif args.category == 'build':
            return build(args)
        elif args.category == 'init':
            return init(args)
        else:
            raise ValueError(f'unknown subcommand {args.category}')
    except (KeyboardInterrupt, ValueError) as e:
        print('')
        if isinstance(e, ValueError):
            print(str(e))

        print('\n!! aborted grizzly-cli')
        return 1
