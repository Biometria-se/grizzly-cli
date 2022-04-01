#!/usr/bin/env python

import sys

from typing import List
from os import path
from json import loads as jsonloads
from io import StringIO

from piplicenses import CustomNamespace, FormatArg, FromArg, OrderArg, create_output_string
from pytablewriter import MarkdownTableWriter

URL_MAP = {
    'pylint': 'https://www.pylint.org/',
    'msal-extensions': 'https://github.com/AzureAD/microsoft-authentication-extensions-for-python',
    'tomli': 'https://github.com/hukkin/tomli',
    'databind.core': 'https://github.com/NiklasRosenstein/databind',
    'databind.json': 'https://github.com/NiklasRosenstein/databind',
    'pydoc-markdown': 'https://pydoc-markdown.readthedocs.io/en/latest/',
    'yapf': 'https://pypi.org/project/yapf/',
    'databind': 'https://github.com/NiklasRosenstein/databind',
    'tomli-w': 'https://github.com/hukkin/tomli-w',
    'build': 'https://github.com/pypa/build',
    'typing-extensions': 'https://github.com/python/typing/blob/master/typing_extensions/',
}

REPO_ROOT = path.realpath(path.join(path.dirname(__file__), '..'))


def generate_license_table() -> List[str]:
    args = CustomNamespace()
    args.format_ = FormatArg.JSON
    args.from_ = FromArg.MIXED
    args.order = OrderArg.LICENSE
    args.summary = False
    args.with_authors = False
    args.with_urls = True
    args.with_description = False
    args.with_license_file = True
    args.no_license_path = False
    args.with_license_file = False
    args.ignore_packages = []
    args.packages = []
    args.fail_on = None
    args.allow_only = None
    args.with_system = False
    args.filter_strings = False

    licenses = jsonloads(create_output_string(args))
    headers = ['Name', 'Version', 'License']

    table_contents: List[List[str]] = []

    for license in licenses:
        name = license['Name']
        if name.startswith('grizzly-'):
            continue

        if license['URL'] == 'UNKNOWN':
            if name in URL_MAP:
                license['URL'] = URL_MAP[name]
            else:
                print(f'!! you need to find an url for package {name}')
                sys.exit(1)

        name = f'[{name}]({license["URL"]})'

        table_contents.append([
            name,
            license['Version'],
            license['License'],
        ])

    writer = MarkdownTableWriter(
        headers=headers,
        value_matrix=table_contents,
        margin=1,
    )

    writer.stream = StringIO()
    writer.write_table()

    license_table = ['### Python dependencies\n'] + [f'{row}\n' for row in writer.stream.getvalue().strip().split('\n')]

    return license_table


def main() -> int:
    with open(path.join(REPO_ROOT, 'LICENSE.md')) as fd:
        contents = fd.readlines()

    license_table = generate_license_table()
    contents[0] = f'#{contents[0]}'
    license_contents = ['# Licenses\n', '\n'] + contents + ['\n', '## Third party licenses\n', '\n'] + license_table[:-1]

    print(''.join(license_contents))

    return 0


if __name__ == '__main__':
    sys.exit(main())
