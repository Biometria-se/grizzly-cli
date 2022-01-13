import os
import sys
import argparse
import re

from typing import List, Set, Dict, Any, Optional, Union, Tuple, Generator, cast
from pathlib import Path
from shutil import which
from tempfile import NamedTemporaryFile
from getpass import getuser
from platform import node as get_hostname
from hashlib import sha1 as sha1_hash
from operator import attrgetter

from behave.model import Scenario
from roundrobin import smooth
from jinja2 import Template

from . import SCENARIOS, EXECUTION_CONTEXT, STATIC_CONTEXT, MOUNT_CONTEXT, PROJECT_NAME
from . import GrizzlyCliParser, run_command, list_images, get_default_mtu, parse_feature_file
from .build import main as build


def _get_distributed_system() -> Optional[str]:
    if which('podman') is not None:
        container_system = 'podman'
        print('!! podman might not work due to buildah missing support for `RUN --mount=type=ssh`: https://github.com/containers/buildah/issues/2835')
    elif which('docker') is not None:
        container_system = 'docker'
    else:
        print(f'neither "podman" nor "docker" not found in PATH')
        return None

    if which(f'{container_system}-compose') is None:
        print(f'"{container_system}-compose" not found in PATH')
        return None

    return container_system


def _parse_arguments() -> argparse.Namespace:
    parser = GrizzlyCliParser(description='Start grizzy load test')

    group_runner = parser.add_mutually_exclusive_group()

    group_runner.add_argument(
        '-m', '--mode',
        type=str,
        choices=['guess', 'feature'],
        required=False,
        default='guess',
        help=argparse.SUPPRESS,
    )

    group_runner.add_argument(
        'file',
        nargs='?',
    )

    group = parser.add_mutually_exclusive_group()

    group.add_argument(
        '--local',
        action='store_true',
        default=None,
        required=False,
        help='Force running local instead of distributed',
    )

    group.add_argument(
        '--workers',
        type=int,
        required=False,
        default=1,
        help='Number of worker containers to start',
    )

    group_build = parser.add_mutually_exclusive_group()

    group_build.add_argument(
        '--force-build',
        action='store_true',
        required=False,
        help='Force rebuild the grizzly projects container image (no cache)',
    )

    group_build.add_argument(
        '--build',
        action='store_true',
        required=False,
        help='Rebuild the grizzly projects container images (with cache)',
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        required=False,
        help='Verbose output from runners',
    )

    parser.add_argument(
        '--container-system',
        type=str,
        choices=['podman', 'docker', None],
        required=False,
        default=None,
        help=argparse.SUPPRESS,
    )

    parser.add_argument(
        '-T', '--testdata-variable',
        action='append',
        type=str,
        required=False,
        help='Testdata variables',
    )

    parser.add_argument(
        '-y', '--yes',
        action='store_true',
        default=False,
        required=False,
        help='Answer yes on any questions',
    )

    parser.add_argument(
        '-c', '--config-file',
        type=str,
        required=False,
        default=None,
        help='Configuration file with environment specific information',
    )

    args = parser.parse_args()

    if args.local and args.force_build:
        parser.error('argument --force-build: not allowed with argument --local')

    if args.local and args.build:
        parser.error('argument --build: not allowed with argument --local')

    if args.file is None:
        feature_files = len(list(Path(os.path.join(EXECUTION_CONTEXT, 'features')).glob('*.feature')))

        if args.mode == 'guess':
            if feature_files > 0:
                if feature_files > 1:
                    parser.error_no_help(f'could not guess which of {feature_files} should execute, please specify')
                args.mode = 'feature'
            else:
                parser.error_no_help(f"could not guess since there are no features files in '{EXECUTION_CONTEXT}'")
        elif args.mode == 'feature':
            if feature_files < 1:
                parser.error_no_help(f"mode '{args.mode}' requires at least one feature file in '{EXECUTION_CONTEXT}/features'")
            elif feature_files > 1:
                parser.error_no_help(f'could not guess which of {feature_files} should execute, please specify')
    else:
        if args.file.endswith('.feature'):
            args.mode = 'feature'
        else:
            parser.error_no_help(f'{args.file} is not a python nor a feature file')

        if not os.path.exists(os.path.join(EXECUTION_CONTEXT, args.file)):
            parser.error_no_help(f'{args.file} does not exist')

    args.container_system = _get_distributed_system()
    if args.local is None:
        args.local = args.container_system is None

    if not args.local and args.container_system is None:
        parser.error_no_help(f"cannot run distributed")
    elif not os.path.exists(os.path.join(EXECUTION_CONTEXT, 'requirements.txt')):
            parser.error_no_help(f'there is no requirements.txt in {EXECUTION_CONTEXT}, building of container image not possible')

    if args.local and args.mode == 'feature' and which('behave') is None:
        parser.error_no_help("'behave' not found in PATH, needed when running local mode")

    if args.testdata_variable is not None:
        for variable in args.testdata_variable:
            try:
                [name, value] = variable.split('=', 1)
                os.environ[f'TESTDATA_VARIABLE_{name}'] = value
            except ValueError:
                parser.error_no_help(f'-T/--testdata-variable needs to be in the format NAME=VALUE')

    return args


