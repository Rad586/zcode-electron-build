"""Compile with bounded execution and periodic progress output."""
import datetime
import os
from pathlib import Path
import subprocess
import sys
import threading
import time


def compile_runtime():
    root = Path('D:/ec/src')
    output = Path('D:/ec/compile.log')
    cores = os.cpu_count() or 2
    memory = int(os.environ.get('ZCODE_BUILD_MEMORY_GB', '8'))
    jobs = max(1, min(cores, memory // 4))
    command = ['cmd.exe', '/d', '/s', '/c',
               f'D:\\depot_tools\\autoninja.bat -C out/Release electron:electron_dist_zip -j {jobs}']
    print(f'Compiler concurrency: {jobs}; CPU: {cores}; RAM: {memory} GiB', flush=True)
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True,
                               encoding='utf-8', errors='replace')
    latest = ['Waiting for compiler output']

    def forward():
        with output.open('w', encoding='utf-8') as log:
            for line in process.stdout:
                log.write(line)
                log.flush()
                latest[0] = line.strip()
                print(line, end='', flush=True)

    reader = threading.Thread(target=forward, daemon=True)
    reader.start()
    while process.poll() is None:
        try:
            process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            elapsed = (time.monotonic() - started) / 60
            print(f'{datetime.datetime.now().isoformat()} elapsed={elapsed:.1f}m latest={latest[0]}', flush=True)
            if elapsed >= int(os.environ.get('ZCODE_COMPILE_MINUTES', '280')):
                print('Compile time budget exhausted; preserving uploaded compiler cache.', flush=True)
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], check=True)
                process.wait(timeout=30)
                reader.join(timeout=30)
                return 124
    reader.join(timeout=30)
    return process.returncode


if __name__ == '__main__':
    sys.exit(compile_runtime())
