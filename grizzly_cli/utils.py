import re
import sys
import subprocess
import signal as psignal
import logging
import logging.config
import stat
import os

from typing import Optional, List, Set, Union, Dict, Any, Tuple, Callable, Type, cast
from types import TracebackType, FrameType
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
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path

import requests
import tomli

from behave.model import Scenario
from jinja2 import Template
from progress.spinner import Spinner

import grizzly_cli


logger = logging.getLogger('grizzly-cli')


class SignalHandler:
    handler: Callable[[int, Optional[FrameType]], None]
    signals: Dict[int, Union[Callable[[int, Optional[FrameType]], Any], int, None]]

    def __init__(self, handler: Callable[[int, Optional[FrameType]], None], signal: int, *signals: int) -> None:
        self.handler = handler
        self.signals = {signal: None}

        if signals is not None and len(signals) > 0:
            for sig in signals:
                self.signals.update({sig: None})

    def __enter__(self) -> None:
        for signal in self.signals.keys():
            self.signals.update({signal: psignal.getsignal(signal)})
            psignal.signal(signal, self.handler)

    def __exit__(self, exc_type: Optional[Type[BaseException]], exc: Optional[BaseException], tb: Optional[TracebackType]) -> bool:
        for signal, handler in self.signals.items():
            psignal.signal(signal, handler)

        return exc is None


@dataclass
class RunCommandResult:
    return_code: int
    abort_timestamp: Optional[datetime] = field(init=False, default=None)
    output: Optional[List[bytes]] = field(init=False, default=None)


def run_command(command: List[str], env: Optional[Dict[str, str]] = None, *, silent: bool = False, verbose: bool = False, spinner: Optional[str] = None) -> RunCommandResult:
    if env is None:
        env = environ.copy()

    if verbose:
        logger.info(f'run_command: {" ".join(command)}')

    process = subprocess.Popen(
        command,
        env=env,
        stderr=subprocess.STDOUT,
        stdout=subprocess.PIPE,
    )

    result = RunCommandResult(return_code=-1)

    if silent:
        result.output = []

    _spinner: Optional[Spinner] = None

    if spinner is not None:
        _spinner = Spinner(f'{spinner} ')

    def sig_handler(signum: int, frame: Optional[FrameType] = None) -> None:
        if result.abort_timestamp is None:
            result.abort_timestamp = datetime.now(timezone.utc)
            process.terminate()

    with SignalHandler(sig_handler, psignal.SIGINT, psignal.SIGTERM):
        try:
            while process.poll() is None:
                stdout = process.stdout
                if stdout is None:
                    break

                if _spinner is not None:
                    _spinner.next()

                output = stdout.readline()
                if not output:
                    break

                if result.output is None:
                    if spinner is None:
                        logger.info(output.decode().rstrip())
                else:
                    result.output.append(output)

            process.terminate()
        except KeyboardInterrupt:
            pass
        finally:
            try:
                process.kill()
            except Exception:
                pass

    process.wait()

    if spinner is not None:
        logger.info('')

    result.return_code = process.returncode

    return result


def get_docker_compose_version() -> Tuple[int, int, int]:
    output = subprocess.getoutput('docker compose version')

    version_line = output.splitlines()[0]

    match = re.match(r'.*version [v]?([1-2]\.[0-9]+\.[0-9]+).*$', version_line)

    if match:
        version = cast(Tuple[int, int, int], tuple([int(part) for part in match.group(1).split('.')]))
    else:
        version = (0, 0, 0,)

    return version


def onerror(func: Callable, path: str, exc_info: Union[
        BaseException,
        Tuple[Type[BaseException], BaseException, Optional[TracebackType]],
]) -> None:  # noqa: ARG001
    """Error handler for shutil.rmtree.

    If the error is due to an access error (read only file)
    it attempts to add write permission and then retries.
    If the error is for another reason it re-raises the error.
    Usage : ``shutil.rmtree(path, onerror=onerror)``
    """
    _path = Path(path)
    # Is the error an access error?
    if not os.access(_path, os.W_OK):
        _path.chmod(stat.S_IWUSR)
        func(path)
    else:
        raise  # pylint: disable=E0704


