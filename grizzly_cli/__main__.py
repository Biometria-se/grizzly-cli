import argparse
import os
import sys

from shutil import which
from typing import Tuple, Optional, List
from traceback import format_exc

from .argparse import ArgumentParser
from .utils import ask_yes_no, get_distributed_system, get_dependency_versions, setup_logging
from .init import init
from .local import local
from .distributed import distributed
from .auth import auth
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

    if hasattr(args, 'file'):
        # needed to support file names with spaces, which is escaped (sh-style)
        setattr(args, 'file', ' '.join(args.file))

    if args.version:
        if __version__ == '0.0.0':
            version = '(development)'
        else:
            version = __version__

        grizzly_versions: Optional[Tuple[Optional[str], Optional[List[str]]]] = None

        if args.version == 'all':
            grizzly_versions, locust_version = get_dependency_versions(False)
        else:
            grizzly_versions, locust_version = None, None

        print(f'grizzly-cli {version}')
        if grizzly_versions is not None:
            grizzly_version, grizzly_extras = grizzly_versions
            if grizzly_version is not None:
                print(f'└── grizzly {grizzly_version}', end='')
                if grizzly_extras is not None and len(grizzly_extras) > 0:
                    print(f' ── extras: {", ".join(grizzly_extras)}', end='')
                print('')

        if locust_version is not None:
            print(f'    └── locust {locust_version}')

        raise SystemExit(0)

    if args.command is None:
        parser.error('no command specified')

    if getattr(args, 'subcommand', None) is None and args.command not in ['init', 'auth']:
        parser.error_no_help(f'no subcommand for {args.command} specified')

    if args.command == 'dist':
        args.container_system = get_distributed_system()

        if args.container_system is None:
            parser.error_no_help('cannot run distributed')

        if args.registry is not None and not args.registry.endswith('/'):
            setattr(args, 'registry', f'{args.registry}/')
    elif args.command in ['init', 'auth']:
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

        if args.csv_prefix is None:
            if args.csv_interval is not None:
                parser.error_no_help('--csv-interval can only be used in combination with --csv-prefix')

            if args.csv_flush_interval is not None:
                parser.error_no_help('--csv-flush-interval can only be used in combination with --csv-prefix')
    elif args.command == 'dist' and args.subcommand == 'build':
        setattr(args, 'force_build', args.no_cache)
        setattr(args, 'build', not args.no_cache)

    log_file = getattr(args, 'log_file', None)
    setup_logging(log_file)

    return args


def _inject_additional_arguments_from_metadata(args: argparse.Namespace) -> argparse.Namespace:
    with open(args.file) as fd:
        file_metadata = [line.strip().replace('# grizzly-cli ', '').split(' ') for line in fd.readlines() if line.strip().startswith('# grizzly-cli ')]

    if len(file_metadata) < 1:
        return args

    argv = sys.argv[1:]
    for additional_arguments in file_metadata:
        try:
            if additional_arguments[0].strip().startswith('-'):
                raise ValueError()

            index = argv.index(additional_arguments[0]) + 1
            for zindex, additional_argument in enumerate(additional_arguments[1:]):
                argv.insert(index + zindex, additional_argument)
        except ValueError:
            print('?? ignoring {}'.format(' '.join(additional_arguments)))

    sys.argv = sys.argv[0:1] + argv

    return _parse_arguments()


def main() -> int:
    args: Optional[argparse.Namespace] = None

    try:
        args = _parse_arguments()

        if getattr(args, 'file', None) is not None:
            args = _inject_additional_arguments_from_metadata(args)

        if args.command == 'local':
            rc = local(args)
        elif args.command == 'dist':
            rc = distributed(args)
        elif args.command == 'init':
            rc = init(args)
        elif args.command == 'auth':
            rc = auth(args)
        else:
            raise ValueError(f'unknown command {args.command}')

        return rc
    except (KeyboardInterrupt, ValueError) as e:
        print('')
        if isinstance(e, ValueError):
            if args is not None and getattr(args, 'verbose', False):
                exception = format_exc()
            else:
                exception = str(e)

            print(exception)

        print('\n!! aborted grizzly-cli')
        return 1
