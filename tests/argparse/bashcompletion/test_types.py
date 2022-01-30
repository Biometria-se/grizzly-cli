from shutil import rmtree
from os import chdir, getcwd, sep
from argparse import ArgumentTypeError

import pytest

from _pytest.tmpdir import TempdirFactory

from grizzly_cli.argparse.bashcompletion.types import BashCompletionTypes

from ...helpers import onerror

CWD = getcwd()

class TestBashCompletionTypes:
    class TestFile:
        def test___init__(self) -> None:
            assert BashCompletionTypes.File('*.txt').patterns == ['*.txt']
            assert BashCompletionTypes.File('*.txt', '*.json').patterns == ['*.txt', '*.json']
            assert BashCompletionTypes.File('*.txt', '*.json', '*.xml').patterns == ['*.txt', '*.json', '*.xml']

        def test___call__(self, tmpdir_factory: TempdirFactory) -> None:
            test_context = tmpdir_factory.mktemp('test_context')
            test_context.mkdir('test-dir')
            test_context.join('test.txt').write('test.txt file')
            test_context.join('test.json').write('{"value": "test.json file"}')
            test_context.join('test.xml').write('<value>test.xml file</value>')
            test_context_root = str(test_context)

            chdir(test_context_root)

            try:
                impl = BashCompletionTypes.File('*.txt')

                with pytest.raises(ArgumentTypeError) as ate:
                    impl('non-existing-directory/')
                assert 'non-existing-directory/ does not exist' in str(ate)

                with pytest.raises(ArgumentTypeError) as ate:
                    impl('test-dir/')
                assert 'test-dir/ is not a file' in str(ate)

                with pytest.raises(ArgumentTypeError) as ate:
                    impl('test.xml')
                assert 'test.xml does not match *.txt' in str(ate)

                assert impl('test.txt') == 'test.txt'

                impl = BashCompletionTypes.File('*.txt', '*.json')

                with pytest.raises(ArgumentTypeError) as ate:
                    impl('test.xml')
                assert 'test.xml does not match *.txt' in str(ate)

                assert impl('test.txt') == 'test.txt'
                assert impl('test.json') == 'test.json'
            finally:
                chdir(CWD)
                rmtree(test_context_root, onerror=onerror)

        def test_list_files(self, tmpdir_factory: TempdirFactory) -> None:
            test_context = tmpdir_factory.mktemp('test_context')
            test_dir = test_context.mkdir('test-dir')
            test_dir.join('test.txt').write('sub test.txt file')
            test_context.mkdir('.hidden').join('hidden.txt').write('hidden.txt file')
            test_context.join('test.txt').write('test.txt file')
            test_context.join('test.json').write('{"value": "test.json file"}')
            test_context.join('test.xml').write('<value>test.xml file</value>')
            test_context_root = str(test_context)

            chdir(test_context_root)

            try:
                impl = BashCompletionTypes.File('*.txt')
                assert impl.list_files(None) == {
                    'test.txt': 'file',
                    'test-dir': 'dir',
                }
                assert impl.list_files('te') == {
                    'test.txt': 'file',
                    'test-dir': 'dir',
                }

                assert impl.list_files('test-') == {
                    'test-dir': 'dir',
                }

                assert impl.list_files(f'test-dir{sep}') == {
                    f'test-dir{sep}test.txt': 'file',
                }

                impl = BashCompletionTypes.File('*.txt', '*.json', '*.xml')
                assert impl.list_files('te') == {
                    'test.txt': 'file',
                    'test.json': 'file',
                    'test.xml': 'file',
                    'test-dir': 'dir',
                }
            finally:
                chdir(CWD)
                rmtree(test_context_root, onerror=onerror)
