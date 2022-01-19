import sys
import os
import subprocess

from typing import Any, Dict, List, Set, Optional, cast
from json import loads as jsonloads
from pathlib import Path
from argparse import Namespace as Arguments, ArgumentParser

from behave.parser import parse_file as feature_file_parser
from behave.model import Scenario, Step

__version__ = '0.0.0'

EXECUTION_CONTEXT = os.getcwd()

STATIC_CONTEXT = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'static')

MOUNT_CONTEXT = os.environ.get('GRIZZLY_MOUNT_CONTEXT', EXECUTION_CONTEXT)

PROJECT_NAME = os.path.basename(EXECUTION_CONTEXT)

SCENARIOS: Set[Scenario] = set()


class GrizzlyCliParser(ArgumentParser):
    def error_no_help(self, message: str) -> None:
        sys.stderr.write('grizzly-run: error: {}\n'.format(message))
        sys.exit(2)


def parse_feature_file(file: Optional[str]) -> None:
    if len(SCENARIOS) > 0:
        return

    if file is None:
        feature_files = list(Path(os.path.join(EXECUTION_CONTEXT, 'features')).rglob('*.feature'))
    else:
        feature_files = [Path(file)]

    for feature_file in feature_files:
        feature = feature_file_parser(feature_file)
        for scenario in feature.scenarios:
            SCENARIOS.add(scenario)


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
            images[name] = {'tags': {}}
        images[name]['tags'].update(version)

    return images

def get_default_mtu(args: Arguments) -> Optional[str]:
    try:
        output = subprocess.check_output([
            'docker',
            'network',
            'inspect',
            'bridge',
            '--format',
            '{{ json .Options }}',
        ]).decode('utf-8')

        lines = output.split('\n')
        line = lines[0]
        network_options = jsonloads(line)
        mtu = network_options.get('com.docker.network.driver.mtu', '1500')

        return cast(str, mtu)
    except:
        print(output)
        return None


def run_command(command: List[str], env: Optional[Dict[str, str]] = None) -> int:
    if env is None:
        env = os.environ.copy()

    process = subprocess.Popen(
        command,
        env=env,
        stderr=subprocess.STDOUT,
        stdout=subprocess.PIPE,
    )

    try:
        while process.poll() is None:
            stdout = process.stdout
            if stdout is None:
                break

            output = stdout.readline()
            if not output:
                break

            print(output.decode('utf-8').strip())

        process.terminate()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            process.kill()
        except Exception:
            pass

    process.wait()

    return process.returncode
