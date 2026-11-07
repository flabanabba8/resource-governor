"""Read-only Linux process resource monitoring with PID reuse detection."""
import json
import math
import os
import sys
from pathlib import Path
import time
import uuid


def stat_fields(text):
    close = text.rfind(')')
    if close < 0:
        raise RuntimeError('Cannot parse process statistics')
    fields = text[close+2:].split()
    if len(fields) < 20:
        raise RuntimeError('Cannot parse process statistics')
    return fields


def measure(pid):
    if sys.platform != 'linux': raise ValueError('Process monitoring requires Linux /proc')
    if type(pid) is not int or pid < 1: raise ValueError('Invalid PID')
    proc = Path('/proc') / str(pid)
    if proc.stat().st_uid != os.getuid(): raise ValueError('Process belongs to another user')
    first = stat_fields((proc / 'stat').read_text())
    status = (proc / 'status').read_text()
    fields = stat_fields((proc / 'stat').read_text())
    if fields[19] != first[19] or proc.stat().st_uid != os.getuid():
        raise RuntimeError('Process identity changed during measurement')
    rss = next((int(line.split()[1]) for line in status.splitlines() if line.startswith('VmRSS:')), None)
    if rss is None: raise RuntimeError('RSS unavailable for this process')
    return {'start_ticks': int(fields[19]), 'cpu_ticks': int(fields[11]) + int(fields[12]), 'rss_kib': rss, 'at': time.monotonic()}


class Governor:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def start(self, pid, max_rss_mb, max_cpu_percent):
        if any(type(x) not in (int, float) or not math.isfinite(x) or x <= 0 for x in (max_rss_mb, max_cpu_percent)):
            raise ValueError('Budgets must be positive finite numbers')
        initial = measure(pid)
        boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        watch_id = uuid.uuid4().hex
        state = {'pid': pid, 'initial': initial, 'boot_id': boot_id, 'max_rss_mb': max_rss_mb, 'max_cpu_percent': max_cpu_percent}
        with os.fdopen(os.open(self.root / (watch_id + '.json'), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
            json.dump(state, f)
        return {'watch_id': watch_id, 'pid': pid, 'rss_mb': initial['rss_kib'] / 1024}

    def check(self, watch_id):
        if sys.platform != 'linux': raise ValueError('Process monitoring requires Linux /proc')
        if not isinstance(watch_id, str) or len(watch_id) != 32 or any(x not in '0123456789abcdef' for x in watch_id): raise ValueError('Invalid watch ID')
        path = self.root / (watch_id + '.json')
        if path.is_symlink(): raise ValueError('Invalid watch path')
        data = json.loads(path.read_text())
        if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != data['boot_id']: raise ValueError('System restarted; create a new watch')
        now = measure(data['pid'])
        initial = data['initial']
        if now['start_ticks'] != initial['start_ticks']: raise ValueError('PID was reused; create a new watch')
        elapsed = now['at'] - initial['at']
        if elapsed <= 0: raise RuntimeError('Not enough time elapsed')
        cpu = (now['cpu_ticks'] - initial['cpu_ticks']) / os.sysconf('SC_CLK_TCK') / elapsed * 100
        if cpu < 0: raise RuntimeError('Invalid CPU counter')
        rss = now['rss_kib'] / 1024
        return {'pid': data['pid'], 'elapsed_seconds': elapsed, 'rss_mb': rss, 'average_cpu_percent_one_core': cpu,
                'rss_budget_exceeded': rss > data['max_rss_mb'], 'cpu_budget_exceeded': cpu > data['max_cpu_percent'],
                'notice': 'Observation only: no process limits are enforced. RSS excludes child processes and GPU memory; CPU is averaged since watch start.'}
