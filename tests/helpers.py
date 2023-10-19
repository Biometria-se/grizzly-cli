import subprocess
import os
import stat
import sys

from typing import Dict, Optional, Tuple, List, Callable, cast
from types import TracebackType
from pathlib import Path

from behave.model import Scenario, Step
from setuptools_scm import Configuration as SetuptoolsScmConfiguration
from setuptools_scm._cli import _get_version as setuptools_scm_get_version


def run_command(command: List[str], env: Optional[Dict[str, str]] = None, cwd: Optional[str] = None, stdin: Optional[str] = None) -> Tuple[int, List[str]]:
    output: List[str] = []
    if env is None:
        env = os.environ.copy()

    if cwd is None:
        cwd = os.getcwd()

    process = subprocess.Popen(
        command,
        env=env,
        cwd=cwd,
        stderr=subprocess.STDOUT,
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
    )

    if stdin is not None:
        assert process.stdin is not None
        process.stdin.write(f'{stdin}\n'.encode('utf-8'))
        process.stdin.close()

    try:
        while process.poll() is None:
            stdout = process.stdout
            if stdout is None:
                break

            buffer = stdout.readline()
            if not buffer:
                break

            line = buffer.decode('utf-8')
            if sys.platform == 'win32':
                line = line.replace(os.linesep, '\n')

            output.append(line)

        process.terminate()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            process.kill()
        except Exception:
            pass

    process.wait()

    return process.returncode, output


def onerror(func: Callable, path: str, exc_info: TracebackType) -> None:
    '''
    Error handler for ``shutil.rmtree``.
    If the error is due to an access error (read only file)
    it attempts to add write permission and then retries.
    If the error is for another reason it re-raises the error.
    Usage : ``shutil.rmtree(path, onerror=onerror)``
    '''
    # Is the error an access error?
    if not os.access(path, os.W_OK):
        os.chmod(path, stat.S_IWUSR)
        func(path)
    else:
        raise  # pylint: disable=misplaced-bare-raise


def create_scenario(name: str, background_steps: List[str], steps: List[str]) -> Scenario:
    scenario = Scenario('', '', '', name)

    for background_step in background_steps:
        [keyword, name] = background_step.split(' ', 1)
        step = Step('', '', keyword.strip(), keyword.strip(), name.strip())
        if scenario._background_steps is None:
            scenario._background_steps = []
        scenario._background_steps.append(step)

    for step in steps:
        [keyword, name] = step.split(' ', 1)
        step = Step('', '', keyword.strip(), keyword.strip(), name.strip())
        scenario.steps.append(step)

    return scenario


def get_current_version() -> str:
    root = (Path(__file__).parent / '..').resolve()

    version = setuptools_scm_get_version(SetuptoolsScmConfiguration.from_file(str(root / 'pyproject.toml'), str(root)), True)

    assert version is not None, f'setuptools-scm was not able to get current version for {str(root)}'

    return cast(str, version)
