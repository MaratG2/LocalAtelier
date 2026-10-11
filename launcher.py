"""Start, reopen, restart and stop only this checkout's local studio."""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
import webbrowser
from pathlib import Path

import httpx
import psutil

from atelier.lifecycle import InstanceLock, RESTART_EXIT, read_json, write_json

ROOT = Path(__file__).resolve().parent
HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def api(port, path='/status', method='GET', timeout=3):
    with httpx.Client(trust_env=False, timeout=timeout) as client:
        response = client.request(method, f'http://127.0.0.1:{port}/api{path}')
        response.raise_for_status()
        return response.json()


def status(port):
    try:
        return api(port, timeout=5)
    except (httpx.HTTPError, ValueError):
        return None


def owned_status(value, data):
    return bool(isinstance(value, dict) and value.get('name') == 'Local Atelier'
                and Path(value.get('data_path', '')).resolve() == data.resolve())


def listener_pids(port):
    return {c.pid for c in psutil.net_connections(kind='tcp')
            if c.status == psutil.CONN_LISTEN and c.laddr.port == port and c.pid}


def owned_process(process, root=ROOT):
    """Match both the script and checkout, never just a process name or port."""
    try:
        args = process.cmdline()
        cwd = Path(process.cwd()).resolve()
        if not args or cwd != root.resolve():
            return False
        script = next((arg for arg in args[1:] if not arg.startswith('-')), '')
        # The old launcher uses only the optional -u flag before run.py.
        script_path = Path(script)
        if not script_path.is_absolute():
            script_path = cwd / script_path
        return script_path.resolve() == (root / 'run.py').resolve() and Path(args[0]).name.lower() in {'python', 'python.exe', 'python3'}
    except (psutil.Error, OSError):
        return False


def migrate_legacy(port, data):
    """One-time takeover of an idle pre-launcher studio, with identity checks."""
    current = status(port)
    if not owned_status(current, data) or current.get('launcher', {}).get('managed'):
        raise RuntimeError('The occupied port is not this checkout\'s legacy studio. It was left running.')
    listeners = listener_pids(port)
    if len(listeners) != 1:
        raise RuntimeError('Could not identify one studio process. No process was stopped.')
    process = psutil.Process(next(iter(listeners)))
    if not owned_process(process):
        raise RuntimeError('The listener does not run this checkout\'s run.py. It was left running.')
    parent = process.parent()
    wrapper = parent if parent and owned_process(parent) and parent.cmdline() == process.cmdline() else None
    temporary = data / 'temporary'
    if temporary.exists() and any(p.is_dir() for p in temporary.iterdir()):
        return False
    jobs = api(port, '/jobs')
    models = api(port, '/models', timeout=15)
    if any(job['status'] in {'queued', 'running'} for job in jobs) or any(model.get('busy') for model in models):
        return False
    # The legacy release API checks active jobs across every session and frees
    # only workers owned by its Runtime before the idle web process is replaced.
    try:
        api(port, '/runtime/release', 'POST', timeout=90)
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 400:
            return False  # A generation started while identity was checked.
        raise
    if any(job['status'] in {'queued', 'running'} for job in api(port, '/jobs')):
        return False
    if not owned_status(status(port), data) or not process.is_running() or not owned_process(process):
        raise RuntimeError('Studio identity changed during restart. No process was stopped.')
    print(f'Replacing verified idle legacy studio PID {process.pid}.', flush=True)
    # psutil retains creation time and checks PID reuse before termination.
    process.terminate()
    process.wait(timeout=15)
    if wrapper and wrapper.is_running():
        try:
            wrapper.wait(timeout=3)
        except psutil.TimeoutExpired:
            if owned_process(wrapper):
                wrapper.terminate()
                wrapper.wait(timeout=10)
    return True


