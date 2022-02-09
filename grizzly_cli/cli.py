import os
import sys
import argparse
import re

from typing import List, Set, Dict, Any, Optional, Union, Tuple, Generator, cast
from shutil import which
from tempfile import NamedTemporaryFile
from getpass import getuser
from platform import node as get_hostname
from hashlib import sha1 as sha1_hash
from operator import attrgetter
from shutil import get_terminal_size

from behave.model import Scenario
from roundrobin import smooth
from jinja2 import Template

from .argparse.bashcompletion import BashCompletionTypes

from . import SCENARIOS, EXECUTION_CONTEXT, STATIC_CONTEXT, MOUNT_CONTEXT, PROJECT_NAME, __version__
from . import run_command, list_images, get_default_mtu, parse_feature_file
from .build import main as build
from .argparse import ArgumentParser


def _get_distributed_system() -> Optional[str]:
    if which('podman') is not None:
        container_system = 'podman'
        print('!! podman might not work due to buildah missing support for `RUN --mount=type=ssh`: https://github.com/containers/buildah/issues/2835')
    elif which('docker') is not None:
        container_system = 'docker'
    else:
        print(f'neither "podman" nor "docker" found in PATH')
        return None

    if which(f'{container_system}-compose') is None:
        print(f'"{container_system}-compose" not found in PATH')
        return None

    return container_system

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

    parser.add_argument('--version', action='store_true', help='print version of command line interface, and exit')

    sub_parser = parser.add_subparsers(dest='category')

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

    if build_parser.prog != 'grizzly-cli build':
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

    if run_parser.prog != 'grizzly-cli run':
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

    if run_local_parser.prog != 'grizzly-cli run local':
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

    if run_dist_parser.prog != 'grizzly-cli run dist':
        run_dist_parser.prog = 'grizzly-cli run dist'

    return parser

def _parse_arguments() -> argparse.Namespace:
    parser = _create_parser()
    args = parser.parse_args()

    if args.version:
        print(__version__)
        raise SystemExit(0)

    if args.category is None:
        parser.error('no subcommand specified')

    if getattr(args, 'mode', None) is None and args.category == 'run':
        parser.error(f'no subcommand for {args.category} specified')

    if args.category == 'build' or (args.category == 'run' and args.mode == 'dist'):
        args.container_system = _get_distributed_system()

        if args.container_system is None:
            parser.error_no_help('cannot run distributed')
        elif not os.path.exists(os.path.join(EXECUTION_CONTEXT, 'requirements.txt')):
            parser.error_no_help(f'there is no requirements.txt in {EXECUTION_CONTEXT}, building of container image not possible')

        if args.registry is not None and not args.registry.endswith('/'):
            setattr(args, 'registry', f'{args.registry}/')

    if args.category == 'run':
        if args.mode == 'dist':
            if args.limit_nofile < 10001 and not args.yes:
                print('!! this will cause warning messages from locust later on')
                _ask_yes_no('are you sure you know what you are doing?')
        elif args.mode == 'local':
            if which('behave') is None:
                parser.error_no_help('"behave" not found in PATH, needed when running local mode')

        if args.testdata_variable is not None:
            for variable in args.testdata_variable:
                try:
                    [name, value] = variable.split('=', 1)
                    os.environ[f'TESTDATA_VARIABLE_{name}'] = value
                except ValueError:
                    parser.error_no_help(f'-T/--testdata-variable needs to be in the format NAME=VALUE')
    elif args.category == 'build':
        setattr(args, 'force_build', args.no_cache)
        setattr(args, 'build', not args.no_cache)

    return args


def _find_variable_names_in_questions(file: str) -> List[str]:
    unique_variables: Set[str] = set()

    parse_feature_file(file)

    for scenario in SCENARIOS:
        for step in scenario.steps + scenario.background_steps or []:
            if not step.name.startswith('ask for value of variable'):
                continue

            match = re.match(r'ask for value of variable "([^"]*)"', step.name)

            if not match:
                raise ValueError(f'could not find variable name in "{step.name}"')

            unique_variables.add(match.group(1))

    return sorted(list(unique_variables))


