import sys

from shutil import rmtree
from tempfile import NamedTemporaryFile
from typing import Optional
from os import path, pathsep
from datetime import datetime

import pytest
import yaml

from ..fixtures import End2EndFixture
from ..helpers import run_command, onerror


def test_e2e_run_example(e2e_fixture: End2EndFixture) -> None:
    if sys.version_info < (3, 8,) and not e2e_fixture._distributed:
        pytest.skip('grizzly-loadtester only supports python >= 3.8')

    if sys.platform == 'win32' and e2e_fixture._distributed:
        pytest.skip('windows github runners do not support running linux containers')

    result: Optional[str] = None

    try:
        example_root = e2e_fixture.root / 'grizzly-example'

        example_root.mkdir()

        rc, _ = run_command([
            'git', 'init',
        ], cwd=str(example_root))

        assert rc == 0

        rc, _ = run_command([
            'git', 'remote', 'add', '-f', 'origin', 'https://github.com/Biometria-se/grizzly.git'
        ], cwd=str(example_root))

        assert rc == 0

        rc, _ = run_command([
            'git', 'sparse-checkout', 'init',
        ], cwd=str(example_root))

        assert rc == 0

        rc, _ = run_command([
            'git', 'sparse-checkout', 'set', 'example',
        ], cwd=str(example_root))

        assert rc == 0

        rc, _ = run_command([
            'git', 'pull', 'origin', 'main',
        ], cwd=str(example_root))

        assert rc == 0

        rmtree(example_root / '.git', onerror=onerror)

        example_root = example_root / 'example'

        with open(example_root / 'features' / 'steps' / 'steps.py', 'a') as fd:
            fd.write(e2e_fixture.start_webserver_step_impl(e2e_fixture.webserver_port))

        e2e_fixture.inject_webserver_module(example_root)

        with open(example_root / 'environments' / 'example.yaml') as env_yaml_file:
            env_conf = yaml.full_load(env_yaml_file)

            for name in ['dog', 'cat', 'book']:
                env_conf['configuration']['facts'][name]['host'] = f'http://{e2e_fixture.host}'

        feature_file = path.join('features', 'example.feature')
        feature_file_path = example_root / 'features' / 'example.feature'
        feature_file_contents = feature_file_path.read_text().split('\n')

        requirements_file = example_root / 'requirements.txt'
        requirements_file.write_text('grizzly-loadtester @ git+https://github.com/Biometria-se/grizzly.git@main\n')

        if e2e_fixture._distributed:
            command = ['grizzly-cli', 'dist', '--project-name', e2e_fixture.root.name, 'build', '--no-cache']
            rc, output = run_command(
                command,
                cwd=str(example_root),
                env=e2e_fixture._env,
            )
            try:
                assert rc == 0
            except AssertionError:
                print(''.join(output))
                raise
        else:
            command = ['python', '-m', 'pip', 'install', '--no-cache-dir', '-r', 'requirements.txt']
            if sys.platform == 'win32':
                command += ['--user']

            rc, output = run_command(
                command,
                cwd=str(example_root),
                env=e2e_fixture._env,
            )

            try:
                assert rc == 0
            except AssertionError:
                print(''.join(output))
                raise

        index = feature_file_contents.index('  Scenario: dog facts api')
        # should go last in "Background"-section
        feature_file_contents.insert(index - 1, f'    Then start webserver on master port "{e2e_fixture.webserver_port}"')

        with open(feature_file_path, 'w') as fd:
            fd.truncate(0)
            fd.write('\n'.join(feature_file_contents))

        with NamedTemporaryFile(delete=False, suffix='.yaml', dir=f'{example_root}/environments') as env_conf_file:
            env_conf_file.write(yaml.dump(env_conf, Dumper=yaml.Dumper).encode())
            env_conf_file.flush()

            rc, output = e2e_fixture.execute(
                feature_file,
                env_conf_file.name.replace(f'{str(example_root)}{pathsep}', ''),
                cwd=str(example_root),
                arguments=['--csv-prefix', '-l', 'test_run.log'],
            )

            # problems with a locust DEBUG log message containing ERROR in the message on macos-latest
            if sys.platform == 'darwin':
                output = [line for line in output if 'ERROR' not in line and 'DEBUG' not in line]

            result = ''.join(output)

            assert rc == 0
            assert 'ERROR' not in result
            assert 'WARNING' not in result
            assert '1 feature passed, 0 failed, 0 skipped' in result
            assert '3 scenarios passed, 0 failed, 0 skipped' in result
            assert '29 steps passed, 0 failed, 0 skipped, 0 undefined' in result

            assert 'ident   iter  status   description' in result
            assert '001      2/2  passed   dog facts api' in result
            assert '002      1/1  passed   cat facts api' in result
            assert '003      1/1  passed   book api' in result
            assert '------|-----|--------|---------------|' in result

            assert 'executing custom.User.request for get-cat-facts and /facts?limit=' in result

            assert 'sending "client_server" from CLIENT' in result
            assert "received from CLIENT" in result
            assert "AtomicCustomVariable.foobar='foobar'" in result

            datestamp = datetime.now().astimezone().strftime('%Y%m%dT')

            csv_file_exceptions = list(example_root.glob('*_exceptions.csv'))
            assert len(csv_file_exceptions) == 1
            assert csv_file_exceptions[0].read_text().strip() == 'Count,Message,Traceback,Nodes'
            assert csv_file_exceptions[0].name.startswith(f'grizzly_example_{datestamp}')

            csv_file_failures = list(example_root.glob('*_failures.csv'))
            assert len(csv_file_failures) == 1
            assert csv_file_failures[0].read_text().strip() == 'Method,Name,Error,Occurrences'
            assert csv_file_failures[0].name.startswith(f'grizzly_example_{datestamp}')

            csv_file_stats = list(example_root.glob('*_stats.csv'))
            assert len(csv_file_stats) == 1
            assert csv_file_stats[0].read_text().strip() != ''
            assert csv_file_stats[0].name.startswith(f'grizzly_example_{datestamp}')

            csv_file_stats_history = list(example_root.glob('*_stats_history.csv'))
            assert len(csv_file_stats_history) == 1
            assert csv_file_stats_history[0].read_text().strip() != ''
            assert csv_file_stats_history[0].name.startswith(f'grizzly_example_{datestamp}')

            log_file_result = (example_root / 'test_run.log').read_text()

            # problems with a locust DEBUG log message containing ERROR in the message on macos-latest
            if sys.platform == 'darwin':
                output = [line for line in log_file_result.split('\n') if 'ERROR' not in line and 'DEBUG' not in line]
                log_file_result = '\n'.join(output)

            assert log_file_result == result
    except:
        if result is not None:
            print(result)
        raise