def _find_variable_names_in_questions(file: Optional[str]) -> List[str]:
    unique_variables: Set[str] = set()

    parse_feature_file(file)

    for scenario in SCENARIOS:
        for step in scenario.steps + scenario.background.steps or []:
            if not step.name.startswith('ask for value of variable'):
                continue

            match = re.match(r'ask for value of variable "([^"]*)"', step.name)

            if not match:
                raise ValueError(f'could not find variable name in "{step.name}"')

            unique_variables.add(match.group(1))

    variables = list(unique_variables)
    variables.sort()

    return variables


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

    print(f'\nFeature file {args.file} will execute in total {total_iterations} iterations\n')

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

    print('Each scenario will execute accordingly:\n')
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

    print('Timeline of user scheduling will look as following:')
    print('\n'.join(formatted_timeline))

    print('')

    if not args.yes:
        _ask_yes_no('Continue?')


def _run_distributed(args: argparse.Namespace, environ: Dict[str, Any], run_arguments: Dict[str, List[str]]) -> int:
    tag = getuser()

    # default locust project
    compose_args: List[str] = [
        '-p', f'{tag}-{PROJECT_NAME}',
        '-f', f'{STATIC_CONTEXT}/compose.yaml',
    ]

    if args.file is not None:
        os.environ['GRIZZLY_RUN_FILE'] = args.file

    mtu = get_default_mtu(args)

    if mtu is None and os.environ.get('GRIZZLY_MTU', None) is None:
        print('!! unable determine MTU, try manually setting GRIZZLY_MTU environment variable if anything other than 1500 is needed')
        mtu = '1500'

    # set environment variables needed by compose files, when *-compose executes
    os.environ['GRIZZLY_MTU'] = cast(str, mtu)
    os.environ['GRIZZLY_EXECUTION_CONTEXT'] = EXECUTION_CONTEXT
    os.environ['GRIZZLY_STATIC_CONTEXT'] = STATIC_CONTEXT
    os.environ['GRIZZLY_MOUNT_CONTEXT'] = MOUNT_CONTEXT
    os.environ['GRIZZLY_PROJECT_NAME'] = PROJECT_NAME
    os.environ['GRIZZLY_USER_TAG'] = tag
    os.environ['GRIZZLY_EXPECTED_WORKERS'] = str(args.workers)

    if len(run_arguments['master']) > 0:
        os.environ['GRIZZLY_MASTER_RUN_ARGS'] = ' '.join(run_arguments['master'])

    if len(run_arguments['worker']) > 0:
        os.environ['GRIZZLY_WORKER_RUN_ARGS'] = ' '.join(run_arguments['worker'])

    if len(run_arguments['common']) > 0:
        os.environ['GRIZZLY_COMMON_RUN_ARGS'] = ' '.join(run_arguments['common'])

    # check if we need to build image
    images = list_images(args)

    if PROJECT_NAME not in images or args.force_build or args.build:
        rc = build(args)
        if rc != 0:
            print(f'!! failed to build {PROJECT_NAME}, rc={rc}')
            return rc

    # file will be deleted when conContainertext exits
    with NamedTemporaryFile() as fd:
        if len(environ) > 0:
            for key, value in environ.items():
                if key == 'GRIZZLY_CONFIGURATION_FILE':
                    value = value.replace(EXECUTION_CONTEXT, MOUNT_CONTEXT).replace(MOUNT_CONTEXT, '/srv/grizzly')

                fd.write(f'{key}={value}\n'.encode('utf-8'))

        fd.flush()

        os.environ['GRIZZLY_ENVIRONMENT_FILE'] = fd.name

        compose_scale_argument = ['--scale', f'worker={args.workers}']

        compose_command = [
            f'{args.container_system}-compose',
            *compose_args,
            'up',
            *compose_scale_argument,
            '--remove-orphans'
        ]

        rc = run_command(compose_command)

        # get logs if start failed
        if rc != 0:
            tail = os.environ.get('GRIZZLY_LOG_LINES', '10')
            compose_command = [
                f'{args.container_system}-compose',
                *compose_args,
                'logs',
                f'--tail={tail}',
                '--no-log-prefix',
                'master',
            ]
            run_command(compose_command)

        compose_command = [
            f'{args.container_system}-compose',
            *compose_args,
            'stop',
        ]

        run_command(compose_command)

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

    if len(run_arguments['master']) > 0 or len(run_arguments['worker']) > 0 or len(run_arguments['common']) > 0:
        command += run_arguments['master'] + run_arguments['worker'] + run_arguments['common']

    return run_command(command)


