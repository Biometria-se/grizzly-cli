import os

from typing import List, cast
from argparse import Namespace as Arguments
from getpass import getuser

from . import EXECUTION_CONTEXT, PROJECT_NAME, STATIC_CONTEXT, run_command


def getuid() -> int:
    if os.name == 'nt' or not hasattr(os, 'getuid'):
        return 1000
    else:
        return cast(int, getattr(os, 'getuid')())


def getgid() -> int:
    if os.name == 'nt' or not hasattr(os, 'getgid'):
        return 1000
    else:
        return cast(int, getattr(os, 'getgid')())


def _create_build_command(args: Arguments, containerfile: str, tag: str, context: str) -> List[str]:
    return [
        f'{args.container_system}',
        'image',
        'build',
        '--ssh',
        'default',
        '--build-arg', f'GRIZZLY_UID={getuid()}',
        '--build-arg', f'GRIZZLY_GID={getgid()}',
        '-f', containerfile,
        '-t', tag,
        context
    ]


def main(args: Arguments) -> int:
    tag = getuser()

    build_command = _create_build_command(
        args,
        f'{STATIC_CONTEXT}/Containerfile',
        f'{PROJECT_NAME}:{tag}',
        EXECUTION_CONTEXT,
    )

    if args.force_build:
        build_command.append('--no-cache')

    # make sure buildkit is used
    build_env = os.environ.copy()
    if args.container_system == 'docker':
        build_env['DOCKER_BUILDKIT'] = '1'

    return run_command(build_command, env=build_env)
