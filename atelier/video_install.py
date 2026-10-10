"""Pinned, self-contained FreeVideo/VDN-H3 installation. No directory discovery."""
import hashlib
import json
import os
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from .models import python_at, CREATE_FLAGS

MANIFEST = Path(__file__).with_name('manifests') / 'vdn-h3.json'
SOURCES = {
    'FreeVideo': ('https://github.com/FlashML-org/FreeVideo.git', '0af617eb54dec1d8c06f9e7de2147c5b6a3f4772'),
    'ComfyUI': ('https://github.com/comfy-org/ComfyUI.git', '421a1c245c682c04d4325ba365f40c834c66f5b0'),
}


def manifest():
    return json.loads(MANIFEST.read_text(encoding='utf-8'))


def environment(root):
    root = Path(root).resolve()
    cache = root / '.cache'
    (cache / 'tmp').mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8',
           'PYTHONDONTWRITEBYTECODE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1', 'DO_NOT_TRACK': '1',
           'FREEVIDEO_HOME': str(root / '.runtime/home'), 'FREEVIDEO_MODEL_ROOT': str(root / 'weights'),
           'FREEVIDEO_VDN_ROOT': str(root / '.runtime/vdn'), 'FREEVIDEO_COMFY_ROOT': str(root / '.runtime/ComfyUI'),
           'FREEVIDEO_UV': shutil.which('uv') or 'uv', 'HF_HUB_DISABLE_XET': '1',
           'HF_HOME': str(cache / 'huggingface'), 'TORCH_HOME': str(cache / 'torch'),
           'TRITON_CACHE_DIR': str(cache / 'triton'), 'TORCHINDUCTOR_CACHE_DIR': str(cache / 'inductor'),
           'CUDA_CACHE_PATH': str(cache / 'cuda'), 'UV_CACHE_DIR': str(cache / 'uv'),
           'UV_PYTHON_INSTALL_DIR': str(root / '.runtime/python'), 'TEMP': str(cache / 'tmp'), 'TMP': str(cache / 'tmp')}
    return env


def runtime_valid(root):
    root = Path(root)
    return all(p.is_file() for p in [python_at(root), root / '.runtime-ready',
        root / '.runtime/FreeVideo/freevideo_engine/generate.py', root / '.runtime/ComfyUI/comfy/sd.py',
        root / '.runtime/vdn/diffusers/src/diffusers/__init__.py'])


def complete(root):
    root = Path(root)
    return runtime_valid(root) and all((root / 'weights' / r['target']).is_file() for r in manifest()['files'])


def digest_file(path, row):
    digest = hashlib.sha256() if row.get('sha256') else hashlib.sha1()
    if not row.get('sha256'):
        digest.update(f"blob {path.stat().st_size}\0".encode())
    with path.open('rb') as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest() == (row.get('sha256') or row['git_blob'])


def install_attention(root, command, update):
    spec = json.loads((root / '.runtime/FreeVideo/freevideo_engine/bootstrap_versions.json').read_text())['windows']['sageattention']
    wheel = root / '.downloads' / unquote(Path(urlparse(spec['url']).path).name)
    wheel.parent.mkdir(parents=True, exist_ok=True)
    update('Installing pinned Windows attention kernels', None)
    if not wheel.is_file() or not digest_file(wheel, spec):
        with httpx.stream('GET', spec['url'], follow_redirects=True, timeout=120) as response:
            response.raise_for_status()
            with wheel.open('wb') as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
        if not digest_file(wheel, spec):
            raise RuntimeError('SageAttention download hash mismatch')
    command([shutil.which('uv'), 'pip', 'install', '--python', python_at(root), '--no-deps', wheel])


def verify(root, update):
    root = Path(root)
    rows = manifest()['files']; total = sum(r['bytes'] for r in rows); done = 0
    for row in rows:
        path = root / 'weights' / row['target']
        if not path.is_file() or path.stat().st_size != row['bytes']:
            raise RuntimeError('Missing or incomplete model file: ' + row['target'])
        digest = hashlib.sha256() if row.get('sha256') else hashlib.sha1()
        if not row.get('sha256'):
            digest.update(f"blob {row['bytes']}\0".encode())
        with path.open('rb') as handle:
            while chunk := handle.read(8 * 1024 * 1024):
                digest.update(chunk); done += len(chunk)
                update('Verifying ' + path.name, min(99, round(done / total * 100)))
        if digest.hexdigest() != (row.get('sha256') or row['git_blob']):
            raise RuntimeError('Integrity mismatch: ' + row['target'])
        if row.get('receipt'):
            path.with_suffix('.json').write_text(json.dumps({'bytes': row['bytes'], 'sha256': row['sha256']}), encoding='utf-8')
    if not runtime_valid(root):
        raise RuntimeError('H3 runtime is incomplete; repair installation')
    for name, (_, revision) in SOURCES.items():
        source = root / '.runtime' / name
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True, creationflags=CREATE_FLAGS).strip()
        dirty = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=source, text=True, creationflags=CREATE_FLAGS).strip()
        if head != revision or dirty:
            raise RuntimeError(name + ' runtime differs from its pinned revision')
    vdn = root / '.runtime/vdn'
    for source, reference, expected in [(vdn, 'HEAD', '30b6b380c2482f3519469350810c2955d8847fd9'),
            (vdn / 'diffusers', 'HEAD^{tree}', '37068ab7331d8b28f4cf718dba7015c742a306d2')]:
        actual = subprocess.check_output(['git', 'rev-parse', reference], cwd=source, text=True, creationflags=CREATE_FLAGS).strip()
        dirty = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=source, text=True, creationflags=CREATE_FLAGS).strip()
        if actual != expected or dirty:
            raise RuntimeError('VDN or Diffusers runtime differs from the pinned source')
    return {'repo': 'OpenVDN/vdn-minimax-h3-edge', 'revision': 'da37681f5a1f7015fdb63482142b865111b687d3', 'bytes': done, 'file_count': len(rows)}


