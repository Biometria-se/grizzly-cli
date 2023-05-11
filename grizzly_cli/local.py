import os

from typing import List, Dict, Any
from argparse import Namespace as Arguments

from . import register_parser
from .utils import (
    run_command,
)
from .run import create_parser as run_create_parser, run
from .argparse import ArgumentSubParser


@register_parser(order=2)
def create_parser(sub_parser: ArgumentSubParser) -> None:
    local_parser = sub_parser.add_parser('local', description='commands for running grizzly in local mode.')

    if local_parser.prog != 'grizzly-cli local':  # pragma: no cover
        local_parser.prog = 'grizzly-cli local'

    sub_parser = local_parser.add_subparsers(dest='subcommand')

    run_create_parser(sub_parser, parent='local')


def local(args: Arguments) -> int:
    if args.subcommand == 'run':
        return run(args, local_run)
    else:
        raise ValueError(f'unknown subcommand {args.subcommand}')


def local_run(args: Arguments, environ: Dict[str, Any], run_arguments: Dict[str, List[str]]) -> int:
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

    return run_command(command).return_code
