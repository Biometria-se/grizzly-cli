import os
import stat

from typing import Callable, List
from types import TracebackType

from behave.model import Scenario, Step


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
