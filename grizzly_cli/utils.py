import re
import sys
import subprocess

from typing import Optional, List, Set, Union, Dict, Any, Tuple, Callable, cast
from os import path, environ
from shutil import which, rmtree
from behave.parser import parse_file as feature_file_parser
from argparse import Namespace as Arguments
from json import loads as jsonloads
from functools import wraps
from packaging import version as versioning
from tempfile import mkdtemp
from hashlib import sha1
from math import ceil

import requests

from behave.model import Scenario
from jinja2 import Template

import grizzly_cli


def run_command(command: List[str], env: Optional[Dict[str, str]] = None, silent: bool = False, verbose: bool = False) -> int:
    if env is None:
        env = environ.copy()

    if verbose:
        print(f'run_command: {" ".join(command)}')

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
                sys.stdout.flush()

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


def get_docker_compose_version() -> Tuple[int, int, int]:
    output = subprocess.getoutput('docker-compose version')

    version_line = output.splitlines()[0]

    match = re.match(r'.*version [v]?([1-2]\.[0-9]+\.[0-9]+).*$', version_line)

    if match:
        version = cast(Tuple[int, int, int], tuple([int(part) for part in match.group(1).split('.')]))
    else:
        version = (0, 0, 0,)

    return version


def is_docker_compose_v2() -> bool:
    version = get_docker_compose_version()

    return version[0] == 2


