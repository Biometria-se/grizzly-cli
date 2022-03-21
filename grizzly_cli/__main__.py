import argparse
import os

from shutil import which

from .argparse import ArgumentParser
from .argparse.bashcompletion import BashCompletionTypes
from .utils import ask_yes_no, get_distributed_system, get_dependency_versions
from .run import run
from .build import build
from .init import init
from . import __version__


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

    # grizzly-cli init
    init_parser = sub_parser.add_parser('init', description=(
        'create a skeleton project with required structure and files.'
    ))

    init_parser.add_argument(
        'project',
        nargs=None,  # type: ignore
        type=str,
        help='project name, a directory will be created with this name',
    )

    init_parser.add_argument(
        '--grizzly-version',
        type=str,
        required=False,
        default=None,
        help='specify which grizzly version to use for project, default is latest'
    )

    init_parser.add_argument(
        '--with-mq',
        action='store_true',
        default=False,
        required=False,
        help='if grizzly should be installed with IBM MQ support (external dependencies excluded)',
    )

    if init_parser.prog != 'grizzly-cli init':  # pragma: no cover
        init_parser.prog = 'grizzly-cli init'

    # grizzly-cli build ...
    build_parser = sub_parser.add_parser('build', description=(
        'build grizzly compose project container image. this command is only applicable if grizzly '
        'should run distributed and is used to pre-build the container images. if worker nodes runs '
        'on different physical computers, it is mandatory to build the images before hand and push to a registry.'
    ))
    build_parser.add_argument(
        '--no-cache',
        action='store_true',
        required=False,
        help='build container image with out cache (full build)',
    )
    build_parser.add_argument(
        '--registry',
        type=str,
        default=None,
        required=False,
        help='push built image to this registry, if the registry has authentication you need to login first',
    )

    if build_parser.prog != 'grizzly-cli build':  # pragma: no cover
        build_parser.prog = 'grizzly-cli build'

    # grizzly-cli run ...
    run_parser = sub_parser.add_parser('run', description='execute load test scenarios specified in a feature file.')
    run_parser.add_argument(
        '--verbose',
        action='store_true',
        required=False,
        help=(
            'changes the log level to `DEBUG`, regardless of what it says in the feature file. gives more verbose logging '
            'that can be useful when troubleshooting a problem with a scenario.'
        )
    )
    run_parser.add_argument(
        '-T', '--testdata-variable',
        action='append',
        type=str,
        required=False,
        help=(
            'specified in the format `<name>=<value>`. avoids being asked for an initial value for a scenario variable.'
        )
    )
    run_parser.add_argument(
        '-y', '--yes',
        action='store_true',
        default=False,
        required=False,
        help='answer yes on any questions that would require confirmation',
    )
    run_parser.add_argument(
        '-e', '--environment-file',
        type=BashCompletionTypes.File('*.yaml', '*.yml'),
        required=False,
        default=None,
        help='configuration file with [environment specific information](/grizzly/usage/variables/environment-configuration/)',
    )

    if run_parser.prog != 'grizzly-cli run':  # pragma: no cover
        run_parser.prog = 'grizzly-cli run'

    run_sub_parser = run_parser.add_subparsers(dest='mode')

    file_kwargs = {
        'nargs': None,
        'type': BashCompletionTypes.File('*.feature'),
        'help': 'path to feature file with one or more scenarios',
    }

    # grizzly-cli run local ...
    run_local_parser = run_sub_parser.add_parser('local', description='arguments for running grizzly locally.')
    run_local_parser.add_argument(
        'file',
        **file_kwargs,  # type: ignore
    )

    if run_local_parser.prog != 'grizzly-cli run local':  # pragma: no cover
        run_local_parser.prog = 'grizzly-cli run local'

    # grizzly-cli run dist ...
    run_dist_parser = run_sub_parser.add_parser('dist', description='arguments for running grizzly distributed.')
    run_dist_parser.add_argument(
        'file',
        **file_kwargs,  # type: ignore
    )
    run_dist_parser.add_argument(
        '--workers',
        type=int,
        required=False,
        default=1,
        help='how many instances of the `workers` container that should be created',
    )
    run_dist_parser.add_argument(
        '--container-system',
        type=str,
        choices=['podman', 'docker', None],
        required=False,
        default=None,
        help=argparse.SUPPRESS,
    )
    run_dist_parser.add_argument(
        '--id',
        type=str,
        required=False,
        default=None,
        help='unique identifier suffixed to compose project, should be used when the same user needs to run more than one instance of `grizzly-cli`',
    )
    run_dist_parser.add_argument(
        '--limit-nofile',
        type=int,
        required=False,
        default=10001,
        help='set system limit "number of open files"',
    )
    run_dist_parser.add_argument(
        '--health-retries',
        type=int,
        required=False,
        default=3,
        help='set number of retries for health check of master container',
    )
    run_dist_parser.add_argument(
        '--health-timeout',
        type=int,
        required=False,
        default=3,
        help='set timeout in seconds for health check of master container',
    )
    run_dist_parser.add_argument(
        '--health-interval',
        type=int,
        required=False,
        default=5,
        help='set interval in seconds between health checks of master container',
    )
    run_dist_parser.add_argument(
        '--registry',
        type=str,
        default=None,
        required=False,
        help='push built image to this registry, if the registry has authentication you need to login first',
    )

    group_build = run_dist_parser.add_mutually_exclusive_group()
    group_build.add_argument(
        '--force-build',
        action='store_true',
        required=False,
        help='force rebuild the grizzly projects container image (no cache)',
    )
    group_build.add_argument(
        '--build',
        action='store_true',
        required=False,
        help='rebuild the grizzly projects container images (with cache)',
    )
    group_build.add_argument(
        '--validate-config',
        action='store_true',
        required=False,
        help='validate and print compose project file',
    )

    if run_dist_parser.prog != 'grizzly-cli run dist':  # pragma: no cover
        run_dist_parser.prog = 'grizzly-cli run dist'

    return parser


def _parse_arguments() -> argparse.Namespace:
    parser = _create_parser()
    args = parser.parse_args()

    if args.version:
        if __version__ == '0.0.0':
            version = '(development)'
        else:
            version = __version__

        if args.version == 'all':
            grizzly_version, locust_version = get_dependency_versions()
        else:
            grizzly_version, locust_version = None, None

        print(f'grizzly-cli {version}')
        if grizzly_version is not None:
            print(f'└── grizzly {grizzly_version}')

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
