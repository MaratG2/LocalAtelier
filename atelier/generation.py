import json
import queue
import threading
from pathlib import Path

from PIL.PngImagePlugin import PngInfo

from .catalog import CATALOG
from .storage import identifier, now


def integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be a whole number between {low} and {high}")
    return value


def validate(data, store):
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    allowed = {"project_id", "model_id", "mode", "prompt", "width", "height", "seed", "num_inference_steps", "batch_size", "reference_ids", "keep_original_aspect", "transparent_background"}
    if set(data) - allowed:
        raise ValueError("Unsupported generation settings")
    if not isinstance(data.get("project_id", "inbox"), str):
        raise ValueError("Select an active project")
    project = store.project(data.get("project_id", "inbox"))
    if not project or project["archived"]:
        raise ValueError("Select an active project")
    model_id = data.get("model_id")
    if not isinstance(model_id, str) or model_id not in CATALOG or CATALOG[model_id]["service"] != "images":
        raise ValueError("Select a supported image model")
    model = CATALOG[model_id]
    prompt = data.get("prompt", "")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12000:
        raise ValueError("Describe your image using 1–12,000 characters")
    mode = data.get("mode", "t2i")
    if not isinstance(mode, str) or mode not in {"t2i", "edit", "reference"}:
        raise ValueError("Unknown generation mode")
    refs = data.get("reference_ids", [])
    if not isinstance(refs, list) or len(refs) > model["max_references"] or any(not isinstance(r, str) for r in refs):
        raise ValueError(f"Use up to {model['max_references']} reference images")
    if (mode == "t2i" and refs) or (mode == "edit" and len(refs) != 1) or (mode == "reference" and not refs):
        raise ValueError("Create needs no references, Edit needs one, and References needs at least one")
    for ref in refs:
        asset = store.asset(ref)
        if not asset or asset["deleted"] or asset["kind"] not in {"generated", "reference"}:
            raise ValueError("A reference image is unavailable")
    request = {"project_id": project["id"], "model_id": model_id, "mode": mode, "prompt": prompt.strip(), "reference_ids": refs}
    for name, default, low, high in [("width", 1024, 512, model["max_size"]), ("height", 1024, 512, model["max_size"]),
                                    ("seed", 42, 0, 4294967295), ("num_inference_steps", model["steps"], 1, model["max_steps"]), ("batch_size", 1, 1, 4)]:
        request[name] = integer(data.get(name, default), name, low, high)
    if request["width"] % 64 or request["height"] % 64:
        raise ValueError("Dimensions must be multiples of 64")
    if request["seed"] + request["batch_size"] - 1 > 4294967295:
        raise ValueError("Seed has no room for the selected batch")
    for name in ("keep_original_aspect", "transparent_background"):
        value = data.get(name, False)
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be true or false")
        request[name] = value
    if request["transparent_background"] and not model["transparent"]:
        raise ValueError("This model does not support native transparency")
    if mode == "t2i" and request["keep_original_aspect"]:
        raise ValueError("Aspect preservation requires a reference")
    return request


