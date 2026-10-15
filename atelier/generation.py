import json
import queue
import threading
from pathlib import Path

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from .plugins import catalog_for, validate_options
from .pixelation import pixelate, validate_pixelation
from .storage import identifier, now


def integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be a whole number between {low} and {high}")
    return value


def validate(data, store):
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    from .styles import apply_style
    from .gamedev import validate_tool, tool_prompt
    data, style = apply_style(data, store)
    tool = validate_tool(data.pop('game_asset', None))
    pixelation = validate_pixelation(data.pop('pixelation', None))
    options = data.pop('model_options', None)
    allowed = {"project_id", "model_id", "mode", "prompt", "width", "height", "seed", "num_inference_steps", "batch_size", "reference_ids", "keep_original_aspect", "transparent_background", "edit_mask_id", "mask_feather"}
    if set(data) - allowed:
        raise ValueError("Unsupported generation settings")
    if not isinstance(data.get("project_id", "inbox"), str):
        raise ValueError("Select an active project")
    project = store.project(data.get("project_id", "inbox"))
    if not project or project["archived"]:
        raise ValueError("Select an active project")
    model_id = data.get("model_id")
    catalog = catalog_for(store)
    if not isinstance(model_id, str) or model_id not in catalog or catalog[model_id]["service"] != "images":
        raise ValueError("Select a supported image model")
    model = catalog[model_id]
    prompt = data.get("prompt", "")
    if not isinstance(style['user_prompt'], str) or not style['user_prompt'].strip() or len(style['user_prompt']) > 12000:
        raise ValueError("Describe your image using 1–12,000 characters")
    mode = data.get("mode", "t2i")
    if not isinstance(mode, str) or mode not in {"t2i", "edit", "reference"}:
        raise ValueError("Unknown generation mode")
    if mode not in model.get('modes', ['t2i', 'edit', 'reference']):
        raise ValueError('This model does not support the selected image mode')
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
    validated_options = validate_options(model, options)
    if validated_options:
        request['model_options'] = validated_options
    for name, default, low, high in [("width", 1024, 512, model["max_size"]), ("height", 1024, 512, model["max_size"]),
                                    ("seed", 42, 0, 4294967295), ("num_inference_steps", model["steps"], 1, model["max_steps"]), ("batch_size", 1, 1, 4)]:
        request[name] = integer(data.get(name, default), name, low, high)
    if request["width"] % 64 or request["height"] % 64:
        raise ValueError("Dimensions must be multiples of 64")
    if tool and tool['generation'] == 'sheet':
        import math
        longest, shortest = max(tool['columns'], tool['rows']), min(tool['columns'], tool['rows'])
        if longest > 4 * shortest:
            raise ValueError('Grid aspect ratio cannot exceed 4:1. Add more rows or columns.')
        cell = min(model['max_size'] // longest // 64 * 64,
                   math.ceil(max(512 / shortest, max(request['width'], request['height']) / longest) / 64) * 64)
        request.update(width=tool['columns'] * cell, height=tool['rows'] * cell)
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
    if data.get('edit_mask_id') is not None:
        mask_id = data['edit_mask_id']
        mask = store.asset(mask_id) if isinstance(mask_id, str) else None
        if mode != 'edit' or tool:
            raise ValueError('Use Edit mode with one source image for masked editing.')
        if not mask or mask['deleted'] or mask['kind'] != 'mask' or mask['metadata'].get('source_id') != refs[0]:
            raise ValueError('This mask belongs to a different or unavailable image. Paint a new mask.')
        request.update(edit_mask_id=mask_id, mask_feather=integer(data.get('mask_feather', 12), 'Edge softness', 0, 64), keep_original_aspect=True)
    request.update(style)
    if pixelation:
        request['pixelation'] = pixelation
    if tool:
        request['game_asset'] = tool
        if tool['generation'] == 'individual':
            request['width'] = request['height'] = max(request['width'], request['height'])
            if tool['kind'] == 'spritesheet':
                if model_id != 'qwen-image-2.1':
                    raise ValueError('Character animation requires Qwen for transparent reference-guided frames')
                if len(refs) >= model['max_references']:
                    raise ValueError('Leave one reference slot free for the character anchor')
                request['transparent_background'] = True
            else:
                request['transparent_background'] = False
            if request['seed'] + request['batch_size'] * tool['count'] - 1 > 4294967295:
                raise ValueError('Seed has no room for all game frames')
        else:
            request['prompt'] += '\n\n' + tool_prompt(tool)
        request['keep_original_aspect'] = False
    return request


