"""HiDream O1 inference using the vendored model implementation."""
import tempfile
from pathlib import Path

from .model_runtime import configure_image_memory, image_device_map
from .settings import resolve_settings, render_dimensions


class HiDreamBackend:
    def __init__(self, weights, temp_root):
        import torch
        import sdnq  # noqa: F401: register quantized layers
        from transformers import AutoConfig, AutoProcessor
        from .models.qwen3_vl_transformers import Qwen3VLForConditionalGeneration
        torch.set_float32_matmul_precision("high")
        self.processor = AutoProcessor.from_pretrained(weights, local_files_only=True)
        config = AutoConfig.from_pretrained(weights, local_files_only=True)
        self.model = Qwen3VLForConditionalGeneration.from_pretrained(weights, dtype=torch.bfloat16, device_map=image_device_map(config), local_files_only=True).eval()
        configure_image_memory(self.model)
        tokenizer = getattr(self.processor, "tokenizer", self.processor)
        for name in ("boi", "bor", "eor", "bot", "tms"):
            setattr(tokenizer, name + "_token", f"<|{name}_token|>")
        self.temp_root = Path(temp_root)
        self.temp_root.mkdir(parents=True, exist_ok=True)

    def generate(self, *, prompt, width, height, seed, references, callback, mode, num_inference_steps, **unused):
        from .models.pipeline import generate_image
        effective_mode = "subject" if mode == "reference" and len(references) > 1 else "edit" if references else "t2i"
        settings = resolve_settings("full", effective_mode, {"num_inference_steps": num_inference_steps})
        with tempfile.TemporaryDirectory(dir=self.temp_root) as folder:
            paths = []
            for i, image in enumerate(references):
                path = Path(folder) / f"reference-{i}.png"
                image.convert("RGB").save(path)
                paths.append(str(path))
            image = generate_image(model=self.model, processor=self.processor, prompt=prompt,
                                   ref_image_paths=paths or None, width=width, height=height, seed=seed,
                                   keep_original_aspect=False, callback=lambda step, total, *args: callback(step + 1, total), **settings)
        rw, rh = render_dimensions(width, height, bool(references))
        return image, {"render_width": rw, "render_height": rh, "parameters": settings}