def supervise(port, data):
    folder = data / 'runtime' / 'launcher'
    try:
        lock = InstanceLock(folder / 'studio.lock')
        lock.__enter__()
    except RuntimeError:
        return 0  # Concurrent Start clicks converge on the existing launcher.
    identity = {'session_id': uuid.uuid4().hex, 'supervisor_pid': os.getpid(),
                'port': port, 'url': f'http://127.0.0.1:{port}/', 'root': str(ROOT)}
    try:
        current = status(port)
        if not current and listener_pids(port):
            raise RuntimeError('Port is occupied but its identity cannot be verified. Nothing was stopped.')
        if current:
            if not owned_status(current, data):
                raise RuntimeError('Port is occupied by a different application. Nothing was stopped.')
            write_json(folder / 'state.json', {**identity, 'state': 'waiting', 'reason': 'Waiting for generations, model operations or incognito sessions in the old studio to finish'})
            while not migrate_legacy(port, data):
                time.sleep(3)
        while True:
            identity['instance_id'] = uuid.uuid4().hex
            # Remove only a command acknowledged by the previous child; never
            # replay restart endlessly into every subsequent server instance.
            command_path = folder / 'command.json'
            command = read_json(command_path)
            previous = read_json(folder / 'state.json')
            if command.get('session_id') == identity['session_id'] and command.get('id') == previous.get('request_id'):
                command_path.unlink(missing_ok=True)
            write_json(folder / 'state.json', {**identity, 'state': 'starting'})
            env = {**os.environ, 'ATELIER_MANAGED': json.dumps(identity), 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
            with (folder / 'server.log').open('a', encoding='utf-8') as log:
                process = subprocess.Popen([sys.executable, '-u', str(ROOT / 'run.py'), '--port', str(port), '--data-dir', str(data)],
                                           cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                           stdin=subprocess.DEVNULL, creationflags=HIDDEN)
                code = process.wait()
            if code == RESTART_EXIT:
                continue
            write_json(folder / 'state.json', {**identity, 'state': 'stopped' if code == 0 else 'error',
                                               'reason': None if code == 0 else f'Server exited ({code}). See {folder / "server.log"}'})
            return code
    except Exception as error:
        write_json(folder / 'state.json', {**identity, 'state': 'error', 'reason': str(error)})
        print(str(error), file=sys.stderr, flush=True)
        return 1
    finally:
        lock.__exit__()


def control(action, port, data, no_browser):
    folder = data / 'runtime' / 'launcher'
    folder.mkdir(parents=True, exist_ok=True)
    current = status(port)
    state = read_json(folder / 'state.json')
    old_session = state.get('session_id')
    if state.get('port') and state['port'] != port and owned_status(status(state['port']), data):
        raise RuntimeError(f'This workspace already runs on port {state["port"]}. Use that port or Stop.cmd first.')
    initial_instance = (current or {}).get('launcher', {}).get('instance_id')
    managed = owned_status(current, data) and current.get('launcher', {}).get('managed')
    if current and not owned_status(current, data):
        raise RuntimeError('Port is occupied by another application. Nothing was stopped.')
    if managed and state.get('instance_id') != initial_instance:
        raise RuntimeError('Launcher identity could not be verified. Nothing was stopped.')
    if action == 'start' and managed:
        print(f'Local Atelier is already running: http://127.0.0.1:{port}/')
        if not no_browser:
            webbrowser.open(f'http://127.0.0.1:{port}/')
        return 0
    if action == 'stop' and not current:
        print('Local Atelier is already stopped.')
        return 0
    if action == 'stop' and not managed:
        raise RuntimeError('The old studio has no managed stop yet. Run Start.cmd once to enable it.')
    request_id = uuid.uuid4().hex
    if managed:
        write_json(folder / 'command.json', {'id': request_id, 'session_id': state['session_id'], 'action': action})
    else:
        with (folder / 'launcher.log').open('a', encoding='utf-8') as log:
            subprocess.Popen([sys.executable, '-u', str(ROOT / 'launcher.py'), '_serve', '--port', str(port), '--data-dir', str(data)],
                             cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             creationflags=HIDDEN, start_new_session=os.name != 'nt')
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        time.sleep(.5)
        state = read_json(folder / 'state.json')
        if state.get('state') == 'error' and (managed or state.get('session_id') != old_session):
            raise RuntimeError(state.get('reason', 'Launcher failed.'))
        if state.get('state') == 'waiting' and (state.get('request_id') == request_id or not managed):
            print('Scheduled automatically: ' + state.get('reason', 'Waiting until idle'))
            return 0
        if action == 'stop' and state.get('state') == 'stopped':
            print('Local Atelier and its GPU workers have stopped.')
            return 0
        running = status(port)
        if owned_status(running, data) and running.get('launcher', {}).get('managed'):
            instance = running['launcher']['instance_id']
            if action == 'start' or instance != initial_instance:
                print(f'Local Atelier is ready: http://127.0.0.1:{port}/\nBackend updates will reload automatically when idle.')
                if not no_browser:
                    webbrowser.open(f'http://127.0.0.1:{port}/')
                return 0
    raise RuntimeError(f'Startup is still pending. Details: {folder / "launcher.log"} and {folder / "server.log"}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'restart', 'stop', '_serve'], nargs='?', default='start')
    parser.add_argument('--port', type=int, default=7870)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    try:
        if not 1024 <= args.port <= 65535:
            raise RuntimeError('Choose a port between 1024 and 65535.')
        if not (ROOT / 'frontend/dist/index.html').is_file():
            raise RuntimeError('Run setup.ps1 once before starting Local Atelier.')
        if args.action == '_serve':
            return supervise(args.port, args.data_dir.resolve())
        return control(args.action, args.port, args.data_dir.resolve(), args.no_browser)
    except Exception as error:
        print(f'Local Atelier: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
