import os
import sys
import argparse

from typing import List, Dict, Any, cast
from tempfile import NamedTemporaryFile
from getpass import getuser
from shutil import get_terminal_size
from argparse import Namespace as Arguments
from platform import node as get_hostname

from . import EXECUTION_CONTEXT, STATIC_CONTEXT, MOUNT_CONTEXT, PROJECT_NAME, register_parser
from .utils import (
    find_variable_names_in_questions,
    ask_yes_no, get_input,
    distribution_of_users_per_scenario,
    is_docker_compose_v2,
    requirements,
    run_command,
    get_default_mtu,
    list_images,
)
from .build import build
from .argparse import ArgumentSubParser
from .argparse.bashcompletion import BashCompletionTypes


@register_parser(order=3)
def create_parser(sub_parser: ArgumentSubParser) -> None:
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
        **file_kwargs,
    )

    if run_local_parser.prog != 'grizzly-cli run local':  # pragma: no cover
        run_local_parser.prog = 'grizzly-cli run local'

    # grizzly-cli run dist ...
    run_dist_parser = run_sub_parser.add_parser('dist', description='arguments for running grizzly distributed.')
    run_dist_parser.add_argument(
        'file',
        **file_kwargs,
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
    run_dist_parser.add_argument(
        '--tty',
        action='store_true',
        default=False,
        required=False,
        help='start containers with a TTY enabled',
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


def distributed(args: Arguments, environ: Dict[str, Any], run_arguments: Dict[str, List[str]]) -> int:
    suffix = '' if args.id is None else f'-{args.id}'
    tag = getuser()

    # default locust project
    compose_args: List[str] = [
        '-p', f'{PROJECT_NAME}{suffix}-{tag}',
        '-f', f'{STATIC_CONTEXT}/compose.yaml',
    ]

    if args.file is not None:
        os.environ['GRIZZLY_RUN_FILE'] = args.file

    mtu = get_default_mtu(args)

    if mtu is None and os.environ.get('GRIZZLY_MTU', None) is None:
        print('!! unable to determine MTU, try manually setting GRIZZLY_MTU environment variable if anything other than 1500 is needed')
        mtu = '1500'

    columns, lines = get_terminal_size()

    # set environment variables needed by compose files, when *-compose executes
    os.environ['GRIZZLY_MTU'] = cast(str, mtu)
    os.environ['GRIZZLY_EXECUTION_CONTEXT'] = EXECUTION_CONTEXT
    os.environ['GRIZZLY_STATIC_CONTEXT'] = STATIC_CONTEXT
    os.environ['GRIZZLY_MOUNT_CONTEXT'] = MOUNT_CONTEXT
    os.environ['GRIZZLY_PROJECT_NAME'] = PROJECT_NAME
    os.environ['GRIZZLY_USER_TAG'] = tag
    os.environ['GRIZZLY_EXPECTED_WORKERS'] = str(args.workers)
    os.environ['GRIZZLY_LIMIT_NOFILE'] = str(args.limit_nofile)
    os.environ['GRIZZLY_HEALTH_CHECK_RETRIES'] = str(args.health_retries)
    os.environ['GRIZZLY_HEALTH_CHECK_INTERVAL'] = str(args.health_interval)
    os.environ['GRIZZLY_HEALTH_CHECK_TIMEOUT'] = str(args.health_timeout)
    os.environ['GRIZZLY_IMAGE_REGISTRY'] = getattr(args, 'registry', None) or ''
    os.environ['GRIZZLY_CONTAINER_TTY'] = 'true' if args.tty else 'false'
    os.environ['COLUMNS'] = str(columns)
    os.environ['LINES'] = str(lines)

    if len(run_arguments.get('master', [])) > 0:
        os.environ['GRIZZLY_MASTER_RUN_ARGS'] = ' '.join(run_arguments['master'])

    if len(run_arguments.get('worker', [])) > 0:
        os.environ['GRIZZLY_WORKER_RUN_ARGS'] = ' '.join(run_arguments['worker'])

    if len(run_arguments.get('common', [])) > 0:
        os.environ['GRIZZLY_COMMON_RUN_ARGS'] = ' '.join(run_arguments['common'])

    # check if we need to build image
    images = list_images(args)

    with NamedTemporaryFile() as fd:
        # file will be deleted when conContainertext exits
        if len(environ) > 0:
            for key, value in environ.items():
                if key == 'GRIZZLY_CONFIGURATION_FILE':
                    value = value.replace(EXECUTION_CONTEXT, MOUNT_CONTEXT).replace(MOUNT_CONTEXT, '/srv/grizzly')

                fd.write(f'{key}={value}\n'.encode('utf-8'))

        fd.write(f'COLUMNS={columns}\n'.encode('utf-8'))
        fd.write(f'LINES={lines}\n'.encode('utf-8'))
        fd.write(f'GRIZZLY_CONTAINER_TTY={os.environ["GRIZZLY_CONTAINER_TTY"]}\n'.encode('utf-8'))

        fd.flush()

        os.environ['GRIZZLY_ENVIRONMENT_FILE'] = fd.name

        validate_config = getattr(args, 'validate_config', False)

        compose_command = [
            f'{args.container_system}-compose',
            *compose_args,
            'config',
        ]

        rc = run_command(compose_command, silent=not validate_config)

        if validate_config or rc != 0:
            if rc != 0 and not validate_config:
                print('!! something in the compose project is not valid, check with:')
                print(f'grizzly-cli {" ".join(sys.argv[1:])} --validate-config')

            return rc

        if images.get(PROJECT_NAME, {}).get(tag, None) is None or args.force_build or args.build:
            rc = build(args)
            if rc != 0:
                print(f'!! failed to build {PROJECT_NAME}, rc={rc}')
                return rc

        compose_scale_argument = ['--scale', f'worker={args.workers}']

        # bring up containers
        compose_command = [
            f'{args.container_system}-compose',
            *compose_args,
            'up',
            *compose_scale_argument,
            '--remove-orphans',
        ]

        rc = run_command(compose_command, verbose=args.verbose)

        # stop containers
        compose_command = [
            f'{args.container_system}-compose',
            *compose_args,
            'stop',
        ]

        run_command(compose_command)

        if rc != 0:
            print('\n!! something went wrong, check container logs with:')
            template = '{container_system} container logs '
            if is_docker_compose_v2():
                template += '{project}{suffix}-{tag}-{node}-{index}'
                start_index = 2
            else:
                template += '{project}{suffix}-{tag}_{node}_{index}'
                start_index = 1

            print(template.format(
                container_system=args.container_system,
                project=PROJECT_NAME,
                suffix=suffix,
                tag=tag,
                node='master',
                index=1
            ))

            for worker in range(start_index, args.workers + start_index):
                print(template.format(
                    container_system=args.container_system,
                    project=PROJECT_NAME,
                    suffix=suffix,
                    tag=tag,
                    node='worker',
                    index=worker
                ))

        return rc


def local(args: Arguments, environ: Dict[str, Any], run_arguments: Dict[str, List[str]]) -> int:
    for key, value in environ.items():
        if key not in os.environ:
            os.environ[key] = value

    command = [
        'behave',
    ]

    if args.file is not None:
        command += [args.file]

    if len(run_arguments.get('master', [])) > 0 or len(run_arguments.get('worker', [])) > 0 or len(run_arguments.get('common', [])) > 0:
        command += run_arguments['master'] + run_arguments['worker'] + run_arguments['common']

    return run_command(command)


@requirements(EXECUTION_CONTEXT)
def run(args: Arguments) -> int:
    # always set hostname of host where grizzly-cli was executed, could be useful
    environ: Dict[str, Any] = {
        'GRIZZLY_CLI_HOST': get_hostname(),
        'GRIZZLY_EXECUTION_CONTEXT': EXECUTION_CONTEXT,
        'GRIZZLY_MOUNT_CONTEXT': MOUNT_CONTEXT,
    }

    variables = find_variable_names_in_questions(args.file)
    questions = len(variables)
    manual_input = False

    if questions > 0 and not getattr(args, 'validate_config', False):
        print(f'feature file requires values for {questions} variables')

        for variable in variables:
            name = f'TESTDATA_VARIABLE_{variable}'
            value = os.environ.get(name, '')
            while len(value) < 1:
                value = get_input(f'initial value for "{variable}": ')
                manual_input = True

            environ[name] = value

        print('the following values was provided:')
        for key, value in environ.items():
            if not key.startswith('TESTDATA_VARIABLE_'):
                continue
            print(f'{key.replace("TESTDATA_VARIABLE_", "")} = {value}')

        if manual_input:
            ask_yes_no('continue?')

    if args.environment_file is not None:
        environment_file = os.path.realpath(args.environment_file)
        environ['GRIZZLY_CONFIGURATION_FILE'] = environment_file

    if not getattr(args, 'validate_config', False):
        distribution_of_users_per_scenario(args, environ)

    if args.mode == 'dist':
        run = distributed
    else:
        run = local

    run_arguments: Dict[str, List[str]] = {
        'master': [],
        'worker': [],
        'common': ['--stop'],
    }

    if args.verbose:
        run_arguments['common'] += ['--verbose', '--no-logcapture', '--no-capture', '--no-capture-stderr']

    return run(args, environ, run_arguments)