def install(root, run, update):
    root = Path(root); uv = shutil.which('uv'); env = environment(root)
    def command(args, cwd=root):
        run(args, cwd, env)
    for name, (url, revision) in SOURCES.items():
        source = root / '.runtime' / name
        update('Installing ' + name + ' source', None)
        if not (source / '.git').is_dir():
            source.mkdir(parents=True, exist_ok=True)
            command(['git', 'init', source])
            command(['git', 'remote', 'add', 'origin', url], source)
        head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=source, capture_output=True, text=True, creationflags=CREATE_FLAGS)
        if head.returncode:
            command(['git', 'fetch', '--depth', '1', 'origin', revision], source)
            command(['git', 'checkout', '--detach', 'FETCH_HEAD'], source)
        elif head.stdout.strip() != revision:
            raise RuntimeError('Existing runtime source has a different revision: ' + name)
    update('Installing isolated Python 3.12 and CUDA dependencies', None)
    config = root / '.venv/pyvenv.cfg'
    if not python_at(root).is_file() or not config.is_file() or str(root / '.runtime/python').lower() not in config.read_text().lower():
        command([uv, 'venv', '--python', '3.12', '--managed-python', '--allow-existing', root / '.venv'])
    constraints = root / '.runtime/FreeVideo/constraints/windows-unified.txt'
    command([uv, 'pip', 'install', '--python', python_at(root), '-r', constraints,
             '--extra-index-url', 'https://download.pytorch.org/whl/cu130', '--index-strategy', 'unsafe-best-match'])
    command([uv, 'pip', 'install', '--python', python_at(root), '--no-deps', '-e', root / '.runtime/FreeVideo'])
    command([python_at(root), '-m', 'freevideo_engine', 'setup', '--vdn-root', root / '.runtime/vdn', '--install-packages'])
    install_attention(root, command, update)
    command([python_at(root), '-c', "import torch; assert torch.cuda.is_available(); assert 'sm_120' in torch.cuda.get_arch_list(); import av, comfy_kitchen, transformers"])
    update('Checking CUDA attention and INT8 kernels', None)
    command([python_at(root), '-m', 'freevideo_engine', 'doctor', '--probe', '--out', root / '.runtime/kernel-check.json'])
    command([python_at(root), '-m', 'freevideo_engine.encode_worker', '--check-library', '--comfy-root', root / '.runtime/ComfyUI'])
    (root / '.runtime-ready').write_text(SOURCES['FreeVideo'][1], encoding='utf-8')
    rows = manifest()['files']; total = sum(r['bytes'] for r in rows)
    if shutil.disk_usage(root).free < sum(r['bytes'] for r in rows if not (root / 'weights' / r['target']).is_file()) + 5 * 2**30:
        raise RuntimeError('Not enough disk space for H3; keep an additional 5 GB free')
    from huggingface_hub import hf_hub_download
    lock = threading.Lock(); done = 0
    def fetch(row):
        nonlocal done
        path = root / 'weights' / row['target']
        if not path.is_file() or path.stat().st_size != row['bytes'] or not digest_file(path, row):
            # Repository-local download staging allows interrupted downloads to resume.
            stage = root / '.downloads' / row['revision']
            downloaded = Path(hf_hub_download(row['repo'], row['file'], revision=row['revision'], local_dir=stage))
            path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(downloaded, path)
        with lock:
            done += row['bytes']
            update(f'Downloading H3 · {done / 1e9:.1f} / {total / 1e9:.1f} GB', round(done / total * 100))
    update(f'Downloading H3 · 0 / {total / 1e9:.1f} GB', 0)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for _ in pool.map(fetch, sorted(rows, key=lambda r: r['bytes'], reverse=True)):
            pass
