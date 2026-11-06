import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('governor_core', Path(__file__).parents[1] / 'core.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

class GovernorTests(unittest.TestCase):
    def test_new_watch_record_is_private_under_permissive_umask(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
            previous = os.umask(0)
            try:
                watch = core.Governor(tmp).start(os.getpid(), 100, 100)
                self.assertEqual((Path(tmp)/(watch['watch_id']+'.json')).stat().st_mode & 0o777, 0o600)
            finally:
                os.umask(previous)
    def test_watch_current_process(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
            governor = core.Governor(tmp)
            watch = governor.start(os.getpid(), 0.001, 100000)
            result = governor.check(watch['watch_id'])
            self.assertTrue(result['rss_budget_exceeded'])
            self.assertFalse(result['cpu_budget_exceeded'])

    def test_pid_reuse_is_rejected(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
            governor = core.Governor(tmp)
            watch = governor.start(os.getpid(), 100, 100)
            measured = core.measure(os.getpid())
            measured['start_ticks'] += 1
            with patch.object(core, 'measure', return_value=measured):
                with self.assertRaisesRegex(ValueError, 'reused'):
                    governor.check(watch['watch_id'])

    def test_process_identity_change_during_measurement_is_rejected(self):
        original = Path.read_text
        calls = 0
        def swapped(path, *args, **kwargs):
            nonlocal calls
            text = original(path, *args, **kwargs)
            if path == Path('/proc') / str(os.getpid()) / 'stat':
                calls += 1
                if calls == 2:
                    close = text.rfind(')')
                    fields = text[close+2:].split()
                    fields[19] = str(int(fields[19]) + 1)
                    return text[:close+2] + ' '.join(fields)
            return text
        with patch.object(Path, 'read_text', swapped):
            with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                core.measure(os.getpid())

if __name__ == '__main__':
    unittest.main()
