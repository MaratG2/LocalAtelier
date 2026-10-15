"""Qwen-Image-2.1 over the local ComfyUI API; no custom nodes required."""
from __future__ import annotations

import io
import json
import os
import time
import uuid
from urllib.parse import urlsplit

import httpx
import websocket
from PIL import Image, ImageFilter
from .workflow import validate_workflow

MODEL = "qwen_image_2.1_int8_convrot.safetensors"
ENCODER = "qwen3vl_8b_int8_convrot.safetensors"
VAE = "qwen_image_2.1_vae_bf16.safetensors"
REQUIRED_NODES = {"UNETLoader", "CLIPLoader", "VAELoader", "TextEncodeQwenImage21", "QwenImage21Cache",
                  "EmptyLatentImage", "KSampler", "VAEDecode", "VAEDecodeTiled", "SaveImage", "LoadImage", "JoinImageWithAlpha"}


def build_workflow(prompt, width, height, seed, references, *, num_inference_steps=25,
                   guidance_scale=1.0, transparent_background=False, encoder=ENCODER):
    if transparent_background:
        prompt = f"This is an RGBA image with transparency. {prompt} The image has alpha channel and the background is transparent."
    graph = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": MODEL, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": encoder, "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "TextEncodeQwenImage21", "inputs": {
            "clip": ["2", 0], "vae": ["3", 0], "prompt": prompt, "negative_prompt": "", "resolution": 0}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "6": {"class_type": "QwenImage21Cache", "inputs": {"model": ["1", 0], "device": "auto", "dtype": "default"}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["6", 0], "positive": ["4", 0], "negative": ["4", 1],
            "latent_image": ["4", 2] if references else ["5", 0], "seed": seed,
            "steps": num_inference_steps, "cfg": guidance_scale, "sampler_name": "euler", "scheduler": "simple", "denoise": 1}},
        "8": {"class_type": "VAEDecodeTiled", "inputs": {"samples": ["7", 0], "vae": ["3", 0], "tile_size": 512, "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "LocalAtelier/qwen"}},
    }
    if width * height <= 1024 * 1024:
        # ComfyUI's normal decoder falls back to tiling on OOM. Avoid the cost
        # of nineteen overlapping decode tiles when a 1K canvas fits directly.
        graph["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}}
    for i, filename in enumerate(references, 1):
        loader, rgba = str(20 + i * 2), str(21 + i * 2)
        graph[loader] = {"class_type": "LoadImage", "inputs": {"image": filename}}
        # LoadImage separates transparency into an inverse-alpha mask. Rejoin it
        # before conditioning so transparent references reach the RGBA VAE intact.
        graph[rgba] = {"class_type": "JoinImageWithAlpha", "inputs": {"image": [loader, 0], "alpha": [loader, 1]}}
        graph["4"]["inputs"][f"images.image_{i}"] = [rgba, 0]
    return graph


class ComfyBackend:
    def __init__(self, url=None):
        self.url = (url or os.environ.get("QWEN_COMFY_URL", "http://127.0.0.1:7893")).rstrip("/")
        parsed = urlsplit(self.url)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.username or parsed.password:
            raise ValueError("QWEN_COMFY_URL must be a local HTTP address")
        self.encoder = os.environ.get("QWEN_TEXT_ENCODER", ENCODER)
        self.info = None

    def check(self):
        with httpx.Client(timeout=5, trust_env=False) as client:
            response = client.get(f"{self.url}/object_info")
            response.raise_for_status()
            info = response.json()
        missing = REQUIRED_NODES - info.keys()
        if missing:
            raise RuntimeError(f"ComfyUI is missing Qwen nodes: {', '.join(sorted(missing))}. Reinstall the model from the model library.")
        for node, field, filename in (("UNETLoader", "unet_name", MODEL), ("CLIPLoader", "clip_name", self.encoder), ("VAELoader", "vae_name", VAE)):
            if filename not in info[node]["input"]["required"][field][0]:
                raise RuntimeError(f"Missing model file: {filename}. Reinstall the model from the model library.")
        self.info = info
        from ..catalog import CATALOG
        return {"id": "Comfy-Org/Qwen-Image-2.1", "quantization": "INT8 ConvRot",
                "text_encoder_quantization": "W4A8" if "w4a8" in self.encoder else "INT8 ConvRot",
                "variant": self.encoder, "source_revision": CATALOG['qwen-image-2.1']['hub_revision']}

    def generate(self, *, prompt, width, height, seed, references, callback, **settings):
        client_id = uuid.uuid4().hex
        ws_url = self.url.replace("http://", "ws://", 1) + f"/ws?clientId={client_id}"
        # Connect before submitting: even a cached graph can complete immediately.
        with httpx.Client(timeout=60, trust_env=False) as client:
            uploaded = []
            for i, reference in enumerate(references):
                image = reference.copy()
                if i == 0:
                    image = image.resize((width, height), Image.Resampling.LANCZOS)
                else:
                    image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                    image = image.resize(tuple(max(32, round(v / 32) * 32) for v in image.size), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                image.save(buf, format="PNG")
                response = client.post(f"{self.url}/upload/image", files={"image": (f"qwen-{client_id}-{i}.png", buf.getvalue(), "image/png")},
                                       data={"type": "input", "subfolder": "LocalAtelier", "overwrite": "false"})
                response.raise_for_status()
                data = response.json()
                uploaded.append(f"{data['subfolder']}/{data['name']}" if data.get("subfolder") else data["name"])
            edit_mask = settings.pop('edit_mask', None)
            graph = build_workflow(prompt, width, height, seed, uploaded, encoder=self.encoder, **settings)
            if edit_mask is not None:
                # Import graph wiring without importing host-side blending dependencies.
                from .workflow import add_mask_nodes
                mask = edit_mask.resize((width, height), Image.Resampling.BILINEAR)
                radius = max(4, round(max(width, height) / 128))
                mask = mask.filter(ImageFilter.MaxFilter(radius * 2 + 1)).filter(ImageFilter.GaussianBlur(2))
                buf = io.BytesIO(); mask.save(buf, format='PNG')
                response = client.post(f'{self.url}/upload/image', files={'image': (f'mask-{client_id}.png', buf.getvalue(), 'image/png')}, data={'type': 'input'})
                response.raise_for_status()
                mask_name = response.json()['name']
                add_mask_nodes(graph, mask_name, uploaded[0], ['3', 0])
            # Save a fresh file even when the engine reuses an identical cached render.
            graph['9']['inputs']['filename_prefix'] = f'LocalAtelier/{client_id}'
            if self.info is not None:
                validate_workflow(graph, self.info)
            ws = websocket.create_connection(ws_url, timeout=1, suppress_origin=True)
            prompt_id = None
            try:
                response = client.post(f"{self.url}/prompt", json={"prompt": graph, "client_id": client_id})
                if response.is_error:
                    raise RuntimeError(f"ComfyUI rejected the workflow: {response.text[:1800]}")
                prompt_id = response.json()["prompt_id"]
                started, last_check = time.monotonic(), 0.0
                while True:
                    try:
                        message = ws.recv()
                        if isinstance(message, str) and message:
                            event = json.loads(message)
                            data = event.get("data", {})
                            if data.get("prompt_id") == prompt_id:
                                if event["type"] == "progress" and str(data.get("node")) == "7":
                                    callback(data["value"], data["max"])
                                elif event["type"] in {"execution_error", "execution_interrupted"}:
                                    raise RuntimeError(data.get("exception_message", "Qwen generation was interrupted"))
                    except websocket.WebSocketTimeoutException:
                        pass
                    now = time.monotonic()
                    if now - last_check >= 1:
                        response = client.get(f"{self.url}/history/{prompt_id}")
                        response.raise_for_status()
                        history = response.json().get(prompt_id)
                        last_check = now
                        if history:
                            if history.get("status", {}).get("status_str") == "error":
                                raise RuntimeError(f"Qwen generation failed: {history['status'].get('messages', [])}")
                            outputs = history.get("outputs", {}).get("9", {}).get("images", [])
                            if outputs:
                                response = client.get(f"{self.url}/view", params=outputs[0])
                                response.raise_for_status()
                                with Image.open(io.BytesIO(response.content)) as result:
                                    return result.copy()
                    if now - started > 3600:
                        # Delete only this queued prompt, never interrupt another client's job.
                        client.post(f"{self.url}/queue", json={"delete": [prompt_id]})
                        raise RuntimeError("Generation exceeded one hour. Check the ComfyUI console before retrying.")
            finally:
                ws.close()
                if prompt_id:
                    try:
                        client.post(f'{self.url}/history', json={'delete': [prompt_id]}).raise_for_status()
                    except httpx.HTTPError:
                        pass