def rm_rf(path: Union[str, Path], *, missing_ok: bool = False) -> None:
    """Remove the path contents recursively, even if some elements
    are read-only."""
    p = path.as_posix() if isinstance(path, Path) else path

    try:
        if sys.version_info >= (3, 12):
            rmtree(p, onexc=onerror)
        else:
            rmtree(p, onerror=onerror)
    except FileNotFoundError:
        if not missing_ok:
            raise


def get_dependency_versions(local_install: Union[bool, str]) -> Tuple[Tuple[Optional[str], Optional[List[str]]], Optional[str]]:
    grizzly_requirement: Optional[str] = None
    grizzly_requirement_egg: str
    locust_version: Optional[str] = None
    grizzly_version: Optional[str] = None
    grizzly_extras: Optional[List[str]] = None

    args: tuple[str, ...] = (grizzly_cli.EXECUTION_CONTEXT,)
    if isinstance(local_install, str):
        args += (local_install,)
        if not local_install.endswith('requirements.txt'):
            args += ('requirements.txt',)
    else:
        args += ('requirements.txt',)

    project_requirements = path.join(*args)

    try:
        with open(project_requirements, encoding='utf-8') as fd:
            for line in fd.readlines():
                if any([pkg in line for pkg in ['grizzly-loadtester', 'grizzly.git'] if not re.match(r'^([\s]+)?#', line)]):
                    grizzly_requirement = line.strip()
                    break
    except:
        return (None, None,), None

    if grizzly_requirement is None:
        print(f'!! unable to find grizzly dependency in {project_requirements}', file=sys.stderr)
        return ('(unknown)', None, ), '(unknown)'

    # check if it's a repo or not
    if 'git+' in grizzly_requirement:
        if grizzly_requirement.startswith('git+'):
            url, egg_part = grizzly_requirement.rsplit('#', 1)
            _, grizzly_requirement_egg = egg_part.split('=', 1)
        elif grizzly_requirement.index('@') < grizzly_requirement.index('git+'):
            grizzly_requirement_egg, url = grizzly_requirement.split('@', 1)
            grizzly_requirement_egg = grizzly_requirement_egg.strip()
            url = url.strip()
        else:
            print(f'!! unable to find properly formatted grizzly dependency in {project_requirements}', file=sys.stderr)
            return ('(unknown)', None, ), '(unknown)'

        url, branch = url.rsplit('@', 1)
        url = url[4:]  # remove git+
        suffix = sha1(grizzly_requirement.encode('utf-8')).hexdigest()

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
                try:
                    git_object_type = subprocess.check_output(
                        ['git', 'cat-file', '-t', branch],
                        cwd=repo_destination,
                        shell=False,
                        universal_newlines=True,
                        stderr=subprocess.STDOUT,
                    ).strip()
                except subprocess.CalledProcessError as cpe:
                    if 'Not a valid object name' in cpe.output:
                        git_object_type = 'branch'  # assume remote branch
                    else:
                        print(f'!! unable to determine git object type for {branch}')
                        raise RuntimeError()

                if git_object_type == 'tag':
                    rc += subprocess.check_call(
                        [
                            'git', 'checkout',
                            f'tags/{branch}',
                            '-b', branch,
                        ],
                        cwd=repo_destination,
                        shell=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )

                    if rc != 0:
                        print(f'!! unable to checkout tag {branch} from git repo {url}', file=sys.stderr)
                        raise RuntimeError()  # abort
                elif git_object_type == 'commit':
                    rc += subprocess.check_call(
                        [
                            'git', 'checkout',
                            branch,
                        ],
                        cwd=repo_destination,
                        shell=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )

                    if rc != 0:
                        print(f'!! unable to checkout commit {branch} from git repo {url}', file=sys.stderr)
                        raise RuntimeError()  # abort
                else:
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
                try:
                    with open(path.join(repo_destination, 'setup.cfg'), encoding='utf-8') as fd:
                        version_raw = [line.strip() for line in fd.readlines() if line.strip().startswith('version = ')]

                    if len(version_raw) != 1:
                        print(f'!! unable to find "version" declaration in setup.cfg from {url}', file=sys.stderr)
                        raise RuntimeError()  # abort

                    _, grizzly_version = version_raw[-1].split(' = ')
                except FileNotFoundError:
                    try:
                        import setuptools_scm  # pylint: disable=unused-import  # noqa: F401  # type: ignore
                    except ModuleNotFoundError:
                        rc = subprocess.check_call([
                            sys.executable,
                            '-m',
                            'pip',
                            'install',
                            'setuptools_scm',
                        ])

                    try:
                        grizzly_version = subprocess.check_output(
                            [
                                sys.executable,
                                '-m',
                                'setuptools_scm',
                            ],
                            shell=False,
                            universal_newlines=True,
                            cwd=repo_destination,
                        ).strip()
                    except subprocess.CalledProcessError:
                        print(f'!! unable to get setuptools_scm version from {url}', file=sys.stderr)
                        raise RuntimeError()  # abort

            if grizzly_version == '0.0.0':
                grizzly_version = '(development)'

            try:
                with open(path.join(repo_destination, 'requirements.txt'), encoding='utf-8') as fd:
                    version_raw = [line.strip() for line in fd.readlines() if line.strip().startswith('locust')]

                if len(version_raw) != 1:
                    print(f'!! unable to find "locust" dependency in requirements.txt from {url}', file=sys.stderr)
                    raise RuntimeError()  # abort

                match = re.match(r'^locust.{2}(.*?)$', version_raw[-1].strip().split(' ')[0])

                if not match:
                    print(f'!! unable to find locust version in "{version_raw[-1].strip()}" specified in requirements.txt from {url}', file=sys.stderr)
                else:
                    locust_version = match.group(1).strip()
            except FileNotFoundError:
                with open(path.join(repo_destination, 'pyproject.toml'), 'rb') as fdt:
                    toml_dict = tomli.load(fdt)
                    dependencies = toml_dict.get('project', {}).get('dependencies', [])
                    for dependency in dependencies:
                        if not dependency.startswith('locust'):
                            continue

                        _, locust_version = dependency.strip().split(' ', 1)

                        break
        except RuntimeError:
            pass
        finally:
            rm_rf(tmp_workspace)
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
                conditions: List[Callable[[versioning.Version], bool]] = []

                match = re.match(r'^(grizzly-loadtester(\[[^\]]*\])?)(.*?)$', grizzly_requirement)

                if match:
                    grizzly_requirement_egg = match.group(1)
                    condition_expression = match.group(3)

                    for condition in condition_expression.split(',', 1):
                        version_string = re.sub(r'^[^0-9]{1,2}', '', condition)
                        condition_version = versioning.parse(version_string)

                        if '>' in condition:
                            compare = condition_version.__le__ if '=' in condition else condition_version.__lt__
                        elif '<' in condition:
                            compare = condition_version.__ge__ if '=' in condition else condition_version.__gt__
                        else:
                            compare = condition_version.__eq__

                        conditions.append(compare)

                matched_version = None

                for available_version in pypi.get('releases', {}).keys():
                    try:
                        version = versioning.parse(available_version)
                        if len(conditions) > 0 and all([compare(version) for compare in conditions]):
                            matched_version = version
                    except versioning.InvalidVersion:
                        pass

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

                        match = re.match(r'^locust \((.*?)\)$', requires_dist.strip())

                        if match:
                            locust_version = cast(str, match.group(1))
                        else:
                            locust_version = requires_dist.replace('locust', '').strip()

                        if locust_version is not None and locust_version.startswith('=='):
                            locust_version = locust_version[2:]

                        if len(locust_version or '') < 1:
                            print(f'!! unable to find locust version in "{requires_dist.strip()}" specified in pypi for grizzly-loadtester {grizzly_version}', file=sys.stderr)
                            locust_version = '(unknown)'
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

    rc, _ = subprocess.getstatusoutput(f'{container_system} compose version')

    if rc != 0:
        print(f'"{container_system} compose" not found in PATH')
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

    grizzly_cli.FEATURE_DESCRIPTION = feature.name

    for scenario in feature.scenarios:
        grizzly_cli.SCENARIOS.append(scenario)