def _distribution_of_users_per_scenario(args: argparse.Namespace, environ: Dict[str, Any]) -> None:
    def _guess_datatype(value: str) -> Union[str, int, float, bool]:
        check_value = value.replace('.', '', 1)

        if check_value[0] == '-':
            check_value = check_value[1:]

        if check_value.isdecimal():
            if float(value) % 1 == 0:
                if value.startswith('0'):
                    return str(value)
                else:
                    return int(float(value))
            else:
                return float(value)
        elif value.lower() in ['true', 'false']:
            return value.lower() == 'true'
        else:
            return value

    class ScenarioProperties:
        name: str
        identifier: str
        user: Optional[str]
        symbol: str
        weight: float
        iterations: int

        def __init__(
            self,
            name: str,
            symbol: str,
            weight: Optional[float]= None,
            user: Optional[str] = None,
            iterations: Optional[int] = None,
        ) -> None:
            self.name = name
            self.symbol = symbol
            self.user = user
            self.iterations = iterations or 1
            self.weight = weight or 1.0
            self.identifier = generate_identifier(name)

    distribution: Dict[str, ScenarioProperties] = {}
    variables = {key.replace('TESTDATA_VARIABLE_', ''): _guess_datatype(value) for key, value in environ.items() if key.startswith('TESTDATA_VARIABLE_')}
    current_symbol = 65  # ASCII decimal for A

    def _pre_populate_scenario(scenario: Scenario) -> None:
        nonlocal current_symbol
        if scenario.name not in distribution:
            distribution[scenario.name] = ScenarioProperties(
                name=scenario.name,
                user=None,
                symbol=chr(current_symbol),
                weight=None,
                iterations=None,
            )
            current_symbol += 1

    def generate_identifier(name: str) -> str:
        return sha1_hash(name.encode('utf-8')).hexdigest()[:8]

    for scenario in sorted(list(SCENARIOS), key=attrgetter('name')):
        if len(scenario.steps) < 1:
            raise ValueError(f'{scenario.name} does not have any steps')

        _pre_populate_scenario(scenario)

        for step in scenario.steps:
            if step.name.startswith('a user of type'):
                match = re.match(r'a user of type "([^"]*)" (with weight "([^"]*)")?.*', step.name)
                if match:
                    distribution[scenario.name].user = match.group(1)
                    distribution[scenario.name].weight = float(match.group(3) or '1.0')
            elif step.name.startswith('repeat for'):
                match = re.match(r'repeat for "([^"]*)" iteration.*', step.name)
                if match:
                    distribution[scenario.name].iterations = int(round(float(Template(match.group(1)).render(**variables)), 0))

    dataset: List[Tuple[str, float]] = [(scenario.name, scenario.weight, ) for scenario in distribution.values()]
    get_weighted_smooth = smooth(dataset)

    for scenario in distribution.values():
        if scenario.user is None:
            raise ValueError(f'{scenario.name} does not have a user type')

    total_iterations = sum([scenario.iterations for scenario in distribution.values()])
    timeline: List[str] = []

    for _ in range(0, total_iterations):
        scenario = get_weighted_smooth()
        symbol = distribution[scenario].symbol
        timeline.append(symbol)

    def chunks(input: List[str], n: int) -> Generator[List[str], None, None]:
        for i in range(0, len(input), n):
            yield input[i:i + n]

    def print_table_lines(length: int) -> None:
        sys.stdout.write('-' * 11)
        sys.stdout.write('|')
        sys.stdout.write('-' * 7)
        sys.stdout.write('|')
        sys.stdout.write('-' * 7)
        sys.stdout.write('|')
        sys.stdout.write('-' * 7)
        sys.stdout.write('|')
        sys.stdout.write('-' * (length + 1))
        sys.stdout.write('|\n')

    rows: List[str] = []
    max_length = len('description')

    print(f'\nfeature file {args.file} will execute in total {total_iterations} iterations\n')

    for scenario in distribution.values():
        row = '{:11} {:^7} {:>7.1f} {:>7} {}'.format(
            scenario.identifier,
            scenario.symbol,
            scenario.weight,
            scenario.iterations,
            scenario.name,
        )
        description_length = len(scenario.name)
        if description_length > max_length:
            max_length = description_length
        rows.append(row)

    print('each scenario will execute accordingly:\n')
    print('{:11} {:7} {:7} {:7} {}'.format('identifier', 'symbol', 'weight', 'iter', 'description'))
    print_table_lines(max_length)
    for row in rows:
        print(row)
    print_table_lines(max_length)

    print('')

    formatted_timeline: List[str] = []

    for chunk in chunks(timeline, 120):
        formatted_timeline.append('{} \\'.format(''.join(chunk)))

    formatted_timeline[-1] = formatted_timeline[-1][:-2]

    if len(formatted_timeline) > 10:
        formatted_timeline = formatted_timeline[:5] + ['...'] + formatted_timeline[-5:]

    print('timeline of user scheduling will look as following:')
    print('\n'.join(formatted_timeline))

    print('')

    if not args.yes:
        _ask_yes_no('continue?')


