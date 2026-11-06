"""Read-only NVIDIA device-level memory observations."""
import os
import shutil
import subprocess


def gpu_status():
    binary = shutil.which('nvidia-smi')
    if not binary: raise ValueError('nvidia-smi is unavailable; NVIDIA telemetry is unsupported')
    try:
        result = subprocess.run([binary, '--query-gpu=memory.used,memory.total', '--format=csv,noheader,nounits'],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                env={'PATH': os.defpath, 'LANG': 'C.UTF-8'}, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('GPU memory status could not be read') from exc
    if result.returncode or len(result.stdout) > 8192: raise RuntimeError('GPU memory status could not be read')
    try:
        rows = result.stdout.decode('ascii').splitlines()
        if not 1 <= len(rows) <= 64: raise ValueError()
        devices = []
        for index, row in enumerate(rows):
            parts = [value.strip() for value in row.split(',')]
            if len(parts) != 2 or not all(value.isdigit() for value in parts): raise ValueError()
            used, total = map(int, parts)
            if total <= 0 or used > total: raise ValueError()
            devices.append({'index': index, 'used_mib': used, 'total_mib': total, 'free_mib': total-used})
    except (ValueError, UnicodeError) as exc:
        raise RuntimeError('GPU memory response was incomplete') from exc
    return {'devices': devices, 'notice': 'Point-in-time device-wide memory only. This does not enforce a budget, attribute usage to a process, or reserve free memory.'}
