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

    image_name = f'{PROJECT_NAME}:{tag}'

    build_command = _create_build_command(
        args,
        f'{STATIC_CONTEXT}/Containerfile',
        image_name,
        EXECUTION_CONTEXT,
    )

    if args.force_build:
        build_command.append('--no-cache')

    # make sure buildkit is used
    build_env = os.environ.copy()
    if args.container_system == 'docker':
        build_env['DOCKER_BUILDKIT'] = '1'

    rc = run_command(build_command, env=build_env)

    if getattr(args, 'registry', None) is None or rc != 0:
        return rc

    tag_command = [
        f'{args.container_system}',
        'image',
        'tag',
        image_name,
        f'{args.registry}{image_name}',
    ]

    rc = run_command(tag_command, env=build_env)

    if rc != 0:
        print(f'\n!! failed to tag image {image_name} -> {args.registry}{image_name}')
        return rc

    push_command = [
        f'{args.container_system}',
        'image',
        'push',
        f'{args.registry}{image_name}',
    ]

    rc = run_command(push_command, env=build_env)

    if rc != 0:
        print(f'\n!! failed to push image {args.registry}{image_name}')

    return rc
