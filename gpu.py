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


def gpu_process(pid):
    """Inspect only one same-user process; absent compute entries are not zero."""
    from .core import measure
    first = measure(pid)
    binary = shutil.which('nvidia-smi')
    if not binary:
        raise ValueError('nvidia-smi is unavailable; NVIDIA telemetry is unsupported')
    try:
        result = subprocess.run([binary, '--query-compute-apps=pid,used_memory', '--format=csv,noheader,nounits'],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                env={'PATH': os.defpath, 'LANG': 'C.UTF-8'}, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('GPU process status could not be read') from exc
    if result.returncode or len(result.stdout) > 65536:
        raise RuntimeError('GPU process status could not be read')
    after = measure(pid)
    if first['start_ticks'] != after['start_ticks']:
        raise RuntimeError('Process identity changed during GPU query')
    try:
        rows = result.stdout.decode('ascii').splitlines()
        values = []
        for row in rows:
            parts = [x.strip() for x in row.split(',')]
            if len(parts) != 2 or not parts[0].isdigit():
                raise ValueError()
            if int(parts[0]) == pid:
                values.append(int(parts[1]) if parts[1].isdigit() else None)
    except (ValueError, UnicodeError) as exc:
        raise RuntimeError('GPU process response was incomplete') from exc
    return {'pid': pid, 'reported_entries_mib': values,
            'status': 'reported' if values else 'not_reported',
            'notice': 'Only NVIDIA compute-process entries are queried; graphics use and unavailable memory may be omitted. Absence is not zero usage. No budget is enforced or reserved.'}