def find_metadata_notices(file: str) -> List[str]:
    with open(file) as fd:
        return [line.strip().replace('# grizzly-cli:notice ', '') for line in fd.readlines() if line.strip().startswith('# grizzly-cli:notice ')]


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
        _iterations: Optional[int]
        _user_count: Optional[int]

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
            self._iterations = iterations
            self.weight = weight or 1.0
            self.identifier = f'{index:03}'
            self._user_count = user_count

        @property
        def iterations(self) -> int:
            if self._iterations is None:
                raise ValueError('iterations has not been set')

            return self._iterations

        @iterations.setter
        def iterations(self, value: int) -> None:
            self._iterations = value

        @property
        def user_count(self) -> int:
            if self._user_count is None:
                raise ValueError('user count has not been set')
            return self._user_count

        @user_count.setter
        def user_count(self, value: int) -> None:
            self._user_count = value

        def is_fulfilled(self) -> bool:
            return self.user is not None and self._iterations is not None and self._user_count is not None

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

    scenario_user_count_total: Optional[int] = None
    use_weights = True

    for index, scenario in enumerate(grizzly_cli.SCENARIOS):
        scenario_variables: Dict[str, Any] = {}
        if len(scenario.steps) < 1:
            raise ValueError(f'scenario "{scenario.name}" does not have any steps')

        _pre_populate_scenario(scenario, index=index + 1)

        if index == 0:  # background_steps is only processed for first scenario in grizzly
            for step in scenario.background_steps or []:
                if (step.name.endswith(' users') or step.name.endswith(' user')) and step.keyword == 'Given':
                    match = re.match(r'"([^"]*)" user(s)?', step.name)
                    if match:
                        scenario_user_count_total = int(round(float(Template(match.group(1)).render(**variables)), 0))

        if scenario_user_count_total is None:
            use_weights = False
            scenario_user_count_total = 0

        for step in (scenario.background_steps or []) + scenario.steps:
            if step.name.startswith('value for variable'):
                match = re.match(r'value for variable "([^"]*)" is "([^"]*)"', step.name)
                if match:
                    try:
                        variable_name = match.group(1)
                        variable_value = Template(match.group(2)).render(**variables, **scenario_variables)
                        scenario_variables.update({variable_name: variable_value})
                    except:
                        continue
            elif step.name.startswith('a user of type'):
                match = re.match(r'a user of type "([^"]*)" (with weight "([^"]*)")?.*', step.name)
                if match:
                    distribution[scenario.name].user = match.group(1)
                    distribution[scenario.name].weight = int(float(Template(match.group(3) or '1.0').render(**variables, **scenario_variables)))
            elif step.name.startswith('repeat for'):
                match = re.match(r'repeat for "([^"]*)" iteration[s]?', step.name)
                if match:
                    distribution[scenario.name].iterations = int(round(float(Template(match.group(1)).render(**variables, **scenario_variables)), 0))
                    (distribution[scenario.name].iterations)
            elif any([pattern in step.name for pattern in ['users of type', 'user of type']]):
                match = re.match(r'"([^"]*)" user[s]? of type "([^"]*)".*', step.name)
                if match:
                    scenario_user_count = int(round(float(Template(match.group(1)).render(**variables, **scenario_variables)), 0))
                    scenario_user_count_total += scenario_user_count

                    distribution[scenario.name].user_count = scenario_user_count
                    distribution[scenario.name].user = match.group(2)

            if distribution[scenario.name].is_fulfilled():
                break

    scenario_count = len(distribution.keys())
    assert scenario_user_count_total is not None
    if scenario_count > scenario_user_count_total:
        raise ValueError(f'grizzly needs at least {scenario_count} users to run this feature')

    total_weight = 0
    total_iterations = 0
    for scenario in distribution.values():
        if scenario.user is None:
            raise ValueError(f'{scenario.name} does not have a user type')

        total_weight += scenario.weight
        total_iterations += scenario.iterations

    if use_weights:
        for scenario in distribution.values():
            scenario.user_count = ceil(scenario_user_count_total * (scenario.weight / total_weight))

        # smooth assigned user count based on weight, so that the sum of scenario.user_count == total_user_count
        total_user_count = sum([scenario.user_count for scenario in distribution.values()])
        user_overflow = total_user_count - scenario_user_count_total

        while user_overflow > 0:
            for scenario in dict(sorted(distribution.items(), key=lambda d: d[1].user_count, reverse=True)).values():
                if scenario.user_count <= 1:
                    continue

                scenario.user_count -= 1
                user_overflow -= 1

                if user_overflow < 1:
                    break

    def print_table_lines(max_length_iterations: int, max_length_users: int, max_length_description: int, max_length_errors: int) -> None:
        line = ['-' * 5, '-|-', '-' * 6, '|-', '-' * max_length_iterations, '|-', '-' * max_length_users, '|-', '-' * max_length_description, '-|']
        if not use_weights:
            line = line[:1] + line[3:]
            line[0] = f'{line[0]}-'

        if max_length_errors > 0:
            line += ['-' * (max_length_errors + 1), '-|']
        logger.info(''.join(line))

    rows: List[str] = []
    max_length_description = len('description')
    max_length_iterations = len('#iter')
    max_length_users = len('#user')
    max_length_errors = len('errors')

    logger.info(f'\nfeature file {args.file} will execute in total {total_iterations} iterations divided on {len(grizzly_cli.SCENARIOS)} scenarios\n')

    errors: Dict[str, List[str]] = {}

    for scenario in distribution.values():
        # check for errors
        if scenario.user_count < 1:
            if scenario.name not in errors:
                errors.update({scenario.name: []})

            errors[scenario.name].append('no users assigned')

        if scenario.iterations < 1:
            if scenario.name not in errors:
                errors.update({scenario.name: []})

            errors[scenario.name].append('no iterations')

        # calculate max length out of all rows
        max_length_description = max(len(scenario.name), max_length_description)
        max_length_iterations = max(len(str(scenario.iterations)), max_length_iterations)
        max_length_users = max(len(str(scenario.user_count)), max_length_users)
        max_length_errors = max(len(', '.join(errors.get(scenario.name, []))), max_length_errors)

    # there was no errors, so reset max length for that column, so it won't be included
    if len(errors) < 1:
        max_length_errors = 0

    row_format = ['{:5} ', '  {:>6d}', '  {:>{}}', '  {:>{}}', '  {:<{}}']
    if not use_weights:
        row_format.pop(1)

    if len(errors) > 0:
        row_format.append('   {}')

    for scenario in distribution.values():
        row_format_args: List[Any] = [
            scenario.identifier,
            scenario.weight,
            scenario.iterations,
            max_length_iterations,
            scenario.user_count,
            max_length_users,
            scenario.name,
            max_length_description,
        ]

        # remove weights column
        if not use_weights:
            row_format_args.pop(1)

        if len(errors) > 0:
            row_format_args.append(
                ', '.join(errors.get(scenario.name, [])),
            )

        rows.append(''.join(row_format).format(*row_format_args))

    logger.info('each scenario will execute accordingly:\n')
    header_row_args: List[Any] = [
        'ident',
        'weight',
        '#iter', max_length_iterations,
        '#user', max_length_users,
        'description', max_length_description,
    ]

    header_row_format = ['{:5} ', '  {:>6}', '  {:>{}}', '  {:>{}}', '  {:<{}}']
    if not use_weights:
        header_row_format.pop(1)
        header_row_args.pop(1)

    if len(errors) > 0:
        header_row_format.append('   {}')
        header_row_args.append('errors')

    logger.info(''.join(header_row_format).format(*header_row_args))
    print_table_lines(max_length_iterations, max_length_users, max_length_description, max_length_errors)
    for row in rows:
        logger.info(row)
    print_table_lines(max_length_iterations, max_length_users, max_length_description, max_length_errors)

    if len(errors) > 0:
        arrow_width = len('ident') + 2 + max_length_iterations + 2 + max_length_users + 2 + max_length_description + 2
        if use_weights:
            arrow_width += len('weight') + 2
        message = f'''{" " * (1 + arrow_width)}^
+{"-" * arrow_width}+
|
+- there were errors when calculating user distribution and iterations per scenario, adjust user "weight", number of users or iterations per scenario
'''

        raise ValueError(message)
    else:
        logger.info('')

    for scenario in distribution.values():
        if scenario.iterations < scenario.user_count:
            raise ValueError(f'{scenario.name} will have {scenario.user_count} users to run {scenario.iterations} iterations, increase iterations or lower user count')

    if not args.yes:
        ask_yes_no('continue?')


def setup_logging(logfile: Optional[str] = None) -> None:
    logging_config: dict = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'plain': {
                'format': '%(message)s',
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'plain',
            },
        },
        'loggers': {
            'grizzly-cli': {
                'handlers': ['console'],
                'level': 'INFO',
                'propagate': False,
            },
        },
        'root': {
            'handlers': ['console'],
            'level': 'INFO',
        },
    }

    if logfile is not None:
        logging_config['handlers']['file'] = {
            'class': 'logging.FileHandler',
            'filename': logfile,
            'formatter': 'plain',
        }

        logging_config['loggers']['grizzly-cli']['handlers'].append('file')
        logging_config['root']['handlers'].append('file')

    logging.config.dictConfig(logging_config)