def save_image(store, image, project_id, *, kind, name, prompt="", model_id=None, seed=None, metadata=None):
    asset_id = identifier()
    filename, thumbnail = asset_id + ".png", asset_id + "-thumb.png"
    metadata = metadata or {}
    info = PngInfo()
    info.add_text("local_atelier", json.dumps({**metadata, "prompt": prompt, "model_id": model_id}))
    image.save(store.assets / filename, format="PNG", pnginfo=info)
    small = image.copy()
    small.thumbnail((512, 512))
    small.save(store.assets / thumbnail, format="PNG")
    (store.assets / (asset_id + ".json")).write_text(json.dumps({**metadata, "prompt": prompt, "model_id": model_id}, indent=2), encoding="utf-8")
    store.execute("INSERT INTO assets(id,project_id,kind,filename,thumbnail,name,prompt,model_id,width,height,seed,metadata,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (asset_id, project_id, kind, filename, thumbnail, name, prompt, model_id, image.width, image.height, seed, json.dumps(metadata), now()))
    store.execute("UPDATE projects SET updated=? WHERE id=?", (now(), project_id))
    return store.asset(asset_id)


class GenerationQueue:
    def __init__(self, store, runtime, models):
        self.store, self.runtime, self.models = store, runtime, models
        self.queue = queue.Queue()
        self.cancelled = set()
        self.lock = threading.Lock()
        threading.Thread(target=self._work, daemon=True).start()

    def submit(self, data, mesh=False, video=False):
        if video:
            from .videos import validate_video
            request = validate_video(data, self.store)
        elif mesh:
            from .mesh_jobs import validate_mesh
            request = validate_mesh(data, self.store)
        else:
            request = validate(data, self.store)
        with self.models.lock, self.lock:
            required = [] if request["mode"] == "simplify" else [request["model_id"]]
            if request.get("image_model_id"):
                required.append(request["image_model_id"])
            for model_id in required:
                if self.models.busy(model_id):
                    raise ValueError("Wait for this model's installation or verification to finish")
                record = self.models.record(model_id)
                if not record or not record['verified']:
                    raise ValueError(f"Install and verify {CATALOG[model_id]['name']} first")
            count = self.store.one("SELECT COUNT(*) AS count FROM jobs WHERE status IN ('queued','running')")["count"]
            if count >= 4:
                raise ValueError("The queue is full. Wait for a generation to finish")
            job_id = identifier()
            self.store.execute("INSERT INTO jobs(id,project_id,model_id,status,phase,total,request,created,updated) VALUES(?,?,?,'queued','Queued',?,?,?,?)",
                               (job_id, request["project_id"], request["model_id"], request["batch_size"], json.dumps(request), now(), now()))
            self.queue.put(job_id)
            return self.store.job(job_id)

    def cancel(self, job_id):
        job = self.store.job(job_id)
        if not job:
            raise ValueError("Job not found")
        if job["status"] in {"queued", "running"}:
            self.cancelled.add(job_id)
            phase = "Stopping generation" if job["model_id"] in {"trellis2", "vdn-h3"} else "Stopping after the current image"
            self.store.update_job(job_id, phase=phase if job["status"] == "running" else "Cancelled")
            if job["status"] == "queued":
                self.store.update_job(job_id, status="cancelled")

    def _work(self):
        while True:
            job_id = self.queue.get()
            results = []
            try:
                job = self.store.job(job_id)
                if job_id in self.cancelled:
                    continue
                request = job["request"]
                self.store.update_job(job_id, status="running", phase="Preparing")
                if request["model_id"] == "vdn-h3":
                    from .providers.vdn_h3 import generate
                    def video_progress(phase, value):
                        if job_id not in self.cancelled:
                            self.store.update_job(job_id, phase=phase, progress=value)
                    asset = generate(self.runtime, request, video_progress, lambda: job_id in self.cancelled)
                    self.store.update_job(job_id, completed=1, result_ids=json.dumps([asset['id']]), status='complete', phase='Complete', progress=100)
                    continue
                if request["model_id"] == "trellis2":
                    from .mesh_jobs import run_mesh_job
                    def mesh_progress(phase, value):
                        if job_id not in self.cancelled:
                            self.store.update_job(job_id, phase=phase, progress=value)
                    asset = run_mesh_job(self, job_id, request, mesh_progress)
                    self.store.update_job(job_id, completed=1, result_ids=json.dumps([asset["id"]]), status="complete", phase="Complete", progress=100)
                    continue
                refs = [self.store.assets / self.store.asset(ref)["filename"] for ref in request["reference_ids"]]
                for index in range(request["batch_size"]):
                    if job_id in self.cancelled:
                        break
                    def progress(phase, value):
                        if job_id not in self.cancelled:
                            self.store.update_job(job_id, phase=phase, progress=round((index * 100 + value) / request["batch_size"]))
                    seed = request["seed"] + index
                    image, metadata = self.runtime.generate({**request, "seed": seed}, refs, progress)
                    metadata.update(reference_ids=request["reference_ids"], settings={**request, "seed": seed}, job_id=job_id)
                    asset = save_image(self.store, image, request["project_id"], kind="generated", name=request["prompt"][:80],
                                       prompt=request["prompt"], model_id=request["model_id"], seed=seed, metadata=metadata)
                    results.append(asset["id"])
                    self.store.update_job(job_id, completed=len(results), result_ids=json.dumps(results))
                status = "cancelled" if job_id in self.cancelled else "complete"
                self.store.update_job(job_id, status=status, phase="Stopped" if status == "cancelled" else "Complete", progress=100 if status == "complete" else self.store.job(job_id)["progress"])
            except Exception as error:
                stopped = job_id in self.cancelled
                self.store.update_job(job_id, status="cancelled" if stopped else "error", phase="Stopped" if stopped else "Generation failed", error=None if stopped else str(error)[:3000])
            finally:
                if self.store.setting("unload_after_job", False):
                    self.runtime.release()
                self.cancelled.discard(job_id)
                self.queue.task_done()
