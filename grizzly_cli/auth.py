import sys

from os import environ
from argparse import Namespace as Arguments
from typing import Optional
from pathlib import Path

from pyotp import TOTP

from . import register_parser
from .argparse import ArgumentSubParser


@register_parser()
def create_parser(sub_parser: ArgumentSubParser) -> None:
    # grizzly-cli auth
    auth_parser = sub_parser.add_parser('auth', description=(
        'grizzly stateless authenticator application'
    ))

    auth_parser.add_argument(
        'input',
        nargs='?',
        type=str,
        default=None,
        const=None,
        help=(
            'where to read OTP secret, nothing specified means environment variable OTP_SECRET, '
            '`-` means stdin and anything else is considered a file'
        )
    )

    if auth_parser.prog != 'grizzly-cli auth':  # pragma: no cover
        auth_parser.prog = 'grizzly-cli auth'


def auth(args: Arguments) -> int:
    secret: Optional[str] = None

    if args.input is None:
        secret = environ.get('OTP_SECRET', None)
        if secret is None:
            raise ValueError('environment variable OTP_SECRET is not set')
    elif args.input == '-':
        try:
            secret = sys.stdin.read().strip()
        except:
            pass
        finally:
            if secret is None or len(secret.strip()) < 1:
                raise ValueError('OTP secret could not be read from stdin')
    else:
        input_file = Path(args.input)

        if not input_file.exists():
            raise ValueError(f'file {input_file} does not exist')

        secret = input_file.read_text().strip()

        if ' ' in secret or len(secret.split('\n')) > 1 or secret == '':
            raise ValueError(f'file {input_file} does not seem to contain a single line with a valid OTP secret')

    try:
        totp = TOTP(secret)

        print(totp.now())
    except Exception as e:
        raise ValueError(f'unable to generate TOTP code: {e}')

    return 0
