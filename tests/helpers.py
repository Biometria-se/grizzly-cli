import subprocess
import os
import stat
import sys

from typing import Dict, Optional, Tuple, List, Callable
from types import TracebackType

from behave.model import Scenario, Step


def run_command(command: List[str], env: Optional[Dict[str, str]] = None, cwd: Optional[str] = None) -> Tuple[int, List[str]]:
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
    )

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
