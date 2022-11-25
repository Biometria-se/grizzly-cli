import os

from typing import List, Dict, Any, Callable, cast
from argparse import Namespace as Arguments
from platform import node as get_hostname

from . import EXECUTION_CONTEXT, MOUNT_CONTEXT
from .utils import (
    find_variable_names_in_questions,
    ask_yes_no, get_input,
    distribution_of_users_per_scenario,
    requirements,
    find_metadata_notices,
)
from .argparse import ArgumentSubParser
from .argparse.bashcompletion import BashCompletionTypes


def create_parser(sub_parser: ArgumentSubParser, parent: str) -> None:
    # grizzly-cli ... run ...
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
    run_parser.add_argument(
        'file',
        nargs='+',
        type=BashCompletionTypes.File('*.feature'),
        help='path to feature file with one or more scenarios',

    )

    if run_parser.prog != f'grizzly-cli {parent} run':  # pragma: no cover
        run_parser.prog = f'grizzly-cli {parent} run'


@requirements(EXECUTION_CONTEXT)
def run(args: Arguments, run_func: Callable[[Arguments, Dict[str, Any], Dict[str, List[str]]], int]) -> int:
    # always set hostname of host where grizzly-cli was executed, could be useful
    environ: Dict[str, Any] = {
        'GRIZZLY_CLI_HOST': get_hostname(),
        'GRIZZLY_EXECUTION_CONTEXT': EXECUTION_CONTEXT,
        'GRIZZLY_MOUNT_CONTEXT': MOUNT_CONTEXT,
    }

    variables = find_variable_names_in_questions(args.file)
    questions = len(variables)
    manual_input = False

    if questions > 0 and not getattr(args, 'validate_config', False):
        print(f'feature file requires values for {questions} variables')

        for variable in variables:
            name = f'TESTDATA_VARIABLE_{variable}'
            value = os.environ.get(name, '')
            while len(value) < 1:
                value = get_input(f'initial value for "{variable}": ')
                manual_input = True

            environ[name] = value

        print('the following values was provided:')
        for key, value in environ.items():
            if not key.startswith('TESTDATA_VARIABLE_'):
                continue
            print(f'{key.replace("TESTDATA_VARIABLE_", "")} = {value}')

        if manual_input:
            ask_yes_no('continue?')

    notices = find_metadata_notices(args.file)

    if len(notices) > 0:
        if args.yes:
            output_func = cast(Callable[[str], None], print)
        else:
            output_func = ask_yes_no

        for notice in notices:
            output_func(notice)

    if args.environment_file is not None:
        environment_file = os.path.realpath(args.environment_file)
        environ['GRIZZLY_CONFIGURATION_FILE'] = environment_file

    if not getattr(args, 'validate_config', False):
        distribution_of_users_per_scenario(args, environ)

    run_arguments: Dict[str, List[str]] = {
        'master': [],
        'worker': [],
        'common': ['--stop'],
    }

    if args.verbose:
        run_arguments['common'] += ['--verbose', '--no-logcapture', '--no-capture', '--no-capture-stderr']

    return run_func(args, environ, run_arguments)
