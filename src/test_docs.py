"""Focused docs page/allowlist/lifetime tests; no personal terminal reads."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

with patch.object(sys, 'argv', ['docs.py', '/bin/teerex', '["send", "docs", "observe", "boardfeed", "maneuvers"]']):
    spec = importlib.util.spec_from_file_location('docs', Path(__file__).with_name('docs.py'))
    docs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(docs)


class DocsTest(unittest.TestCase):
    def test_page_binds_live_help_and_readme_without_running_snippets(self):
        replies = [subprocess.CompletedProcess([], 0, '# Send\n```sh\nrm dangerous\n```\n'),
                   subprocess.CompletedProcess([], 0, 'Usage: teerex send')]
        with patch.object(docs, 'run', side_effect=replies) as run:
            page = docs.page('send')
        self.assertIn('send-example-1', page)
        self.assertIn('send-help', page)
        self.assertIn('rm dangerous', page)
        self.assertIn('Usage: teerex send', page)
        self.assertEqual(run.call_args_list[0].args[0], ['/bin/teerex', 'docs', '_readme', 'send'])
        self.assertEqual(run.call_args_list[1].args[0], ['/bin/teerex', 'send', '--help'])

    def test_all_try_argv_are_readonly_and_no_source_snippet_is_allowed(self):
        self.assertNotIn('boardfeed', docs.COMMANDS)
        for key, argv in docs.EXAMPLES.items():
            if key.endswith('-self'):
                self.assertIn('{session}', argv)
                self.assertIn('{block}', argv)
                continue
            self.assertTrue(argv == ['--version'] or len(argv) == 2 and argv[1] == '--help')
        with patch.object(sys, 'argv', ['docs.py', '/bin/teerex', '[]', 'try', 'send-example-1']), patch.object(docs, 'surface') as surface:
            with self.assertRaisesRegex(ValueError, 'unknown or unsafe'):
                docs.main()
            surface.assert_not_called()

    def test_try_removes_directory_and_restores_terminal(self):
        seen = []
        def execute(argv, cwd):
            self.assertTrue(Path(cwd).is_dir())
            seen.append(cwd)
            return subprocess.CompletedProcess(argv, 0)
        with tempfile.TemporaryFile() as terminal, patch('builtins.open', return_value=terminal), patch.object(docs.subprocess, 'run', side_effect=execute), patch.object(docs.termios, 'tcgetattr', return_value='before'), patch.object(docs.termios, 'tcsetattr') as restore, patch.object(docs.tty, 'setraw'):
            self.assertEqual(docs.try_runner('send-help'), 0)
        self.assertFalse(Path(seen[0]).exists())
        restore.assert_called_once()


if __name__ == '__main__':
    unittest.main()
