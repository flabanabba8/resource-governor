"""One plugin-owned CPU video conversion with Linux resource limits."""
import fcntl
import hashlib
import json
import time
import os
from pathlib import Path
import shutil
import signal
import subprocess
import uuid

PRIVATE = {'.ssh', '.gnupg', '.aws', '.azure', '.codex', '.docker', '.kube', '.pki', '.config', '.hermes'}
MAX_SOURCE = 256 * 1024**2
MAX_OUTPUT = 256 * 1024**2


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def transcode(root, source_path, max_seconds, address_space_mb, cpu_seconds, wall_seconds, allow_profile_media=False):
    values = (max_seconds, address_space_mb, cpu_seconds, wall_seconds)
    if any(type(x) is not int for x in values) or not 1 <= max_seconds <= 60 or not 512 <= address_space_mb <= 16384 or not 1 <= cpu_seconds <= 60 or not 1 <= wall_seconds <= 60:
        raise ValueError('Use duration 1–60 s, address space 512–16384 MiB, and CPU/wall budgets 1–60 s')
    if type(allow_profile_media) is not bool: raise ValueError('allow_profile_media must be boolean')
    source = Path(source_path).expanduser()
    original_parts = source.parts
    if not source.is_absolute() or source.is_symlink() or any(x.casefold() in PRIVATE - {'.hermes'} for x in original_parts):
        raise ValueError('Choose an absolute non-symlink video outside private configuration')
    source = source.resolve(strict=True)
    profile_data = Path(root).resolve().parent
    profile_home = profile_data.parent if profile_data.name.casefold() == 'plugin-data' else None
    permitted_private_media = allow_profile_media and profile_home is not None and source.is_relative_to(profile_data)
    protected = any(x.casefold() == '.hermes' for x in original_parts) or any(x.casefold() == '.hermes' for x in source.parts) or (profile_home is not None and source.is_relative_to(profile_home))
    if (any(x.casefold() in PRIVATE - {'.hermes'} for x in source.parts) or protected and not permitted_private_media or
        not source.is_file() or source.suffix.lower() not in ('.mp4', '.mkv', '.mov', '.webm')):
        raise ValueError('Choose a local video outside private configuration or explicitly allow active-profile plugin media')
    if source.stat().st_size > MAX_SOURCE: raise ValueError('Source exceeds 256 MiB')
    ffmpeg, ffprobe, prlimit = shutil.which('ffmpeg'), shutil.which('ffprobe'), shutil.which('prlimit')
    if not ffmpeg or not ffprobe or not prlimit: raise ValueError('Install ffmpeg, ffprobe and Linux prlimit')
    directory = Path(root).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / '.job.lock').open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('Another governed video job is running') from None
        before = sha(source)
        name = uuid.uuid4().hex
        partial, output = directory/(name+'.partial.mp4'), directory/(name+'.mp4')
        command = [prlimit, '--as='+str(address_space_mb*1024**2), '--cpu='+str(cpu_seconds),
            '--fsize='+str(MAX_OUTPUT), '--core=0', '--', ffmpeg, '-v','error','-nostdin','-n',
            '-threads','1','-filter_threads','1','-hwaccel','none','-protocol_whitelist','file,pipe',
            '-i',str(source),'-t',str(max_seconds),'-map','0:v:0','-map','0:a?',
            '-map_metadata','-1','-map_chapters','-1','-c:v','libx264','-preset','veryfast','-threads','1','-c:a','aac','-f','mp4',str(partial)]
        env = {'PATH': os.defpath, 'LANG': 'C.UTF-8'}
        started = time.monotonic()
        def run_limited(args, capture=False):
            remaining = wall_seconds - (time.monotonic() - started)
            if remaining <= 0: raise RuntimeError('Video job exceeded its wall-time budget')
            process = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE if capture else subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=env, start_new_session=True)
            try:
                stdout, _ = process.communicate(timeout=remaining)
            except BaseException as exc:
                if process.poll() is None:
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    process.communicate()
                if isinstance(exc, subprocess.TimeoutExpired):
                    raise RuntimeError('Video job exceeded its wall-time budget') from exc
                raise
            if process.returncode: raise RuntimeError('Video job failed or exceeded a process limit')
            return stdout if capture else b''
        try:
            run_limited(command)
            if not partial.is_file() or not partial.stat().st_size:
                raise RuntimeError('Video job produced an empty output')
            verify = [prlimit, '--as='+str(address_space_mb*1024**2), '--cpu='+str(min(cpu_seconds,5)),
                '--fsize='+str(MAX_OUTPUT), '--core=0', '--', ffprobe, '-v','error',
                '-show_entries','format=duration:stream=codec_type','-of','json',str(partial)]
            info = json.loads(run_limited(verify, capture=True))
            duration = float(info.get('format', {}).get('duration', 0))
            if not 0 < duration <= max_seconds + 1 or not any(x.get('codec_type') == 'video' for x in info.get('streams', [])):
                raise RuntimeError('Output metadata verification failed')
            if sha(source) != before: raise ValueError('Source changed during conversion; output discarded')
            output_sha = sha(partial)
            os.replace(partial, output)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
    return {'output_path': str(output), 'source_sha256': before, 'output_sha256': output_sha,
            'bytes': output.stat().st_size, 'duration_seconds': duration, 'address_space_mb': address_space_mb,
            'encoding_cpu_seconds_limit': cpu_seconds, 'verification_cpu_seconds_limit': min(cpu_seconds,5),
            'notice': 'Address-space and CPU-time limits apply separately to encoding and metadata verification. This CPU-only job has a shared wall-time limit. Output is not fully decoded or visually reviewed; limits do not govern other processes or GPU memory.'}
