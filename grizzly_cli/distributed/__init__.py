import os
import sys
import argparse
import subprocess

from typing import List, Dict, Any, cast
from tempfile import NamedTemporaryFile
from getpass import getuser
from shutil import get_terminal_size
from argparse import Namespace as Arguments
from socket import gethostname
from json import loads as jsonloads
from io import StringIO
from pathlib import Path

from .. import EXECUTION_CONTEXT, STATIC_CONTEXT, MOUNT_CONTEXT, PROJECT_NAME, register_parser
from ..utils import (
    run_command,
    get_default_mtu,
    list_images,
)
from .build import build as do_build, create_parser as build_create_parser
from .clean import clean as do_clean, create_parser as clean_create_parser
from ..run import create_parser as run_create_parser, run
from ..argparse import ArgumentSubParser


@register_parser(order=3)
def create_parser(sub_parser: ArgumentSubParser) -> None:
    dist_parser = sub_parser.add_parser('dist', description='commands for running grizzly i distributed mode.')

    dist_parser.add_argument(
        '--workers',
        type=int,
        required=False,
        default=1,
        help='how many instances of the `workers` container that should be created',
    )
    dist_parser.add_argument(
        '--container-system',
        type=str,
        choices=['podman', 'docker', None],
        required=False,
        default=None,
        help=argparse.SUPPRESS,
    )
    dist_parser.add_argument(
        '--id',
        type=str,
        required=False,
        default=None,
        help='unique identifier suffixed to compose project, should be used when the same user needs to run more than one instance of `grizzly-cli`',
    )
    dist_parser.add_argument(
        '--limit-nofile',
        type=int,
        required=False,
        default=10001,
        help='set system limit "number of open files"',
    )
    dist_parser.add_argument(
        '--health-retries',
        type=int,
        required=False,
        default=3,
        help='set number of retries for health check of master container',
    )
    dist_parser.add_argument(
        '--health-timeout',
        type=int,
        required=False,
        default=3,
        help='set timeout in seconds for health check of master container',
    )
    dist_parser.add_argument(
        '--health-interval',
        type=int,
        required=False,
        default=5,
        help='set interval in seconds between health checks of master container',
    )
    dist_parser.add_argument(
        '--registry',
        type=str,
        default=None,
        required=False,
        help='push built image to this registry, if the registry has authentication you need to login first',
    )
    dist_parser.add_argument(
        '--tty',
        action='store_true',
        default=False,
        required=False,
        help='start containers with a TTY enabled',
    )
    dist_parser.add_argument(
        '--wait-for-worker',
        type=str,
        default=None,
        required=False,
        help=(
            'sets enviroment variable LOCUST_WAIT_FOR_WORKERS_REPORT_AFTER_RAMP_UP, which tells master to wait '
            'this amount of time for worker report'
        )
    )

    dist_parser.add_argument(
        '--project-name',
        type=str,
        default=None,
        help='override project name, which otherwise would be the name of the directory where command is executed in',
    )

    group_build = dist_parser.add_mutually_exclusive_group()
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

    if dist_parser.prog != 'grizzly-cli dist':  # pragma: no cover
        dist_parser.prog = 'grizzly-cli dist'

    sub_parser = dist_parser.add_subparsers(dest='subcommand')

    build_create_parser(sub_parser)
    clean_create_parser(sub_parser)
    run_create_parser(sub_parser, parent='dist')


def distributed(args: Arguments) -> int:
    if args.subcommand == 'run':
        return run(args, distributed_run)
    elif args.subcommand == 'build':
        return do_build(args)
    elif args.subcommand == 'clean':
        return do_clean(args)
    else:
        raise ValueError(f'unknown subcommand {args.subcommand}')


