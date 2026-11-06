import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('governor_gpu', Path(__file__).parents[1] / 'gpu.py')
gpu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gpu)


class GpuStatusTests(unittest.TestCase):
    def test_device_memory_and_scrubbed_environment(self):
        result = type('Result', (), {'returncode': 0, 'stdout': b'1024, 8192\n2048, 16384\n'})()
        with patch.object(gpu.shutil, 'which', return_value='/usr/bin/nvidia-smi'), patch.dict(gpu.os.environ, {'INWORLD_API_KEY': 'fixture-only-value'}), patch.object(gpu.subprocess, 'run', return_value=result) as run:
            status = gpu.gpu_status()
        self.assertEqual([x['free_mib'] for x in status['devices']], [7168, 14336])
        self.assertNotIn('INWORLD_API_KEY', run.call_args.kwargs['env'])
        self.assertIn('does not enforce', status['notice'])

    def test_bad_or_unavailable_response_is_not_zero_usage(self):
        with patch.object(gpu.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'unavailable'): gpu.gpu_status()
        result = type('Result', (), {'returncode': 0, 'stdout': b'N/A, 8192\n'})()
        with patch.object(gpu.shutil, 'which', return_value='/usr/bin/nvidia-smi'), patch.object(gpu.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'incomplete'): gpu.gpu_status()


if __name__ == '__main__': unittest.main()
