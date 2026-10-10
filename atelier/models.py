"""Owned model lifecycle: isolated runtimes, pinned weights and verified deletion."""
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath

import httpx

from .catalog import CATALOG
from .storage import identifier, now

CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def python_at(root):
    return Path(root) / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")


def weights_at(model, root):
    return Path(root) / model["weight_dir"]


def installed(model, root):
    root = Path(root)
    weights = weights_at(model, root)
    if not python_at(root).is_file() or not (root / ".runtime-ready").is_file():
        return False
    if model["files"]:
        return all((weights / name).is_file() for name in model["files"]) and (root / ".runtime/ComfyUI/main.py").is_file()
    return (weights / "config.json").is_file() and (weights / "model.safetensors.index.json").is_file() and bool(list(weights.glob("*.safetensors")))


class ModelManager:
    def __init__(self, store, project_root, runtime=None):
        self.store, self.project_root, self.runtime = store, Path(project_root).resolve(), runtime
        self.owned_root = self.project_root / "models"
        self.owned_root.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.operations = {}

    def record(self, model_id):
        if model_id not in CATALOG:
            raise ValueError("Unknown model")
        return self.store.one("SELECT * FROM models WHERE id=?", (model_id,))

    def busy(self, model_id):
        return any(op["model_id"] == model_id and op["status"] == "running" for op in self.operations.values())

    def in_use(self, model_id):
        return self.store.one("SELECT id FROM jobs WHERE model_id=? AND status IN ('queued','running') LIMIT 1", (model_id,)) is not None

    def list(self):
        result = []
        for model_id, model in CATALOG.items():
            record = self.record(model_id)
            root = Path(record["runtime_path"]) if record else None
            complete = installed(model, root) and bool(record['verified']) if root else False
            size = sum(p.stat().st_size for p in weights_at(model, root).rglob("*.safetensors")) if root and root.exists() else 0
            item = {key: value for key, value in model.items() if key not in {"files", "hub_revision", "port", "weight_dir"}}
            item.update(status="installed" if complete else "incomplete" if record else "not_installed",
                        source=record["source"] if record else None, runtime_path=str(root) if root else None,
                        verified=record["verified"] if record else None,
                        verification=json.loads(record["verification"]) if record and record["verification"] else None,
                        size_bytes=size, busy=self.busy(model_id), in_use=self.in_use(model_id))
            item["operation"] = next((dict(op) for op in reversed(list(self.operations.values())) if op["model_id"] == model_id), None)
            result.append(item)
        return result

    def _assert_idle(self, model_id):
        self.record(model_id)
        if self.busy(model_id) or self.in_use(model_id):
            raise ValueError("Wait for this model's current operation or generation to finish")

    def start(self, model_id, action):
        with self.lock:
            self._assert_idle(model_id)
            if action not in {"install", "verify"}:
                raise ValueError("Unknown model operation")
            record = self.record(model_id)
            if action == "verify" and not record:
                raise ValueError("Install this model first")
            operation = {"id": identifier(), "model_id": model_id, "action": action, "status": "running",
                         "phase": "Preparing", "progress": None, "logs": [], "error": None, "created": now()}
            self.operations[operation["id"]] = operation
            threading.Thread(target=self._operate, args=(operation,), daemon=True).start()
            return dict(operation)

    def _update(self, operation, phase=None, progress=None, log=None):
        with self.lock:
            if phase:
                operation["phase"] = phase
            operation["progress"] = progress
            if log:
                operation["logs"] = (operation["logs"] + [str(log).strip()[-1000:]])[-80:]

    def _operate(self, operation):
        try:
            if operation["action"] == "install":
                self._install(operation)
            self._verify(operation)
            self._update(operation, "Verified", 100)
            operation["status"] = "complete"
        except Exception as error:
            operation.update(status="error", phase="Needs attention", error=str(error))

    def _run(self, operation, args, cwd):
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "HF_HUB_DISABLE_XET": "1", "HF_HUB_DISABLE_TELEMETRY": "1"}
        process = subprocess.Popen([str(a) for a in args], cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace", creationflags=CREATE_FLAGS)
        for line in process.stdout:
            self._update(operation, log=line)
        if process.wait() != 0:
            raise RuntimeError("Installation command failed. See the operation log; retry resumes completed downloads.")

    def _install(self, operation):
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        model_id = operation["model_id"]
        model = CATALOG[model_id]
        if self.runtime:
            self.runtime.release(model_id)
        if os.name != "nt":
            raise RuntimeError("GPU installation currently supports Windows.")
        uv = shutil.which("uv")
        if not uv:
            raise RuntimeError("Install uv from https://docs.astral.sh/uv/ then retry")
        bundle = self.owned_root / model_id
        bundle.mkdir(exist_ok=True)
        marker = bundle / ".atelier-owned.json"
        if any(bundle.iterdir()) and not marker.exists():
            raise RuntimeError("Refusing to adopt a non-empty unmanaged model folder")
        marker.write_text(json.dumps({"model_id": model_id}), encoding="utf-8")
        root = bundle
        self.store.execute("INSERT OR REPLACE INTO models(id,source,runtime_path,linked) VALUES(?,?,?,?)", (model_id, "managed", str(root), now()))
        comfy = root / ".runtime/ComfyUI"
        if model_id == "qwen-image-2.1" and not (comfy / "main.py").is_file():
            self._update(operation, "Downloading ComfyUI engine")
            archive = bundle / "comfyui.zip"
            with httpx.Client(follow_redirects=True, timeout=120) as client, client.stream("GET", "https://api.github.com/repos/Comfy-Org/ComfyUI/zipball/0df64eb242b7c5759c3e86afd5d1846d923b1033") as response:
                response.raise_for_status()
                with archive.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
            comfy.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive) as zipped:
                for member in zipped.infolist():
                    relative = PurePosixPath(member.filename)
                    parts = relative.parts[1:]
                    if not parts or member.is_dir():
                        continue
                    target = (comfy / Path(*parts)).resolve()
                    if not target.is_relative_to(comfy.resolve()):
                        raise RuntimeError("Invalid runtime archive path")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zipped.open(member) as source, target.open("wb") as dest:
                        shutil.copyfileobj(source, dest)
        self._update(operation, "Installing runtime dependencies")
        if not python_at(root).exists():
            self._run(operation, [uv, "venv", "--python", "3.14" if model_id == "qwen-image-2.1" else "3.12", root / ".venv"], root)
        self._run(operation, [uv, "pip", "install", "--python", python_at(root), "torch==2.13.0", "torchvision==0.28.0", "--index-url", "https://download.pytorch.org/whl/cu130"], root)
        self._run(operation, [uv, "pip", "install", "--python", python_at(root), "-r", self.project_root / "requirements.txt"], root)
        if model_id == "qwen-image-2.1":
            self._run(operation, [uv, "pip", "install", "--python", python_at(root), "torchaudio==2.11.0", "--index-url", "https://download.pytorch.org/whl/cu130"], root)
            self._run(operation, [uv, "pip", "install", "--python", python_at(root), "-r", comfy / "requirements.txt", "websocket-client>=1.8,<2"], root)
        else:
            self._run(operation, [uv, "pip", "install", "--python", python_at(root), "-r", self.project_root / "requirements-hidream.txt"], root)
        self._run(operation, [python_at(root), "-c", "import torch; assert torch.cuda.is_available(), 'CUDA unavailable'; assert 'sm_120' in torch.cuda.get_arch_list(), 'RTX 5060 Ti support missing'"], root)
        (root / ".runtime-ready").write_text("GPU dependencies installed", encoding="utf-8")
        self._update(operation, "Downloading model weights")
        from huggingface_hub import hf_hub_download
        files = self._hub_files(model)
        for i, file in enumerate(files):
            self._update(operation, f"Downloading {i + 1}/{len(files)}: {Path(file.rfilename).name}", round(i / len(files) * 100))
            hf_hub_download(model["hub_repo"], file.rfilename, revision=model["hub_revision"], local_dir=weights_at(model, root))

    def _hub_files(self, model):
        from huggingface_hub import HfApi
        info = HfApi().model_info(model["hub_repo"], revision=model["hub_revision"], files_metadata=True)
        if model["files"]:
            files = [f for f in info.siblings if f.rfilename in model["files"]]
            if len(files) != len(model["files"]):
                raise RuntimeError("Publisher manifest is missing a required file")
        else:
            files = [f for f in info.siblings if "/" not in f.rfilename and not f.rfilename.startswith(".") and f.rfilename not in {"README.md", "benchmark_summary.json", "demo_prompts.json"}]
        return files

    def _verify(self, operation):
        model_id = operation["model_id"]
        self.store.execute("UPDATE models SET verified=NULL,verification=NULL WHERE id=?", (model_id,))
        model = CATALOG[model_id]
        record = self.record(model_id)
        root = Path(record["runtime_path"])
        self._update(operation, "Reading publisher manifest")
        files = self._hub_files(model)
        total = sum(f.size or 0 for f in files)
        checked = 0
        manifest = []
        for file in files:
            path = weights_at(model, root) / file.rfilename
            if not path.is_file():
                raise RuntimeError(f"Missing file: {file.rfilename}")
            digest = hashlib.sha256() if file.lfs else hashlib.sha1()
            if not file.lfs:
                digest.update(f"blob {path.stat().st_size}\0".encode())
            with path.open("rb") as handle:
                while chunk := handle.read(8 * 1024 * 1024):
                    digest.update(chunk)
                    checked += len(chunk)
                    self._update(operation, f"Verifying {path.name}", min(99, round(checked / max(total, 1) * 100)))
            expected = file.lfs.sha256 if file.lfs else file.blob_id
            if digest.hexdigest() != expected:
                self.store.execute("UPDATE models SET verified=NULL,verification=NULL WHERE id=?", (model_id,))
                raise RuntimeError(f"Integrity mismatch: {file.rfilename}. The file does not match the pinned publisher revision.")
            manifest.append({"name": file.rfilename, "hash": expected, "size": path.stat().st_size})
        if not installed(model, root):
            raise RuntimeError("Weights verified, but runtime dependencies are incomplete; repair the installation")
        verification = {"repo": model["hub_repo"], "revision": model["hub_revision"], "files": manifest, "bytes": checked}
        self.store.execute("UPDATE models SET verified=?,verification=? WHERE id=?", (now(), json.dumps(verification), model_id))

    def remove(self, model_id):
        with self.lock:
            self._assert_idle(model_id)
            record = self.record(model_id)
            if not record:
                raise ValueError("Model is not installed")
            if self.runtime:
                self.runtime.release(model_id)
            if record["source"] == "managed":
                bundle = self.owned_root / model_id
                root = Path(record["runtime_path"])
                marker = bundle / ".atelier-owned.json"
                if bundle.is_symlink() or getattr(bundle, "is_junction", lambda: False)() or bundle.resolve().parent != self.owned_root.resolve() or root.resolve() != bundle.resolve():
                    raise ValueError("Refusing to delete a model outside the managed folder")
                if not marker.is_file() or json.loads(marker.read_text())["model_id"] != model_id:
                    raise ValueError("This model folder has no valid ownership marker")
                # Python removes directory links themselves without traversing their targets.
                shutil.rmtree(bundle)
            else:
                raise ValueError("Only model folders owned by Local Atelier may be removed")
            self.store.execute("DELETE FROM models WHERE id=?", (model_id,))