def distributed_run(args: Arguments, environ: Dict[str, Any], run_arguments: Dict[str, List[str]]) -> int:
    suffix = '' if args.id is None else f'-{args.id}'
    tag = getuser()

    if args.project_name is None:
        project_name = PROJECT_NAME
    else:
        project_name = args.project_name

    # default locust project
    compose_args: List[str] = [
        '-p', f'{project_name}{suffix}-{tag}',
        '-f', f'{STATIC_CONTEXT}/compose.yaml',
    ]

    if args.file is not None:
        os.environ['GRIZZLY_RUN_FILE'] = args.file

    if args.wait_for_worker is not None:
        os.environ['LOCUST_WAIT_FOR_WORKERS_REPORT_AFTER_RAMP_UP'] = f'{args.wait_for_worker}'

    mtu = get_default_mtu(args)

    if mtu is None and os.environ.get('GRIZZLY_MTU', None) is None:
        print('!! unable to determine MTU, try manually setting GRIZZLY_MTU environment variable if anything other than 1500 is needed')
        mtu = '1500'

    columns, lines = get_terminal_size()

    # set environment variables needed by compose files, when * compose executes
    os.environ['GRIZZLY_MTU'] = cast(str, mtu)
    os.environ['GRIZZLY_EXECUTION_CONTEXT'] = EXECUTION_CONTEXT
    os.environ['GRIZZLY_STATIC_CONTEXT'] = STATIC_CONTEXT
    os.environ['GRIZZLY_MOUNT_CONTEXT'] = MOUNT_CONTEXT
    os.environ['GRIZZLY_PROJECT_NAME'] = project_name
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

    grizzly_mount_context_path = ''

    name_template = '{project}{suffix}-{tag}-{node}-{index}'

    if EXECUTION_CONTEXT != MOUNT_CONTEXT:
        hostname = gethostname()
        output = subprocess.check_output(
            [args.container_system, 'container', 'inspect', '-f', '{{ json .Mounts }}', hostname],
            encoding='utf-8',
        )
        container_mounts = jsonloads(output)
        for container_mount in container_mounts:
            if container_mount['Source'] != MOUNT_CONTEXT:
                continue

            grizzly_mount_context_path = EXECUTION_CONTEXT.replace(container_mount['Destination'], '')[1:]
            break

    os.environ['GRIZZLY_MOUNT_PATH'] = grizzly_mount_context_path

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

        if args.wait_for_worker is not None:
            fd.write(f'LOCUST_WAIT_FOR_WORKERS_REPORT_AFTER_RAMP_UP="{args.wait_for_worker}"'.encode('utf-8'))

        fd.flush()

        os.environ['GRIZZLY_ENVIRONMENT_FILE'] = fd.name

        validate_config = getattr(args, 'validate_config', False)

        compose_command = [
            args.container_system, 'compose',
            *compose_args,
            'config',
        ]

        result = run_command(compose_command, silent=not validate_config)

        if validate_config or result.return_code != 0:
            if result.return_code != 0 and not validate_config:
                print('!! something in the compose project is not valid, check with:')
                argv = sys.argv[:]
                argv.insert(argv.index('dist') + 1, '--validate-config')
                print(f'grizzly-cli {" ".join(argv[1:])}')

            return result.return_code

        if images.get(project_name, {}).get(tag, None) is None or args.force_build or args.build:
            rc = do_build(args)
            if rc != 0:
                print(f'!! failed to build {project_name}, rc={rc}')
                return rc

        compose_scale_argument = ['--scale', f'worker={args.workers}']

        # bring up containers
        compose_command = [
            args.container_system, 'compose',
            *compose_args,
            'up',
            *compose_scale_argument,
            '--remove-orphans',
        ]

        result = run_command(compose_command, verbose=args.verbose)

        try:
            output = subprocess.check_output(
                [
                    args.container_system,
                    'inspect',
                    '-f',
                    '{{ .State.ExitCode }}',
                    name_template.format(
                        project=project_name,
                        suffix=suffix,
                        tag=tag,
                        node='master',
                        index=1,
                    ),
                ],
                encoding='utf-8',
            )
            result.return_code = int(output.strip())
        except:
            result.return_code = 1

        # stop containers
        compose_command = [
            args.container_system, 'compose',
            *compose_args,
            'stop',
        ]

        run_command(compose_command)

        if result.return_code != 0:
            if result.abort_timestamp is not None:
                master_node_name = name_template.format(
                    project=project_name,
                    suffix=suffix,
                    tag=tag,
                    node='master',
                    index=1,
                )

                since_timestamp = result.abort_timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')
                command = [args.container_system, 'container', 'logs', '--since', since_timestamp, master_node_name]

                missed_output = subprocess.check_output(
                    command,
                    encoding='utf-8',
                    shell=False,
                    universal_newlines=True,
                    stderr=subprocess.STDOUT,
                ).split('\n')

                log_file = Path(args.log_file).open('a+') if args.log_file is not None else StringIO()

                try:
                    for line in missed_output:
                        formatted_line = f'{master_node_name}  | {line}'
                        print(formatted_line)
                        log_file.write(f'{formatted_line}\n')
                except:
                    pass
                finally:
                    log_file.close()

            print('\n!! something went wrong, check full container logs with:')
            template = '{container_system} container logs {name_template}'
            print(template.format(
                container_system=args.container_system,
                name_template=name_template.format(
                    project=project_name,
                    suffix=suffix,
                    tag=tag,
                    node='master',
                    index=1,
                ),
            ))

            for worker in range(1, args.workers + 1):
                print(template.format(
                    container_system=args.container_system,
                    name_template=name_template.format(
                        project=project_name,
                        suffix=suffix,
                        tag=tag,
                        node='worker',
                        index=worker,
                    ),
                ))

        return result.return_code
