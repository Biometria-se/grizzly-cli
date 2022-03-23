import os

from typing import List, cast
from argparse import Namespace as Arguments
from getpass import getuser

from .utils import requirements, run_command
from .argparse import ArgumentSubParser
from . import EXECUTION_CONTEXT, PROJECT_NAME, STATIC_CONTEXT


def create_parser(sub_parser: ArgumentSubParser) -> None:
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


@requirements(EXECUTION_CONTEXT)
def build(args: Arguments) -> int:
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
