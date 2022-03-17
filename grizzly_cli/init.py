from typing import Generator
from argparse import Namespace as Arguments
from os import path
from pathlib import Path

from .utils import ask_yes_no
from . import EXECUTION_CONTEXT

# prefix components:
space = '    '
branch = '│   '
# pointers:
tee = '├── '
last = '└── '


def tree(dir_path: Path, prefix: str = '') -> Generator[str, None, None]:
    '''A recursive generator, given a directory Path object
    will yield a visual tree structure line by line
    with each line prefixed by the same characters

    credit: https://stackoverflow.com/a/59109706
    '''
    contents = list(dir_path.iterdir())
    # contents each get pointers that are ├── with a final └── :
    pointers = [tee] * (len(contents) - 1) + [last]
    for pointer, sub_path in zip(pointers, contents):
        yield prefix + pointer + sub_path.name
        if sub_path.is_dir():  # extend the prefix and recurse:
            extension = branch if pointer == tee else space
            # i.e. space because last, └── , above so no more |
            yield from tree(sub_path, prefix=prefix + extension)


def init(args: Arguments) -> int:
    if path.exists(path.join(EXECUTION_CONTEXT, args.project)):
        print(f'"{args.project}" already exists in {EXECUTION_CONTEXT}')
        return 1

    if all([path.exists(path.join(EXECUTION_CONTEXT, p)) for p in ['environments', 'features', 'requirements.txt']]):
        print('oops, looks like you are already in a grizzly project directory', end='\n\n')
        print(EXECUTION_CONTEXT)
        for line in tree(Path(EXECUTION_CONTEXT)):
            print(line)
        return 1

    layout = f'''
    {args.project}
    ├── features
    │   ├── environment.py
    │   ├── steps
    │   │   └── steps.py
    │   ├── {args.project}.feature
    │   └── requests
    ├── environments
    │   └── {args.project}.yaml
    └── requirements.txt
'''
    ask_yes_no(f'the following structure will be created:\n{layout}\ndo you want to create grizzly project "{args.project}"?')

    # create project root
    structure = Path(path.join(EXECUTION_CONTEXT, args.project))
    structure.mkdir()

    # create requirements.txt
    grizzly_dependency = 'grizzly-loadtester'

    if args.with_mq:
        grizzly_dependency = f'{grizzly_dependency}[mq]'

    if args.grizzly_version is not None:
        grizzly_dependency = f'{grizzly_dependency}=={args.grizzly_version}'

    (structure / 'requirements.txt').write_text(f'{grizzly_dependency}\n')

    # create environments/
    structure_environments = structure / 'environments'
    structure_environments.mkdir()

    # create environments/<project>.yaml
    (structure_environments / f'{args.project}.yaml').write_text('''configuration:
  template:
    host: https://localhost
''')

    # create features/ directory
    structure_features = structure / 'features'
    structure_features.mkdir()

    # create features/<project>.feature
    (structure_features / f'{args.project}.feature').write_text('''Feature: Template feature file
  Scenario: Template scenario
    Given a user of type "RestApi" with weight "1" load testing "$conf::template.host"
''')

    # create features/environment.py
    (structure_features / 'environment.py').write_text('from grizzly.environment import *\n\n')

    # create features/requests directory
    (structure_features / 'requests').mkdir()

    # create features/steps directory
    structure_feature_steps = structure_features / 'steps'
    structure_feature_steps.mkdir()

    # create features/steps/steps.py
    (structure_feature_steps / 'steps.py').write_text('from grizzly.steps import *\n\n')

    print(f'successfully created project "{args.project}", with the following options:')
    print(f'{" " * 2}\u2022 {"with" if args.with_mq else "without"} IBM MQ support')
    if args.grizzly_version is not None:
        print(f'{" " * 2}\u2022 pinned to grizzly version {args.grizzly_version}')
    else:
        print(f'{" " * 2}\u2022 latest grizzly version')

    return 0