def _run_distributed(args: argparse.Namespace, environ: Dict[str, Any], run_arguments: Dict[str, List[str]]) -> int:
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
            for worker in range(1, args.workers+1):
                print(f'{args.container_system} container logs {PROJECT_NAME}{suffix}-{tag}_worker_{worker}')

        return rc


def _run_local(args: argparse.Namespace, environ: Dict[str, Any], run_arguments: Dict[str, List[str]]) -> int:
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


def _get_input(text: str) -> str:
    return input(text).strip()

def _ask_yes_no(question: str) -> None:
    answer = 'undefined'
    while answer.lower() not in ['y', 'n']:
        if answer != 'undefined':
            print('you must answer y (yes) or n (no)')
        answer = _get_input(f'{question} [y/n]: ')

        if answer == 'n':
            raise KeyboardInterrupt()


def main() -> int:
    try:
        args = _parse_arguments()

        if args.category == 'run':
            # always set hostname of host where grizzly-cli was executed, could be useful
            environ: Dict[str, Any] = {
                'GRIZZLY_CLI_HOST': get_hostname(),
                'GRIZZLY_EXECUTION_CONTEXT': EXECUTION_CONTEXT,
                'GRIZZLY_MOUNT_CONTEXT': MOUNT_CONTEXT,
            }


            variables = _find_variable_names_in_questions(args.file)
            questions = len(variables)
            manual_input = False

            if questions > 0 and not getattr(args, 'validate_config', False):
                print(f'feature file requires values for {questions} variables')

                for variable in variables:
                    name = f'TESTDATA_VARIABLE_{variable}'
                    value = os.environ.get(name, '')
                    while len(value) < 1:
                        value = _get_input(f'initial value for "{variable}": ')
                        manual_input = True

                    environ[name] = value

                print('the following values was provided:')
                for key, value in environ.items():
                    if not key.startswith('TESTDATA_VARIABLE_'):
                        continue
                    print(f'{key.replace("TESTDATA_VARIABLE_", "")} = {value}')

                if manual_input:
                    _ask_yes_no('continue?')

            if args.environment_file is not None:
                environment_file = os.path.realpath(args.environment_file)
                environ['GRIZZLY_CONFIGURATION_FILE'] = environment_file

            if not getattr(args, 'validate_config', False):
                _distribution_of_users_per_scenario(args, environ)

            if args.mode == 'dist':
                run = _run_distributed
            else:
                run = _run_local

            run_arguments: Dict[str, List[str]] = {
                'master': [],
                'worker': [],
                'common': ['--stop'],
            }

            if args.verbose:
                run_arguments['common'] += ['--verbose', '--no-logcapture', '--no-capture', '--no-capture-stderr']

            return run(args, environ, run_arguments)
        elif args.category == 'build':
            return build(args)
        else:
            raise ValueError(f'unknown subcommand {args.category}')
    except (KeyboardInterrupt, ValueError) as e:
        print('')
        if isinstance(e, ValueError):
            print(str(e))

        print('\n!! aborted grizzly-cli')
        return 1


if __name__ == '__main__':
    sys.exit(main())