def get_dependency_versions() -> Tuple[Tuple[str, Optional[List[str]]], str]:
    grizzly_requirement: Optional[str] = None
    grizzly_requirement_egg: str
    locust_version: Optional[str] = None
    grizzly_version: Optional[str] = None
    grizzly_extras: Optional[List[str]] = None

    project_requirements = path.join(grizzly_cli.EXECUTION_CONTEXT, 'requirements.txt')

    with open(project_requirements, encoding='utf-8') as fd:
        for line in fd.readlines():
            if any([pkg in line for pkg in ['grizzly-loadtester', 'grizzly.git'] if not re.match(r'^([\s]+)?#', line)]):
                grizzly_requirement = line.strip()
                break

    if grizzly_requirement is None:
        print(f'!! unable to find grizzly dependency in {project_requirements}', file=sys.stderr)
        return ('(unknown)', None, ), '(unknown)'

    # check if it's a repo or not
    if grizzly_requirement.startswith('git+'):
        suffix = sha1(grizzly_requirement.encode('utf-8')).hexdigest()
        url, egg_part = grizzly_requirement.rsplit('#', 1)
        url, branch = url.rsplit('@', 1)
        url = url[4:]  # remove git+
        _, grizzly_requirement_egg = egg_part.split('=', 1)

        # extras_requirement normalization
        egg = grizzly_requirement_egg.replace('[', '__').replace(']', '__').replace(',', '_')

        tmp_workspace = mkdtemp(prefix='grizzly-cli-')
        repo_destination = path.join(tmp_workspace, f'{egg}_{suffix}')

        try:
            rc = subprocess.check_call(
                [
                    'git', 'clone', '--filter=blob:none', '-q',
                    url,
                    repo_destination
                ],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            if rc != 0:
                print(f'!! unable to clone git repo {url}', file=sys.stderr)
                raise RuntimeError()  # abort

            active_branch = branch

            try:
                active_branch = subprocess.check_output(
                    ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                    cwd=repo_destination,
                    shell=False,
                    universal_newlines=True,
                ).strip()
                rc = 0
            except subprocess.CalledProcessError as cpe:
                rc = cpe.returncode

            if rc != 0:
                print(f'!! unable to check branch name of HEAD in git repo {url}', file=sys.stderr)
                raise RuntimeError()  # abort

            if active_branch != branch:
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
                    print(f'!! unable to checkout branch {branch} from git repo {url}', file=sys.stderr)
                    raise RuntimeError()  # abort

            if not path.exists(path.join(repo_destination, 'pyproject.toml')):
                with open(path.join(repo_destination, 'grizzly', '__init__.py'), encoding='utf-8') as fd:
                    version_raw = [line.strip() for line in fd.readlines() if line.strip().startswith('__version__ =')]

                if len(version_raw) != 1:
                    print(f'!! unable to find "__version__" declaration in grizzly/__init__.py from {url}', file=sys.stderr)
                    raise RuntimeError()  # abort

                _, grizzly_version, _ = version_raw[-1].split("'")
            else:
                with open(path.join(repo_destination, 'setup.cfg'), encoding='utf-8') as fd:
                    version_raw = [line.strip() for line in fd.readlines() if line.strip().startswith('version = ')]

                if len(version_raw) != 1:
                    print(f'!! unable to find "version" declaration in setup.cfg from {url}', file=sys.stderr)
                    raise RuntimeError()  # abort

                _, grizzly_version = version_raw[-1].split(' = ')

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

            grizzly_requirement_egg = grizzly_requirement

            # get grizzly version used in requirements.txt
            if re.match(r'^grizzly-loadtester(\[[^\]]*\])?$', grizzly_requirement):  # latest
                grizzly_version = pypi.get('info', {}).get('version', None)
            else:
                available_versions = [versioning.parse(available_version) for available_version in pypi.get('releases', {}).keys()]
                conditions: List[Callable[[versioning.Version], bool]] = []

                match = re.match(r'^(grizzly-loadtester(\[[^\]]*\])?)(.*?)$', grizzly_requirement)

                if match:
                    grizzly_requirement_egg = match.group(1)
                    condition_expression = match.group(3)

                    for condition in condition_expression.split(',', 1):
                        version_string = re.sub(r'^[^0-9]{1,2}', '', condition)
                        condition_version = versioning.parse(version_string)

                        if not isinstance(condition_version, versioning.Version):
                            print(f'!! {condition} is a {condition_version.__class__.__name__}, expected Version', file=sys.stderr)
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
                        print(f'!! {str(available_version)} is a {available_version.__class__.__name__}, expected Version', file=sys.stderr)
                        break

                    if len(conditions) > 0 and all([compare(available_version) for compare in conditions]):
                        matched_version = available_version

                if matched_version is None:
                    print(f'!! could not resolve {grizzly_requirement} to one specific version available at pypi', file=sys.stderr)
                else:
                    grizzly_version = str(matched_version)

            if grizzly_version is not None:
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
    else:
        match = re.match(r'^grizzly-loadtester\[([^\]]*)\]$', grizzly_requirement_egg)

        if match:
            grizzly_extras = [extra.strip() for extra in match.group(1).split(',')]
        else:
            grizzly_extras = []

    if locust_version is None:
        locust_version = '(unknown)'

    return (grizzly_version, grizzly_extras, ), locust_version


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


def requirements(execution_context: str) -> Callable[[Callable[..., int]], Callable[..., int]]:
    def wrapper(func: Callable[..., int]) -> Callable[..., int]:
        @wraps(func)
        def _wrapper(*args: Tuple[Any, ...], **kwargs: Dict[str, Any]) -> int:
            requirements_file = path.join(getattr(func, '__value__'), 'requirements.txt')
            if not path.exists(requirements_file):
                with open(requirements_file, 'w+') as fd:
                    fd.write('grizzly-loadtester\n')

                print('!! created a default requirements.txt with one dependency:')
                print('grizzly-loadtester\n')

            return func(*args, **kwargs)

        # a bit ugly, but needed for testability
        setattr(func, '__value__', execution_context)
        setattr(_wrapper, '__wrapped__', func)

        return _wrapper

    return wrapper


def get_distributed_system() -> Optional[str]:
    if which('docker') is not None:
        container_system = 'docker'
    elif which('podman') is not None:
        container_system = 'podman'
        print('!! podman might not work due to buildah missing support for `RUN --mount=type=ssh`: https://github.com/containers/buildah/issues/2835')
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
        grizzly_cli.SCENARIOS.append(scenario)


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
        index: int
        identifier: str
        user: Optional[str]
        weight: float
        iterations: int
        user_count: int

        def __init__(
            self,
            name: str,
            index: int,
            weight: Optional[float] = None,
            user: Optional[str] = None,
            iterations: Optional[int] = None,
            user_count: Optional[int] = None,
        ) -> None:
            self.name = name
            self.index = index
            self.user = user
            self.iterations = iterations or 1
            self.weight = weight or 1.0
            self.identifier = f'{index:03}'
            self.user_count = user_count or 0

    distribution: Dict[str, ScenarioProperties] = {}
    variables = {key.replace('TESTDATA_VARIABLE_', ''): _guess_datatype(value) for key, value in environ.items() if key.startswith('TESTDATA_VARIABLE_')}

    def _pre_populate_scenario(scenario: Scenario, index: int) -> None:
        if scenario.name not in distribution:
            distribution[scenario.name] = ScenarioProperties(
                name=scenario.name,
                index=index,
                user=None,
                weight=None,
                iterations=None,
            )

    scenario_user_count = 0

    for index, scenario in enumerate(grizzly_cli.SCENARIOS):
        if len(scenario.steps) < 1:
            raise ValueError(f'{scenario.name} does not have any steps')

        _pre_populate_scenario(scenario, index=index + 1)

        if index == 0:  # background_steps is only processed for first scenario in grizzly
            for step in scenario.background_steps or []:
                if (step.name.endswith(' users') or step.name.endswith(' user')) and step.keyword == 'Given':
                    match = re.match(r'"([^"]*)" user(s)?', step.name)
                    if match:
                        scenario_user_count = int(round(float(Template(match.group(1)).render(**variables)), 0))

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

    scenario_count = len(distribution.keys())
    if scenario_count > scenario_user_count:
        raise ValueError(f'grizzly needs at least {scenario_count} users to run this feature')

    total_weight = 0
    total_iterations = 0
    for scenario in distribution.values():
        if scenario.user is None:
            raise ValueError(f'{scenario.name} does not have a user type')

        total_weight += scenario.weight
        total_iterations += scenario.iterations

    for scenario in distribution.values():
        scenario.user_count = ceil(scenario_user_count * (scenario.weight / total_weight))

    # smooth assigned user count based on weight, so that the sum of scenario.user_count == total_user_count
    total_user_count = sum([scenario.user_count for scenario in distribution.values()])
    user_overflow = total_user_count - scenario_user_count

    while user_overflow > 0:
        for scenario in dict(sorted(distribution.items(), key=lambda d: d[1].user_count, reverse=True)).values():
            if scenario.user_count <= 1:
                continue

            scenario.user_count -= 1
            user_overflow -= 1

            if user_overflow < 1:
                break

    for scenario in distribution.values():
        if scenario.iterations < scenario.user_count:
            raise ValueError(f'{scenario.name} will have {scenario.user_count} users to run {scenario.iterations} iterations, increase iterations or lower user count')

    def print_table_lines(max_length_iterations: int, max_length_users: int, max_length_description: int) -> None:
        sys.stdout.write('-' * 5)
        sys.stdout.write('-|-')
        sys.stdout.write('-' * 6)
        sys.stdout.write('|-')
        sys.stdout.write('-' * max_length_iterations)
        sys.stdout.write('|-')
        sys.stdout.write('-' * max_length_users)
        sys.stdout.write('|-')
        sys.stdout.write('-' * max_length_description)
        sys.stdout.write('-|\n')

    rows: List[str] = []
    max_length_description = len('description')
    max_length_iterations = len('#iter')
    max_length_users = len('#user')

    print(f'\nfeature file {args.file} will execute in total {total_iterations} iterations\n')

    for scenario in distribution.values():
        max_length_description = max(len(scenario.name), max_length_description)
        max_length_iterations = max(len(str(scenario.iterations)), max_length_iterations)
        max_length_users = max(len(str(scenario.user_count)), max_length_users)

    for scenario in distribution.values():
        row = '{:5}   {:>6.1f}  {:>{}}  {:>{}}  {}'.format(
            scenario.identifier,
            scenario.weight,
            scenario.iterations,
            max_length_iterations,
            scenario.user_count,
            max_length_users,
            scenario.name,
        )
        rows.append(row)

    print('each scenario will execute accordingly:\n')
    print('{:5}   {:>6}  {:>{}}  {:>{}}  {}'.format(
        'ident',
        'weight',
        '#iter', max_length_iterations,
        '#user', max_length_users,
        'description',
    ))
    print_table_lines(max_length_iterations, max_length_users, max_length_description)
    for row in rows:
        print(row)
    print_table_lines(max_length_iterations, max_length_users, max_length_description)

    print('')

    if not args.yes:
        ask_yes_no('continue?')
