import os
import subprocess
import sys

from typing import Any, Dict, List, Set, Optional
from json import loads as jsonloads
from argparse import Namespace as Arguments

from behave.parser import parse_file as feature_file_parser
from behave.model import Scenario


__version__ = '0.0.0'

EXECUTION_CONTEXT = os.getcwd()

STATIC_CONTEXT = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'static')

MOUNT_CONTEXT = os.environ.get('GRIZZLY_MOUNT_CONTEXT', EXECUTION_CONTEXT)

PROJECT_NAME = os.path.basename(EXECUTION_CONTEXT)

SCENARIOS: Set[Scenario] = set()


def parse_feature_file(file: str) -> None:
    if len(SCENARIOS) > 0:
        return

    feature = feature_file_parser(file)
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
            images[name] = {}
        images[name].update(version)

    return images

def get_default_mtu(args: Arguments) -> Optional[str]:
    try:
        output = subprocess.check_output([
            f'{args.container_system}',
            'network',
            'inspect',
            'bridge',
            '--format',
            '{{ json .Options }}',
        ]).decode('utf-8')

        line, _ = output.split('\n', 1)
        network_options: Dict[str, str] = jsonloads(line)
        return network_options.get('com.docker.network.driver.mtu', '1500')
    except:
        return None


def run_command(command: List[str], env: Optional[Dict[str, str]] = None, silent: bool = False) -> int:
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

            if not silent:
                sys.stdout.write(output.decode('utf-8'))

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
