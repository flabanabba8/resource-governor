import fcntl
import importlib.util
import os
import resource
import time
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('governor_transcode_fixture', Path(__file__).parents[1] / 'transcode.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

@unittest.skipUnless(all(shutil.which(x) for x in ('ffmpeg','ffprobe','prlimit')), 'Linux FFmpeg and prlimit required')
class TranscodeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.root = Path(self.tmp.name)
        self.source = self.root/'source.mp4'
        subprocess.run(['ffmpeg','-v','error','-nostdin','-f','lavfi','-i','color=size=64x64:rate=10:color=blue',
                        '-t','1','-c:v','libx264','-threads','1',str(self.source)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=15,
                       env={'PATH':os.defpath,'LANG':'C.UTF-8'})
    def tearDown(self): self.tmp.cleanup()

    def test_real_cpu_job_and_credential_scrubbing(self):
        before = self.source.read_bytes()
        seen_env, observed_limits = [], []
        original = subprocess.Popen
        def start(*args, **kwargs):
            seen_env.append(kwargs['env'])
            process = original(*args, **kwargs)
            deadline = time.monotonic() + 2
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    memory = resource.prlimit(process.pid, resource.RLIMIT_AS)
                    cpu = resource.prlimit(process.pid, resource.RLIMIT_CPU)
                    if memory[0] == 2048 * 1024**2 and cpu[0] in (10, 5):
                        observed_limits.append((memory[0], cpu[0]))
                        break
                except ProcessLookupError:
                    break
                time.sleep(.001)
            return process
        with patch.dict(os.environ, {'INWORLD_API_KEY':'fixture-only-value'}), patch.object(core.subprocess, 'Popen', side_effect=start):
            result = core.transcode(self.root/'output', str(self.source), 1, 2048, 10, 20)
        self.assertTrue(Path(result['output_path']).is_file())
        self.assertGreater(result['duration_seconds'], 0)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(len(seen_env), 2)
        self.assertEqual([x[1] for x in observed_limits], [10, 5])
        self.assertTrue(all('INWORLD_API_KEY' not in env for env in seen_env))

    def test_timeout_terminates_only_owned_group(self):
        process = Mock()
        process.pid = 98765
        process.poll.return_value = None
        process.communicate.side_effect = [subprocess.TimeoutExpired('fixture', 1), (b'', None)]
        with patch.object(core.subprocess, 'Popen', return_value=process), patch.object(core.os, 'killpg') as kill:
            with self.assertRaisesRegex(RuntimeError, 'wall-time'):
                core.transcode(self.root/'output', str(self.source), 1, 2048, 10, 1)
        kill.assert_called_once_with(process.pid, core.signal.SIGKILL)
        self.assertEqual(list((self.root/'output').glob('*.mp4')), [])

    def test_explicit_active_profile_media_access(self):
        private = self.root/'.hermes'
        sibling = private/'plugin-data'/'tutorial'
        sibling.mkdir(parents=True)
        video = sibling/'demo.mp4'
        video.write_bytes(self.source.read_bytes())
        output = private/'plugin-data'/'resource-governor'
        with self.assertRaisesRegex(ValueError, 'private configuration'):
            core.transcode(output, str(video), 1, 2048, 10, 20)
        result = core.transcode(output, str(video), 1, 2048, 10, 20, allow_profile_media=True)
        self.assertTrue(Path(result['output_path']).is_file())
        unrelated = private/'unrelated.mp4'
        unrelated.write_bytes(self.source.read_bytes())
        with self.assertRaisesRegex(ValueError, 'private configuration'):
            core.transcode(output, str(unrelated), 1, 2048, 10, 20, allow_profile_media=True)

    def test_custom_profile_configuration_stays_blocked(self):
        profile = self.root/'custom-profile'
        profile.mkdir()
        source = profile/'unrelated.mp4'
        source.write_bytes(self.source.read_bytes())
        with self.assertRaisesRegex(ValueError, 'private configuration'):
            core.transcode(profile/'plugin-data'/'resource-governor', str(source), 1, 2048, 10, 20, allow_profile_media=True)

    def test_busy_queue_does_not_start_job(self):
        output = self.root/'output'
        output.mkdir()
        with (output/'.job.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, 'Another governed'):
                core.transcode(output, str(self.source), 1, 2048, 10, 20)

if __name__ == '__main__': unittest.main()
