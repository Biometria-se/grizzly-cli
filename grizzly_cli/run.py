import os
import sys

from typing import List, Dict, Any, cast
from tempfile import NamedTemporaryFile
from getpass import getuser
from shutil import get_terminal_size
from argparse import Namespace as Arguments
from platform import node as get_hostname

from . import EXECUTION_CONTEXT, STATIC_CONTEXT, MOUNT_CONTEXT, PROJECT_NAME
from .utils import (
    find_variable_names_in_questions,
    ask_yes_no, get_input,
    distribution_of_users_per_scenario,
    requirements,
    run_command,
    get_default_mtu,
    list_images,
)
from .build import build


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
    os.environ['GRIZZLY_HEALTH_CHECK_RETRIES'] = str(args.health_retries)
    os.environ['GRIZZLY_HEALTH_CHECK_INTERVAL'] = str(args.health_interval)
    os.environ['GRIZZLY_HEALTH_CHECK_TIMEOUT'] = str(args.health_timeout)
    os.environ['GRIZZLY_IMAGE_REGISTRY'] = getattr(args, 'registry', None) or ''
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
            '--remove-orphans'
        ]

        rc = run_command(compose_command)

        # stop containers
        compose_command = [
            f'{args.container_system}-compose',
            *compose_args,
            'stop',
        ]

        run_command(compose_command)

        if rc != 0:
            print('\n!! something went wrong, check container logs with:')
            print(f'{args.container_system} container logs {PROJECT_NAME}{suffix}-{tag}_master_1')
            for worker in range(1, args.workers + 1):
                print(f'{args.container_system} container logs {PROJECT_NAME}{suffix}-{tag}_worker_{worker}')

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
