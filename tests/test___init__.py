from os import chdir, environ, path, getcwd
from shutil import rmtree
from inspect import getfile
from importlib import reload

from _pytest.tmpdir import TempPathFactory

from .helpers import onerror

CWD = getcwd()


def test___import__(tmp_path_factory: TempPathFactory) -> None:
    test_context = tmp_path_factory.mktemp('test_context')
    test_context_root = str(test_context)

    chdir(test_context_root)

    try:
        environ['GRIZZLY_MOUNT_CONTEXT'] = '/var/tmp'

        import grizzly_cli
        reload(grizzly_cli)

        static_context = path.join(path.dirname(getfile(grizzly_cli)), 'static')

        assert grizzly_cli.__version__ == '0.0.0'
        assert grizzly_cli.EXECUTION_CONTEXT == test_context_root
        assert grizzly_cli.MOUNT_CONTEXT == '/var/tmp'
        assert grizzly_cli.STATIC_CONTEXT == static_context
        assert grizzly_cli.PROJECT_NAME == path.basename(test_context_root)
        assert len(grizzly_cli.SCENARIOS) == 0
    finally:
        chdir(CWD)
        rmtree(test_context_root, onerror=onerror)
        try:
            del environ['GRIZZLY_MOUNT_CONTEXT']
        except:
            pass
