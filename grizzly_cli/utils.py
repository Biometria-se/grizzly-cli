import re
import sys
import subprocess

from typing import Optional, List, Set, Union, Dict, Any, Tuple, Generator, Callable
from os import path, environ
from shutil import which, rmtree
from behave.parser import parse_file as feature_file_parser
from argparse import Namespace as Arguments
from operator import attrgetter
from hashlib import sha1 as sha1_hash
from json import loads as jsonloads
from functools import wraps
from packaging import version as versioning
from tempfile import mkdtemp
from hashlib import sha1

import requests

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


def get_dependency_versions() -> Tuple[str, str]:
    grizzly_requirement: Optional[str] = None
    locust_version: Optional[str] = None
    grizzly_version: Optional[str] = None

    project_requirements = path.join(grizzly_cli.EXECUTION_CONTEXT, 'requirements.txt')

    with open(project_requirements, encoding='utf-8') as fd:
        for line in fd.readlines():
            if any([pkg in line for pkg in ['grizzly-loadtester', 'grizzly.git'] if not re.match(r'^([\s]+)?#', line)]):
                grizzly_requirement = line.strip()
                break

    if grizzly_requirement is None:
        print(f'!! unable to find grizzly dependency in {project_requirements}', file=sys.stderr)
        return '(unknown)', '(unknown)'

    # check if it's a repo or not
    if grizzly_requirement.startswith('git+'):
        suffix = sha1(grizzly_requirement.encode('utf-8')).hexdigest()
        url, egg_part = grizzly_requirement.rsplit('#', 1)
        url, branch = url.rsplit('@', 1)
        url = url[4:]  # remove git+
        _, egg = egg_part.split('=', 1)

        # extras_requirement normalization
        egg = egg.replace('[', '__').replace(']', '__')

        tmp_workspace = mkdtemp(prefix='grizzly-cli-')
        repo_destination = path.join(tmp_workspace, f'{egg}_{suffix}')

        try:
            rc: int = 0

            rc += subprocess.check_call(
                [
                    'git', 'clone', '--filter=blob:none', '-q',
                    url,
                    repo_destination
                ],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            rc += subprocess.check_call(
                [
                    'git', 'checkout',
                    '-b', branch,
                    '--track', f'origin/{branch}',
                ],
                cwd=repo_destination,
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            if rc != 0:
                print(f'!! unable to get git repo {url} and branch {branch}', file=sys.stderr)
                raise RuntimeError()  # abort

            with open(path.join(repo_destination, 'grizzly', '__init__.py'), encoding='utf-8') as fd:
                version_raw = [line.strip() for line in fd.readlines() if line.strip().startswith('__version__ =')]

            if len(version_raw) != 1:
                print(f'!! unable to find "__version__" declaration in grizzly/__init__.py from {url}', file=sys.stderr)
                raise RuntimeError()  # abort

            _, grizzly_version, _ = version_raw[-1].split("'")

            if grizzly_version == '0.0.0':
                grizzly_version = '(development)'

            with open(path.join(repo_destination, 'requirements.txt'), encoding='utf-8') as fd:
                version_raw = [line.strip() for line in fd.readlines() if line.strip().startswith('locust')]

            if len(version_raw) != 1:
                print(f'!! unable to find "locust" dependency in requirements.txt from {url}', file=sys.stderr)
                raise RuntimeError()  # abort

            match = re.match(r'^locust.{2}([^\s]+)\s+', version_raw[-1])

            if not match:
                print(f'!! unable to find locust version in "{version_raw[-1].strip()}" specified in requirements.txt from {url}', file=sys.stderr)
            else:
                locust_version = match.group(1)
        except RuntimeError:
            pass
        finally:
            rmtree(tmp_workspace)
    else:
        response = requests.get(
            'https://pypi.org/pypi/grizzly-loadtester/json'
        )

        if response.status_code != 200:
            print(f'!! unable to get grizzly package information from {response.url} ({response.status_code})', file=sys.stderr)
        else:
            pypi = jsonloads(response.text)

            # get grizzly version used in requirements.txt
            if re.match(r'^grizzly-loadtester(\[[^\]]\])?$', grizzly_requirement):  # latest
                grizzly_version = pypi.get('info', {}).get('version', None)
            else:
                available_versions = [versioning.parse(available_version) for available_version in pypi.get('releases', {}).keys()]
                conditions: List[Callable[[versioning.Version], bool]] = []

                for condition in grizzly_requirement.replace('grizzly-loadtester', '').split(',', 1):
                    condition_version = versioning.parse(re.sub(r'[^0-9\.]', '', condition))

                    if not isinstance(condition_version, versioning.Version):
                        print(f'!! {str(condition_version)} is a {condition_version.__class__.__name__}, expected Version', file=sys.stderr)
                        break

                    if '>' in condition:
                        compare = condition_version.__le__ if '=' in condition else condition_version.__lt__
                    elif '<' in condition:
                        compare = condition_version.__ge__ if '=' in condition else condition_version.__gt__
                    else:
                        compare = condition_version.__eq__

                    conditions.append(compare)

                matched_version = None

                for available_version in available_versions:
                    if not isinstance(available_version, versioning.Version):
                        print(f'{str(condition_version)} is a {condition_version.__class__.__name__}, expected Version', file=sys.stderr)
                        break

                    if all([compare(available_version) for compare in conditions]):
                        matched_version = available_version

                if matched_version is None:
                    print(f'!! could not resolve {grizzly_requirement} to one specific version available at pypi', file=sys.stderr)
                else:
                    grizzly_version = str(matched_version)

            # get version from pypi, to be able to get locust version
            response = requests.get(
                f'https://pypi.org/pypi/grizzly-loadtester/{grizzly_version}/json'
            )

            if response.status_code != 200:
                print(f'!! unable to get grizzly {grizzly_version} package information from {response.url} ({response.status_code})', file=sys.stderr)
            else:
                release_info = jsonloads(response.text)

                for requires_dist in release_info.get('info', {}).get('requires_dist', []):
                    if not requires_dist.startswith('locust'):
                        continue

                    match = re.match(r'^locust \([^0-9]{2}(.+)\)$', requires_dist.strip())

                    if not match:
                        print(f'!! unable to find locust version in "{requires_dist.strip()}" specified in pypi for grizzly-loadtester {grizzly_version}', file=sys.stderr)
                        locust_version = '(unknown)'
                        break

                    locust_version = match.group(1)
                    break

                if locust_version is None:
                    print(f'!! could not find "locust" in requires_dist information for grizzly-loadtester {grizzly_version}', file=sys.stderr)

    if grizzly_version is None:
        grizzly_version = '(unknown)'

    if locust_version is None:
        locust_version = '(unknown)'

    return grizzly_version, locust_version


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


def requirements(execution_context: str) -> Callable[[Callable[[Arguments], int]], Callable[[Arguments], int]]:
    def wrapper(func: Callable[[Arguments], int]) -> Callable[[Arguments], int]:
        @wraps(func)
        def _wrapper(arguments: Arguments) -> int:
            requirements_file = path.join(getattr(func, '__value__'), 'requirements.txt')
            if not path.exists(requirements_file):
                with open(requirements_file, 'w+') as fd:
                    fd.write('grizzly-loadtester\n')

                print('!! created a default requirements.txt with one dependency:')
                print('grizzly-loadtester\n')

            return func(arguments)

        # a bit ugly, but needed for testability
        setattr(func, '__value__', execution_context)
        setattr(_wrapper, '__wrapped__', func)

        return _wrapper

    return wrapper


def get_distributed_system() -> Optional[str]:
    if which('podman') is not None:
        container_system = 'podman'
        print('!! podman might not work due to buildah missing support for `RUN --mount=type=ssh`: https://github.com/containers/buildah/issues/2835')
    elif which('docker') is not None:
        container_system = 'docker'
    else:
        print('neither "podman" nor "docker" found in PATH')
        return None

    if which(f'{container_system}-compose') is None:
        print(f'"{container_system}-compose" not found in PATH')
        return None

    return container_system


def get_input(text: str) -> str:  # pragma: no cover
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
            weight: Optional[float] = None,
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