def save_image(store, image, project_id, *, kind, name, prompt="", model_id=None, seed=None, metadata=None):
    asset_id = identifier()
    filename, thumbnail = asset_id + ".png", asset_id + "-thumb.png"
    metadata = metadata or {}
    info = PngInfo()
    info.add_text("local_atelier", json.dumps({**metadata, "prompt": prompt, "model_id": model_id}))
    store.write_image(filename, image, pnginfo=info)
    small = image.copy()
    if metadata.get('pixelation'):
        small.thumbnail((512, 512), resample=Image.Resampling.NEAREST)
    else:
        small.thumbnail((512, 512))
    store.write_image(thumbnail, small)
    store.write_file(asset_id + '.json', json.dumps({**metadata, 'prompt': prompt, 'model_id': model_id}, indent=2).encode('utf-8'))
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
        self.accepting = True
        threading.Thread(target=self._work, daemon=True).start()

    def submit(self, data, mesh=False, video=False):
        with self.models.lock, self.lock:
            return self._submit(data, mesh, video)

    def _submit(self, data, mesh=False, video=False):
        if video:
            from .videos import validate_video
            request = validate_video(data, self.store)
        elif mesh:
            from .mesh_jobs import validate_mesh
            request = validate_mesh(data, self.store)
        else:
            request = validate(data, self.store)
        if not self.accepting:
            raise ValueError('Local Atelier is updating. Try again in a moment.')
        required = [] if request["mode"] == "simplify" else [request["model_id"]]
        if request.get("image_model_id"):
            required.append(request["image_model_id"])
        for model_id in required:
            if self.models.busy(model_id):
                raise ValueError("Wait for this model's installation or verification to finish")
            record = self.models.record(model_id)
            if not record or not record['verified']:
                raise ValueError(f"Install and verify {catalog_for(self.store)[model_id]['name']} first")
            model = catalog_for(self.store)[model_id]
            if model.get('plugin_id'):
                from .models import installed
                if not installed(model, record['runtime_path']):
                    raise ValueError('Install and verify this plugin model first')
        count = self.store.one("SELECT COUNT(*) AS count FROM jobs WHERE status IN ('queued','running')")["count"]
        if count >= 4:
            raise ValueError("The queue is full. Wait for a generation to finish")
        job_id = identifier()
        self.store.execute("INSERT INTO jobs(id,project_id,model_id,status,phase,total,request,created,updated) VALUES(?,?,?,'queued','Queued',?,?,?,?)",
                           (job_id, request["project_id"], request["model_id"], request["batch_size"], json.dumps(request), now(), now()))
        self.queue.put((job_id, self.store.context.get() if hasattr(self.store, 'context') else None))
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
            job_id, session = self.queue.get()
            if session:
                # Claim the session before its reaper can dispose a cancelled
                # queue item. Cleanup checks this flag under the same lock.
                with self.store.lock:
                    current = self.store.sessions.get(session)
                    if current is None or current.closed:
                        self.cancelled.discard(job_id)
                        self.queue.task_done()
                        continue
                    current.working = True
            context = self.store.context.set(session) if hasattr(self.store, 'context') else None
            files = self.store.file_scope()
            files.__enter__()
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
                refs = [self.store.input_path(self.store.asset(ref)["filename"]) for ref in request["reference_ids"]]
                for index in range(request["batch_size"]):
                    if job_id in self.cancelled:
                        break
                    def progress(phase, value):
                        if job_id not in self.cancelled:
                            self.store.update_job(job_id, phase=phase, progress=round((index * 100 + value) / request["batch_size"]))
                    tool = request.get('game_asset')
                    individual = tool and tool['generation'] == 'individual'
                    seed = request['seed'] + index * (tool['count'] if individual else 1)
                    if individual:
                        from .game_render import render_game
                        image, metadata = render_game(self.runtime, self.store, {**request, 'seed': seed}, refs, progress, lambda: job_id in self.cancelled)
                    else:
                        image, metadata = self.runtime.generate({**request, 'seed': seed}, refs, progress)
                    if request.get('pixelation'):
                        progress('Applying pixel finish', 99)
                        image, metadata['pixelation'] = pixelate(image, request['pixelation'])
                    if request.get('edit_mask_id'):
                        from .masking import composite_edit
                        progress('Blending the selected area', 99)
                        image, metadata['masked_edit'] = composite_edit(self.store, request, image)
                    metadata.update(reference_ids=request["reference_ids"], settings={**request, "seed": seed}, job_id=job_id, game_asset=request.get('game_asset'), style_prompt=request.get('style_prompt'), style_reference_id=request.get('style_reference_id'))
                    user_prompt = request.get('user_prompt', request['prompt'])
                    asset = save_image(self.store, image, request["project_id"], kind="generated", name=user_prompt[:80],
                                       prompt=user_prompt, model_id=request["model_id"], seed=seed, metadata=metadata)
                    results.append(asset["id"])
                    self.store.update_job(job_id, completed=len(results), result_ids=json.dumps(results))
                status = "cancelled" if job_id in self.cancelled else "complete"
                self.store.update_job(job_id, status=status, phase="Stopped" if status == "cancelled" else "Complete", progress=100 if status == "complete" else self.store.job(job_id)["progress"])
            except Exception as error:
                self.runtime.release()
                stopped = job_id in self.cancelled
                self.store.update_job(job_id, status="cancelled" if stopped else "error", phase="Stopped" if stopped else "Generation failed", error=None if stopped else str(error)[:3000])
            finally:
                if self.store.setting("unload_after_job", False) or (session and self.store.current.closed):
                    self.runtime.release()
                try:
                    files.__exit__(None, None, None)
                    if getattr(self.store, 'personal', False) and not self.runtime.active_model:
                        self.store.current.clear_work()
                except OSError:
                    self.runtime.release()
                    self.store.cleanup_error = 'Temporary file cleanup is pending. Close the studio workers and restart to retry.'
                    if getattr(self.store, 'personal', False):
                        self.store.current.pending_runtime_cleanup = True
                if session:
                    self.store.current.working = False
                if context is not None:
                    self.store.context.reset(context)
                    self.store.reap()
                self.cancelled.discard(job_id)
                self.queue.task_done()
