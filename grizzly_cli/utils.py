import re
import sys
import subprocess

from typing import Optional, List, Set, Union, Dict, Any, Tuple, Generator, Callable
from os import path, environ
from shutil import which
from behave.parser import parse_file as feature_file_parser
from argparse import Namespace as Arguments
from operator import attrgetter
from hashlib import sha1 as sha1_hash
from json import loads as jsonloads

from behave.model import Scenario
from roundrobin import smooth
from jinja2 import Template

import grizzly_cli


def run_command(command: List[str], env: Optional[Dict[str, str]] = None, silent: bool = False) -> int:
    if env is None:
        env = environ.copy()

    process = subprocess.Popen(
        command,
        env=env,
        stderr=subprocess.STDOUT,
        stdout=subprocess.PIPE,
    )

    try:
        while process.poll() is None:
            stdout = process.stdout
            if stdout is None:
                break

            output = stdout.readline()
            if not output:
                break

            if not silent:
                sys.stdout.write(output.decode('utf-8'))

        process.terminate()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            process.kill()
        except Exception:
            pass

    process.wait()

    return process.returncode


def list_images(args: Arguments) -> Dict[str, Any]:
    images: Dict[str, Any] = {}
    output = subprocess.check_output([
        f'{args.container_system}',
        'image',
        'ls',
        '--format',
        '{"name": "{{.Repository}}", "tag": "{{.Tag}}", "size": "{{.Size}}", "created": "{{.CreatedAt}}", "id": "{{.ID}}"}',
    ]).decode('utf-8')

    for line in output.split('\n'):
        if len(line) < 1:
            continue
        image = jsonloads(line)
        name = image['name']
        tag = image['tag']
        del image['name']
        del image['tag']

        version = {tag: image}

        if name not in images:
            images[name] = {}
        images[name].update(version)

    return images


def get_default_mtu(args: Arguments) -> Optional[str]:
    try:
        output = subprocess.check_output([
            f'{args.container_system}',
            'network',
            'inspect',
            'bridge',
            '--format',
            '{{ json .Options }}',
        ]).decode('utf-8')

        line, _ = output.split('\n', 1)
        network_options: Dict[str, str] = jsonloads(line)
        return network_options.get('com.docker.network.driver.mtu', '1500')
    except:
        return None


def requirements_needed(func: Callable[[Arguments], int]) -> Callable[[Arguments], int]:
    requirements_file = path.join(grizzly_cli.EXECUTION_CONTEXT, 'requirements.txt')
    if not path.exists(requirements_file):
        with open(requirements_file, 'w+') as fd:
            fd.write('grizzly-loadtester\n')

        print('!! created a default requirements.txt with one dependency:')
        print('grizzly-loadtester\n')

    return func


def get_distributed_system() -> Optional[str]:
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


def get_input(text: str) -> str:
    return input(text).strip()


def ask_yes_no(question: str) -> None:
    answer = 'undefined'
    while answer.lower() not in ['y', 'n']:
        if answer != 'undefined':
            print('you must answer y (yes) or n (no)')
        answer = get_input(f'{question} [y/n]: ')

        if answer == 'n':
            raise KeyboardInterrupt()


def parse_feature_file(file: str) -> None:
    if len(grizzly_cli.SCENARIOS) > 0:
        return

    feature = feature_file_parser(file)

    for scenario in feature.scenarios:
        print(scenario)
        grizzly_cli.SCENARIOS.add(scenario)

    print(id(grizzly_cli.SCENARIOS))


def find_variable_names_in_questions(file: str) -> List[str]:
    unique_variables: Set[str] = set()

    parse_feature_file(file)

    for scenario in grizzly_cli.SCENARIOS:
        for step in scenario.steps + scenario.background_steps or []:
            if not step.name.startswith('ask for value of variable'):
                continue

            match = re.match(r'ask for value of variable "([^"]*)"', step.name)

            if not match:
                raise ValueError(f'could not find variable name in "{step.name}"')

            unique_variables.add(match.group(1))

    return sorted(list(unique_variables))


def distribution_of_users_per_scenario(args: Arguments, environ: Dict[str, Any]) -> None:
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

    for scenario in sorted(list(grizzly_cli.SCENARIOS), key=attrgetter('name')):
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

    def print_table_lines(max_length_iterations: int, max_length_description: int) -> None:
        sys.stdout.write('-' * 10)
        sys.stdout.write('-|-')
        sys.stdout.write('-' * 6)
        sys.stdout.write('-|-')
        sys.stdout.write('-' * 6)
        sys.stdout.write('|-')
        sys.stdout.write('-' * max_length_iterations)
        sys.stdout.write('|-')
        sys.stdout.write('-' * max_length_description)
        sys.stdout.write('-|\n')

    rows: List[str] = []
    max_length_description = len('description')
    max_length_iterations = len('#')

    print(f'\nfeature file {args.file} will execute in total {total_iterations} iterations\n')

    for scenario in distribution.values():
        description_length = len(scenario.name)
        if description_length > max_length_description:
            max_length_description = description_length

        iterations_length = len(str(scenario.iterations))
        if iterations_length > max_length_iterations:
            max_length_iterations = iterations_length

    for scenario in distribution.values():
        row = '{:10}   {:^6}   {:>6.1f}  {:>{}}  {}'.format(
            scenario.identifier,
            scenario.symbol,
            scenario.weight,
            scenario.iterations,
            max_length_iterations,
            scenario.name,
        )
        rows.append(row)

    print('each scenario will execute accordingly:\n')
    print('{:10}   {:6}   {:>6}  {:>{}}  {}'.format('identifier', 'symbol', 'weight', '#', max_length_iterations, 'description'))
    print_table_lines(max_length_iterations, max_length_description)
    for row in rows:
        print(row)
    print_table_lines(max_length_iterations, max_length_description)

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
        ask_yes_no('continue?')
