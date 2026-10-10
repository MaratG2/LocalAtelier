"""Execute the pinned TRELLIS.2 model on our owned CUDA process, with no server port."""
import os
import re
import shutil
import time
from pathlib import Path

from PIL import Image, ImageOps

from ..catalog import CATALOG
from ..models import installed, weights_at
from ..storage import identifier
from ..trellis_install import VERSION, REVISION, binary_at


class MeshCancelled(Exception):
    pass


def generate(runtime, request, reference, callback, cancelled):
    model = CATALOG["trellis2"]
    record = runtime.store.one("SELECT * FROM models WHERE id='trellis2'")
    if not record or not record["verified"] or not installed(model, record["runtime_path"]):
        raise RuntimeError("Install and verify TRELLIS.2 in the model library first")
    bundle = Path(record["runtime_path"])
    work = runtime.root / "trellis2" / identifier()
    work.mkdir(parents=True)
    input_path, output = work / "input.png", work / "model.glb"
    succeeded = False
    try:
        with Image.open(reference) as source:
            image = ImageOps.exif_transpose(source).convert("RGBA")
            image.thumbnail((2048, 2048))
            image.save(input_path)
        args = [binary_at(bundle), input_path, output, "--models", weights_at(model, bundle) / "q8",
                "--model", "trellis", "--gpu", "0", "--require-gpu", "--res", request["resolution"],
                "--seed", request["seed"], "--steps", request["num_inference_steps"],
                "--atlas", request["texture_size"], "--tex-res", "512", "--webp", "off", "--dump-bg"]
        if not request["texture"]:
            args.append("--no-texture")
        if request["background_removal"] == "birefnet":
            args += ["--bg-removal", "birefnet"]
        callback("Switching model · freeing GPU memory", 0)
        with runtime.lock:
            runtime.release()
            if cancelled():
                raise MeshCancelled()
            runtime.active_model = "trellis2"
            runtime.phase = "Loading TRELLIS.2"
            # All scratch files stay inside this repo. Do not inherit debug overrides.
            env = {k: v for k, v in os.environ.items() if not k.startswith("TRELLIS_")}
            cache = runtime.root / "cache/trellis2/cuda"
            cache.mkdir(parents=True, exist_ok=True)
            env.update(TMP=str(work), TEMP=str(work), CUDA_CACHE_PATH=str(cache))
            process = runtime._start(args, work, env, "trellis2")
        start = time.monotonic()
        log_path = runtime.root / "trellis2.log"
        offset, tail, stage = 0, "", 0
        labels = {1: "Removing background", 2: "Reading reference image", 3: "Generating sparse structure",
                  4: "Generating shape", 5: "Decoding geometry", 6: "Generating PBR material", 7: "Unwrapping and baking textures"}
        while True:
            if cancelled():
                raise MeshCancelled()
            if time.monotonic() - start > 3600:
                raise RuntimeError("TRELLIS.2 exceeded the one-hour generation limit; see runtime logs")
            with log_path.open("r", encoding="utf-8", errors="replace") as log:
                log.seek(offset)
                text = log.read()
                offset = log.tell()
            tail = (tail + text)[-6000:]
            for match in re.finditer(r"\[([1-7])/[67]\]", text):
                next_stage = int(match[1])
                if next_stage > stage:
                    stage = next_stage
                    runtime.phase = labels[stage]
                    callback(runtime.phase, min(92, (stage - 1) * 15))
            if process.poll() is not None:
                break
            time.sleep(.4)
        if process.returncode or not output.is_file() or output.stat().st_size < 24:
            raise RuntimeError(f"TRELLIS.2 failed (exit {process.returncode}). " + tail[-1800:])
        callback("Preparing mesh asset", 94)
        succeeded = True
        return output, {
            "elapsed_seconds": round(time.monotonic() - start, 2), "runtime": "trellis.cpp",
            "runtime_version": VERSION, "runtime_revision": REVISION,
            "weights_repo": model["hub_repo"], "weights_revision": model["hub_revision"],
            "precision": "Q8", "resolution": request["resolution"], "texture_size": request["texture_size"],
            "mock_mode": False, "pbr_source": "TRELLIS.2 texture decoder" if request["texture"] else None,
        }
    finally:
        runtime.release("trellis2")
        if not succeeded:
            shutil.rmtree(work, ignore_errors=True)
