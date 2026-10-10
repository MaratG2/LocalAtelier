import atexit
import base64
import io
import json
import os
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path

import httpx
from PIL import Image

from .catalog import CATALOG
from .models import CREATE_FLAGS, installed, python_at, weights_at


class Runtime:
    """A single owned GPU worker at a time, with isolated Python environments."""
    def __init__(self, store):
        self.store = store
        self.active_model = None
        self.processes = []
        self.log_handles = []
        self.lock = threading.RLock()
        self.phase = "Idle"
        self.token = uuid.uuid4().hex
        self.root = store.root / "runtime"
        self.root.mkdir(exist_ok=True)
        atexit.register(self.release)

    def _start(self, args, cwd, env, name):
        log = (self.root / f"{name}.log").open("w", encoding="utf-8")
        self.log_handles.append(log)
        process = subprocess.Popen([str(a) for a in args], cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=CREATE_FLAGS, start_new_session=os.name != "nt")
        self.processes.append(process)
        return process

    def release(self, model_id=None):
        with self.lock:
            if model_id and self.active_model != model_id:
                return
            for process in reversed(self.processes):
                if process.poll() is None:
                    if os.name == "nt":
                        subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"], capture_output=True, creationflags=CREATE_FLAGS, timeout=30)
                    else:
                        import signal
                        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
            for handle in self.log_handles:
                handle.close()
            self.processes.clear()
            self.log_handles.clear()
            self.active_model = None
            self.phase = "Idle"

    def ensure(self, model_id, callback):
        model = CATALOG[model_id]
        url = f"http://127.0.0.1:{model['port']}"
        with self.lock:
            if self.active_model == model_id and all(p.poll() is None for p in self.processes):
                return url
            callback("Switching model · freeing GPU memory", 0)
            self.release()
            for port in ([model['port'], 7893] if model_id == 'qwen-image-2.1' else [model['port']]):
                with socket.socket() as probe:
                    try:
                        probe.bind(('127.0.0.1', port))
                    except OSError as error:
                        raise RuntimeError(f'Local worker port {port} is occupied. Close the process using it; Local Atelier will not connect to another installation.') from error
            record = self.store.one("SELECT * FROM models WHERE id=?", (model_id,))
            if not record or not record['verified'] or not installed(model, record["runtime_path"]):
                raise RuntimeError("Install this model in the model library first")
            root = Path(record["runtime_path"])
            cache = self.root / 'cache' / model_id
            cache.mkdir(parents=True, exist_ok=True)
            env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                   "HF_HUB_DISABLE_TELEMETRY": "1", "HF_HOME": str(cache / 'huggingface'),
                   "TORCH_HOME": str(cache / 'torch'), "TRITON_CACHE_DIR": str(cache / 'triton'),
                   "TORCHINDUCTOR_CACHE_DIR": str(cache / 'inductor'),
                   "DO_NOT_TRACK": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                   "ATELIER_WORKER_TOKEN": self.token, "PYTHONDONTWRITEBYTECODE": "1"}
            self.active_model = model_id
            self.phase = f"Loading {model['name']}"
            callback(self.phase, 0)
            try:
                if model_id == "qwen-image-2.1":
                    engine_root = root / ".runtime/ComfyUI"
                    paths = self.root / "qwen-paths.yaml"
                    paths.write_text("local_atelier:\n  base_path: " + json.dumps(str(weights_at(model, root))) + "\n  diffusion_models: diffusion_models\n  text_encoders: text_encoders\n  vae: vae\n", encoding="utf-8")
                    engine_port = 7893
                    env["QWEN_COMFY_URL"] = f"http://127.0.0.1:{engine_port}"
                    env["QWEN_TEXT_ENCODER"] = "qwen3vl_8b_int8_convrot.safetensors"
                    args = [python_at(root), "-u", "main.py", "--listen", "127.0.0.1", "--port", engine_port,
                            "--extra-model-paths-config", paths, "--disable-auto-launch", "--use-pytorch-cross-attention",
                            "--reserve-vram", "1.0", "--disable-all-custom-nodes", "--disable-partner-nodes"]
                    if self.store.setting("low_vram", False):
                        args.append("--lowvram")
                    self._start(args, engine_root, env, "qwen-engine")
                    self._wait(env["QWEN_COMFY_URL"] + "/system_stats", 180)
                else:
                    env.update(HIDREAM_ATTENTION_BACKEND="auto", PYTORCH_CUDA_ALLOC_CONF="")
                args = [python_at(root), "-u", "-m", "atelier.worker", "--model", model_id, "--weights", weights_at(model, root), "--data", self.root / model_id, "--port", model["port"]]
                self._start(args, Path(__file__).resolve().parents[1], env, model_id)
                self._wait(url + "/api/status", 600)
                self.phase = "Ready"
            except Exception:
                self.release()
                raise
        return url

    def _wait(self, url, timeout):
        deadline = time.monotonic() + timeout
        with httpx.Client(timeout=2, trust_env=False, headers={"X-Atelier-Worker": self.token}) as client:
            while time.monotonic() < deadline:
                if any(p.poll() is not None for p in self.processes):
                    raise RuntimeError("Model worker exited while loading. See Settings → runtime logs.")
                try:
                    response = client.get(url)
                    if response.is_success:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
        raise RuntimeError("Model startup timed out. See Settings → runtime logs.")

    def generate_mesh(self, request, reference, callback, cancelled):
        from .providers.trellis2 import generate
        return generate(self, request, reference, callback, cancelled)

    def generate(self, request, references, callback):
        model_id = request["model_id"]
        url = self.ensure(model_id, callback)
        mode = request["mode"]
        payload = {key: request[key] for key in ("prompt", "width", "height", "seed", "num_inference_steps", "keep_original_aspect")}
        payload["mode"] = mode
        payload["refs_b64"] = []
        for path in references:
            with Image.open(path) as reference:
                reference.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
                buffer = io.BytesIO()
                reference.save(buffer, format="PNG")
                payload["refs_b64"].append(base64.b64encode(buffer.getvalue()).decode("ascii"))
        if model_id == "qwen-image-2.1":
            payload["transparent_background"] = request["transparent_background"]
        self.phase = "Generating"
        callback("Encoding prompt and references", 0)
        started = time.monotonic()
        try:
            with httpx.Client(timeout=httpx.Timeout(3600, connect=5), trust_env=False, headers={"X-Atelier-Worker": self.token}) as client:
                response = client.post(url + "/api/generate/start", json=payload)
                if response.is_error:
                    raise RuntimeError(response.json().get("error", "The model rejected the request"))
                job_id = response.json()["job_id"]
                with client.stream("GET", url + "/api/generate/stream/" + job_id) as stream:
                    stream.raise_for_status()
                    for line in stream.iter_lines():
                        if time.monotonic() - started > 3600:
                            raise RuntimeError("Generation exceeded one hour")
                        if not line.startswith("data: "):
                            continue
                        event = json.loads(line[6:])
                        if event["type"] == "progress":
                            total = max(1, event.get("total", request["num_inference_steps"]))
                            step = event.get("step", 0)
                            callback(f"Rendering · step {step} of {total}" if step < total else "Decoding and saving", min(99, round(step / total * 95)))
                        elif event["type"] == "error":
                            raise RuntimeError(event["message"])
                        elif event["type"] == "done":
                            if event.get("mock_mode"):
                                raise RuntimeError("The model worker returned a mock image; real generation was requested")
                            raw = base64.b64decode(event.pop("image"))
                            with Image.open(io.BytesIO(raw)) as image:
                                return image.copy(), {**event, "elapsed_seconds": round(time.monotonic() - started, 2)}
            raise RuntimeError("The model stream ended without a result")
        finally:
            self.phase = "Ready" if self.active_model else "Idle"

    def logs(self):
        return {path.stem: path.read_text(encoding="utf-8", errors="replace")[-12000:] for path in self.root.glob("*.log")}
