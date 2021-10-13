import codecs
import os

from typing import List
from setuptools import setup, find_packages
from pathlib import Path

from grizzly_cli import __version__


def long_description() -> str:
    with codecs.open('README.md', encoding='utf-8') as fd:
        return fd.read()


def install_requires() -> List[str]:
    install_requires: List[str] = []
    with codecs.open('requirements.txt', encoding='utf-8') as fd:
        for line in fd.readlines():
            install_requires.append(line.strip())

    return install_requires


def grizzly_cli_static_files() -> List[str]:
    files: List[str] = []

    base = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'grizzly_cli')

    for path in Path(os.path.join(base, 'static')).rglob('*'):
        if not path.is_file():
            continue

        files.append(str(path).replace(f'{base}/', ''))

    return files


setup(
    name='grizzly-loadtester-cli',
    version=__version__,
    description='Command line interface for grizzly-loadtester',
    long_description=long_description(),
    long_description_content_type='text/markdown',
    url='https://github.com/biometria-se/grizzly-cli',
    author='Biometria',
    author_email='opensource@biometria.se',
    license='MIT',
    packages=find_packages(),
    package_data={
        'grizzly_cli': grizzly_cli_static_files(),
    },
    python_requires='>=3.6',
    install_requires=install_requires(),
    entry_points={
        'console_scripts': [
            'grizzly-cli=grizzly_cli.cli:main',
        ],
    },
)
