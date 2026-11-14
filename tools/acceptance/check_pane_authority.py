"""Run only existing tests that exercise pane control, plus the guard contracts.

Select literal control calls and their same-class helpers, rather than running
whole feature suites. --list prints the exact selected methods before execution.
"""
import ast
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
OPERATIONS = {'close', 'rename', 'move', 'focus', 'session close'}


def selections():
    paths = sorted({*ROOT.glob('items/*/test*.py'), *ROOT.glob('src/test*.py'), *ROOT.glob('tools/*/test*.py')})
    for path in paths:
        tree = ast.parse(path.read_text())
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
            selected = set()
            for name, method in methods.items():
                strings = {n.value for n in ast.walk(method) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
                attributes = {n.func.attr for n in ast.walk(method) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
                if (('surfaces' in strings and strings & OPERATIONS)
                    or any('surfaces' in value and any(op in value for op in OPERATIONS) for value in strings)
                    or strings & {'surfaces_close', 'surfaces_rename', 'surfaces_focus', 'surfaces_move'}
                    or ('take' in strings and ('clutch' in strings or 'clutch' in attributes))
                    or strings & {'teerex_clutch_take'}
                    or ('surface' in attributes and strings & OPERATIONS)
                    or attributes & {'rename_command', 'move_command'}
                    or ('--focus' in strings and attributes & {'surface', 'global_command'})
                    or strings & {'block.event', 'com.superlogical.terminal.write', 'com.superlogical.terminal.key'}
                    or ('rex_json' in attributes and strings & {'key', 'type'})
                    or (path.parent.name in {'jobs', 'agents'} and name.startswith('test_') and 'present' in strings)
                    or (path.parent.name == 'agents' and name.startswith('test_') and 'detached' in name)
                    or (path.parent.name == 'waiting' and name.startswith('test_') and
                        ('focus' in name or any(isinstance(n, ast.keyword) and n.arg == 'focus' for n in ast.walk(method))
                         or 'put-away' in strings))
                    or (path.parent.name in {'run', 'offstage', 'replay'} and name.startswith('test_')
                        and any(word in name for word in ('close', 'resize')))
                    or (path.parent.name == 'replay' and name.startswith('test_') and
                        any(isinstance(n, ast.keyword) and n.arg in {'key', 'write', 'paste'} for n in ast.walk(method)))
                    or (path.name == 'test_pane_guard.py' and name.startswith('test_'))):
                    selected.add(name)
            while True:
                users = {name for name, method in methods.items() if any(
                    isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == 'self'
                    and n.func.attr in selected for n in ast.walk(method))}
                if users <= selected:
                    break
                selected |= users
            for name in methods:
                if name.startswith('test_') and name in selected:
                    yield path, cls.name, name


def run():
    selected = list(selections())
    if '--list' in sys.argv:
        for path, cls, method in selected:
            print(str(path.relative_to(ROOT)) + '::' + cls + '.' + method)
        return 0
    suite = unittest.TestSuite()
    modules = {}
    for path, cls, method in selected:
        if path not in modules:
            name = '_authority_' + '_'.join(path.relative_to(ROOT).with_suffix('').parts)
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            modules[path] = module
        suite.addTest(getattr(modules[path], cls)(method))
    print('Selected', suite.countTestCases(), 'pane-control tests; no whole-suite discovery.', flush=True)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return not result.wasSuccessful()


def main():
    if '--list' in sys.argv:
        return run()
    # Legacy fixtures also invoke CLI helpers without their own environment map.
    # Those calls must never consult a personal boards/creator/agent store.
    with tempfile.TemporaryDirectory(prefix='pane-authority-environment-') as root:
        root = Path(root)
        os.environ.update(HOME=str(root), XDG_STATE_HOME=str(root / 'state'),
                          TEEREX_BOARDS_STORE=str(root / 'boards'), AGENT_REGISTRY=str(root / 'agents'))
        if os.environ.get('REX_BIN'):
            os.environ['PATH'] = str(Path(os.environ['REX_BIN']).parent) + os.pathsep + os.environ.get('PATH', '')
        return run()


if __name__ == '__main__':
    sys.exit(main())
