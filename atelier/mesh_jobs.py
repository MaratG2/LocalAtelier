"""3D jobs share the same GPU queue as image generation."""
import json
import shutil
import time
from pathlib import Path

from .generation import integer, save_image
from .meshes import save_mesh, simplify_mesh
from .providers.trellis2 import MeshCancelled
from .storage import identifier


def validate_mesh(data, store):
    allowed = {"project_id", "model_id", "mode", "prompt", "reference_ids", "seed", "num_inference_steps",
               "resolution", "texture_size", "target_triangles", "texture", "background_removal", "source_mesh_id"}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError("Unsupported 3D generation settings")
    project_id = data.get("project_id", "inbox")
    project = store.project(project_id) if isinstance(project_id, str) else None
    if not project or project["archived"]:
        raise ValueError("Select an active project")
    if data.get("model_id", "trellis2") != "trellis2":
        raise ValueError("TRELLIS.2 is the supported 3D model")
    mode = data.get("mode", "image-to-3d")
    if mode not in ("image-to-3d", "text-to-3d", "simplify"):
        raise ValueError("Choose image-to-3D or text-to-3D")
    prompt = data.get("prompt", "")
    if not isinstance(prompt, str) or len(prompt) > 4000 or (mode == "text-to-3d" and not prompt.strip()):
        raise ValueError("Describe your object using 1–4,000 characters")
    refs = data.get("reference_ids", [])
    if not isinstance(refs, list) or any(not isinstance(r, str) for r in refs) or len(refs) > 1:
        raise ValueError("TRELLIS.2 accepts one reference image")
    if (mode == "image-to-3d" and len(refs) != 1) or (mode != "image-to-3d" and refs):
        raise ValueError("Image-to-3D needs one image; text-to-3D creates its own reference")
    for ref in refs:
        asset = store.asset(ref)
        if not asset or asset["deleted"] or asset["kind"] not in {"generated", "reference"}:
            raise ValueError("Choose an available reference image")
    request = {"project_id": project_id, "model_id": "trellis2", "mode": mode, "prompt": prompt.strip(), "reference_ids": refs, "batch_size": 1}
    for key, default, lo, hi in [("seed", 42, 0, 4294967295), ("num_inference_steps", 12, 4, 30),
                                 ("resolution", 512, 512, 1024), ("texture_size", 2048, 512, 4096), ("target_triangles", 30000, 1000, 300000)]:
        request[key] = integer(data.get(key, default), key, lo, hi)
    if request["resolution"] not in (512, 1024) or request["texture_size"] not in (512, 1024, 2048, 4096):
        raise ValueError("Choose 512 or 1024 geometry and a power-of-two texture size")
    texture = data.get("texture", True)
    background = data.get("background_removal", "auto")
    if not isinstance(texture, bool) or background not in ("auto", "birefnet"):
        raise ValueError("Invalid material or background setting")
    request.update(texture=texture, background_removal=background)
    if mode == "text-to-3d":
        request["image_model_id"] = "qwen-image-2.1"
    if mode == "simplify":
        source_id = data.get("source_mesh_id")
        asset = store.asset(source_id) if isinstance(source_id, str) else None
        if not asset or asset["kind"] != "mesh" or asset["deleted"]:
            raise ValueError("Choose an available mesh to simplify")
        request["source_mesh_id"] = source_id
        request["reference_ids"] = [source_id]  # Protect the source while queued.
    return request


def run_mesh_job(queue, job_id, request, callback):
    store, runtime = queue.store, queue.runtime
    cancelled = lambda: job_id in queue.cancelled
    started = time.monotonic()
    project_root = queue.models.project_root
    work = store.root / "runtime/mesh-jobs" / identifier()
    work.mkdir(parents=True)
    native_work = None
    try:
        if request["mode"] == "simplify":
            source = store.asset(request["source_mesh_id"])
            path = store.assets / source["filename"]
            metadata = {**source["metadata"], "parent_asset_id": source["id"], "operation": "simplify"}
            name = source["name"][:65] + " · simplified"
        else:
            refs = request["reference_ids"][:]
            if request["mode"] == "text-to-3d":
                callback("Creating concept image with Qwen", 0)
                image_request = {"model_id": "qwen-image-2.1", "mode": "t2i", "prompt": request["prompt"] + ". A single complete object, centered, three-quarter view, plain neutral background, even studio lighting, no text, no cropped parts.",
                    "width": 1024, "height": 1024, "seed": request["seed"], "num_inference_steps": 25,
                    "keep_original_aspect": False, "transparent_background": False}
                image, image_metadata = runtime.generate(image_request, [], lambda phase, percent: callback("Concept · " + phase, round(percent * .2)))
                concept = save_image(store, image, request["project_id"], kind="generated", name=request["prompt"][:70] + " · concept",
                    prompt=image_request["prompt"], model_id="qwen-image-2.1", seed=request["seed"], metadata={**image_metadata, "mesh_job_id": job_id})
                refs = [concept["id"]]
                request["reference_ids"] = refs
                store.update_job(job_id, result_ids=json.dumps(refs), request=json.dumps(request))
            if cancelled():
                raise MeshCancelled()
            reference = store.assets / store.asset(refs[0])["filename"]
            # Runtime method is replaceable for isolated tests; production invokes native CUDA.
            mesh_progress = (lambda phase, percent: callback(phase, 20 + round(percent * .8))) if request["mode"] == "text-to-3d" else callback
            path, metadata = runtime.generate_mesh(request, reference, mesh_progress, cancelled)
            native_work = Path(path).parent
            metadata["reference_ids"] = refs
            name = request["prompt"][:80] or store.asset(refs[0])["name"][:80]
        if cancelled():
            raise MeshCancelled()
        callback("Optimizing mesh · preserving material and UVs", 96)
        optimized = work / "optimized.glb"
        simplify_mesh(path, optimized, request["target_triangles"], project_root)
        if cancelled():
            raise MeshCancelled()
        metadata.update(settings=request, job_id=job_id, elapsed_seconds=round(time.monotonic() - started, 2), target_triangles=request["target_triangles"])
        callback("Saving mesh and texture maps", 99)
        asset = save_mesh(store, optimized, request["project_id"], name=name, prompt=request["prompt"], seed=request["seed"], metadata=metadata)
        return asset
    finally:
        # Both directories are unique scratch directories created for this job.
        shutil.rmtree(work, ignore_errors=True)
        if native_work and native_work.resolve().is_relative_to((runtime.root / "trellis2").resolve()):
            shutil.rmtree(native_work, ignore_errors=True)