def _ask_yes_no(question: str) -> None:
    answer = 'undefined'
    while answer.lower() not in ['y', 'n']:
        if answer != 'undefined':
            print('You must answer y (yes) or n (no)')
        answer = input(f'{question} [y/n]: ').strip()

        if answer == 'n':
            raise KeyboardInterrupt()


def main() -> int:
    try:
        args = _parse_arguments()

        # always set hostname of host where grizzly-cli was executed, could be useful
        environ: Dict[str, Any] = {
            'GRIZZLY_CLI_HOST': get_hostname(),
            'GRIZZLY_EXECUTION_CONTEXT': EXECUTION_CONTEXT,
            'GRIZZLY_MOUNT_CONTEXT': MOUNT_CONTEXT,
        }

        if args.mode == 'feature':
            # make sure the user want to run all feature files in project
            if args.file is None:
                feature_files = list(Path(os.path.join(EXECUTION_CONTEXT, 'features')).glob('*.feature'))
                if len(feature_files) > 1:
                    print('\n'.join([str(feature) for feature in feature_files]))
                    _ask_yes_no(f'Run the these {len(feature_files)} feature files')

            variables = _find_variable_names_in_questions(args.file)
            questions = len(variables)
            manual_input = False

            if questions > 0:
                print(f'Feature file requires values for {questions} variables')

                for variable in sorted(variables):
                    name = f'TESTDATA_VARIABLE_{variable}'
                    value = os.environ.get(name, '')
                    while len(value) < 1:
                        value = input(f'Initial value for "{variable}": ').strip()
                        manual_input = True

                    environ[name] = value

                print('The following values was provided:')
                for key, value in environ.items():
                    if not key.startswith('TESTDATA_VARIABLE_'):
                        continue
                    print(f'{key.replace("TESTDATA_VARIABLE_", "")} = {value}')

                if manual_input:
                    _ask_yes_no('Continue?')

            if args.config_file is not None:
                config_file = os.path.realpath(args.config_file)
                environ['GRIZZLY_CONFIGURATION_FILE'] = config_file

            _distribution_of_users_per_scenario(args, environ)

        if not args.local:
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
    except (KeyboardInterrupt, ValueError) as e:
        print('')
        if isinstance(e, ValueError):
            print(str(e))

        print('\n!! Aborted grizzly-cli')
        return 1


if __name__ == '__main__':
    sys.exit(main())
