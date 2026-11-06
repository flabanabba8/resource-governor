import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('governor_gpu_package', root/'__init__.py', submodule_search_locations=[str(root)])
plugin = importlib.util.module_from_spec(spec); sys.modules[spec.name] = plugin; spec.loader.exec_module(plugin)
from governor_gpu_package import core, gpu

class GPUProcessTests(unittest.TestCase):
 def test_filters_process_and_preserves_unknown_memory(self):
  response = type('Response', (), {'returncode': 0, 'stdout': b'101, 1024\n999, 30\n101, N/A\n'})()
  with patch.object(core, 'measure', return_value={'start_ticks': 1}), patch.object(gpu.shutil, 'which', return_value='/usr/bin/nvidia-smi'), patch.object(gpu.subprocess, 'run', return_value=response):
   result = gpu.gpu_process(101)
  self.assertEqual(result['reported_entries_mib'], [1024, None]); self.assertEqual(result['status'], 'reported')
  self.assertNotIn('999', str(result))
 def test_absence_is_unknown_and_pid_reuse_rejected(self):
  response = type('Response', (), {'returncode': 0, 'stdout': b''})()
  with patch.object(core, 'measure', return_value={'start_ticks': 1}), patch.object(gpu.shutil, 'which', return_value='/usr/bin/nvidia-smi'), patch.object(gpu.subprocess, 'run', return_value=response):
   result = gpu.gpu_process(101)
  self.assertEqual(result['status'], 'not_reported'); self.assertEqual(result['reported_entries_mib'], [])
  with patch.object(core, 'measure', side_effect=[{'start_ticks': 1}, {'start_ticks': 2}]), patch.object(gpu.shutil, 'which', return_value='/usr/bin/nvidia-smi'), patch.object(gpu.subprocess, 'run', return_value=response):
   with self.assertRaisesRegex(RuntimeError, 'identity changed'): gpu.gpu_process(101)

if __name__ == '__main__': unittest.main()
