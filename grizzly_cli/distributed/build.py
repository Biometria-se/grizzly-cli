import os

from typing import List, cast
from argparse import SUPPRESS, Namespace as Arguments
from getpass import getuser
from socket import gethostbyname, gaierror

from ..utils import get_dependency_versions, requirements, run_command
from ..argparse import ArgumentSubParser
from .. import EXECUTION_CONTEXT, PROJECT_NAME, STATIC_CONTEXT


def create_parser(sub_parser: ArgumentSubParser) -> None:
    # grizzly-cli dist build ...
    build_parser = sub_parser.add_parser('build', description=(
        'build grizzly compose project container image before running test. if worker nodes runs on different physical '
        'computers, it is mandatory to build the images before hand and push to a registry.'
        '\n\n'
        'if image includes IBM MQ native dependencies, the build time increases due to download times. it is possible '
        'to self-host the archive and override the download host with environment variable `IBM_MQ_LIB_HOST`.'
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
    build_parser.add_argument(
        '--no-progress',
        action='store_true',
        default=False,
        required=False,
        help='do not show a progress spinner while building',
    )
    build_parser.add_argument(
        '--verbose',
        action='store_true',
        default=False,
        required=False,
        help='show more information',
    )
    # <!-- used during development, hide from help
    build_parser.add_argument(
        '--local-install',
        nargs='?',
        const=True,
        default=False,
        help=SUPPRESS,
    )
    # used during development, hide from help -->

    if build_parser.prog != 'grizzly-cli dist build':  # pragma: no cover
        build_parser.prog = 'grizzly-cli dist build'


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
    local_install = getattr(args, 'local_install', False)

    if local_install:
        install_type = 'local'
    else:
        install_type = 'remote'

    (_, grizzly_extras, ), _ = get_dependency_versions(local_install)

    if grizzly_extras is not None and 'mq' in grizzly_extras:
        grizzly_extra = 'mq'
    else:
        grizzly_extra = 'base'

    extra_args: List[str] = []

    ibm_mq_lib_host = os.environ.get('IBM_MQ_LIB_HOST', None)
    if ibm_mq_lib_host is not None:
        extra_args += ['--build-arg', f'IBM_MQ_LIB_HOST={ibm_mq_lib_host}']

        if 'host.docker.internal' in ibm_mq_lib_host:
            try:
                host_docker_internal = gethostbyname('host.docker.internal')
            except gaierror:
                host_docker_internal = 'host-gateway'

            extra_args += ['--add-host', f'host.docker.internal:{host_docker_internal}']

    ibm_mq_lib = os.environ.get('IBM_MQ_LIB', None)
    if ibm_mq_lib is not None:
        extra_args += ['--build-arg', f'IBM_MQ_LIB={ibm_mq_lib}']

    return [
        f'{args.container_system}',
        'image',
        'build',
        '--ssh',
        'default',
        '--build-arg', f'GRIZZLY_EXTRA={grizzly_extra}',
        '--build-arg', f'GRIZZLY_INSTALL_TYPE={install_type}',
        '--build-arg', f'GRIZZLY_UID={getuid()}',
        '--build-arg', f'GRIZZLY_GID={getgid()}',
        *extra_args,
        '-f', containerfile,
        '-t', tag,
        context
    ]


@requirements(EXECUTION_CONTEXT)
def build(args: Arguments) -> int:
    tag = getuser()

    if args.project_name is None:
        image_name = f'{PROJECT_NAME}:{tag}'
    else:
        image_name = f'{args.project_name}:{tag}'

    build_command = _create_build_command(
        args,
        f'{STATIC_CONTEXT}{os.path.sep}Containerfile',
        image_name,
        EXECUTION_CONTEXT,
    )

    if args.force_build:
        build_command.append('--no-cache')

    # make sure buildkit is used
    build_env = os.environ.copy()
    if args.container_system == 'docker':
        build_env['DOCKER_BUILDKIT'] = '1'

    spinner = 'building' if not getattr(args, 'no_progress', False) else None

    result = run_command(build_command, env=build_env, spinner=spinner, verbose=args.verbose)

    if result.return_code == 0:
        print(f'\nbuilt image {image_name}')

    if getattr(args, 'registry', None) is None or result.return_code != 0:
        return result.return_code

    tag_command = [
        f'{args.container_system}',
        'image',
        'tag',
        image_name,
        f'{args.registry}{image_name}',
    ]

    result = run_command(tag_command, env=build_env, verbose=args.verbose)

    if result.return_code != 0:
        print(f'\n!! failed to tag image {image_name} -> {args.registry}{image_name}')
        return result.return_code
    else:
        print(f'tagged image {image_name} -> {args.registry}{image_name}')

    push_command = [
        f'{args.container_system}',
        'image',
        'push',
        f'{args.registry}{image_name}',
    ]

    spinner = 'pushing' if not args.no_progress else None

    result = run_command(push_command, env=build_env, spinner=spinner, verbose=args.verbose)

    if result.return_code != 0:
        print(f'\n!! failed to push image {args.registry}{image_name}')
    else:
        print(f'pushed image {args.registry}{image_name}')

    return result.return_code
