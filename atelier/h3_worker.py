"""Session-owned FreeVideo coordinator, running in H3's isolated environment.

The upstream resident worker retains compatible model weights. Per-generation
CLI processes still own request diagnostics and memory guards, but no longer
own the lifetime of the GPU worker. IPC is confined to the session's scratch.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from atelier.lifecycle import write_json


class Coordinator:
    def __init__(self, folder, source, owner, processes, environment):
        self.folder, self.source = Path(folder), Path(source)
        self.owner, self.processes = owner, processes
        self.environment = dict(environment)

    def run(self, request):
        from freevideo_engine.resident_process import ENV
        environment = dict(self.environment)
        environment[ENV] = self.owner.start(self.folder, self.source, sys.executable, environment)
        self.owner.active = True
        process = None
        try:
            with Path(request['log']).open('w', encoding='utf-8') as log:
                process = self.processes.popen(
                    [sys.executable, '-u', '-m', 'freevideo_engine', 'generate', *request['arguments']],
                    env=environment, cwd=self.source, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True, supervise=True)
                code = process.wait()
            if code:
                self.owner.close()
            return {'id': request['id'], 'returncode': code}
        finally:
            if process is not None and process.poll() is None:
                self.processes.stop(process)
            self.owner.active = False

    def close(self):
        self.owner.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--parent', type=int, required=True)
    args = parser.parse_args()
    import psutil
    from freevideo_engine.resident_process import SessionOwner
    from freevideo_engine import processes
    parent = psutil.Process(args.parent)
    created = parent.create_time()
    stopped = threading.Event()

    def watch_parent():
        while not stopped.wait(.5):
            try:
                if parent.is_running() and parent.create_time() == created:
                    continue
            except psutil.Error:
                pass
            # Upstream children are supervised; their leases and model memory
            # must not outlive a crashed studio or its coordinator.
            os._exit(72)

    threading.Thread(target=watch_parent, daemon=True).start()
    coordinator = Coordinator(args.folder, args.source, SessionOwner(), processes, os.environ)
    args.folder.mkdir(parents=True, exist_ok=True)
    write_json(args.folder / 'ready.json', {'pid': os.getpid()})
    try:
        while True:
            pending = args.folder / 'request.json'
            if not pending.is_file():
                time.sleep(.1)
                continue
            request = json.loads(pending.read_text(encoding='utf-8'))
            pending.unlink()
            try:
                response = coordinator.run(request)
            except Exception as error:
                coordinator.close()
                response = {'id': request['id'], 'returncode': 1, 'error': str(error)[:1800]}
            write_json(args.folder / 'response.json', response)
    finally:
        stopped.set()
        coordinator.close()


if __name__ == '__main__':
    main()
