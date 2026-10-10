"""Trusted model adapters. Add future providers here, without changing projects."""
CATALOG = {
    "qwen-image-2.1": {
        "id": "qwen-image-2.1", "name": "Qwen-Image-2.1", "family": "Qwen", "service": "images",
        "description": "Precise creation, multi-image composition and native transparent backgrounds.",
        "precision": "INT8 ConvRot", "download_gb": 17.3, "vram_gb": 16,
        "license": "Qwen Research License", "license_url": "https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE",
        "hub_repo": "Comfy-Org/Qwen-Image-2.1", "hub_revision": "df94239739eef7205973a145ffa6f441f7b64e84",
        "weight_dir": "weights", "port": 7892,
        "steps": 25, "max_steps": 60, "max_references": 10,
        "transparent": True, "max_size": 2048,
        "files": ["diffusion_models/qwen_image_2.1_int8_convrot.safetensors", "text_encoders/qwen3vl_8b_int8_convrot.safetensors", "vae/qwen_image_2.1_vae_bf16.safetensors"],
    },
    "hidream-o1": {
        "id": "hidream-o1", "name": "HiDream O1", "family": "HiDream", "service": "images",
        "description": "Expressive image generation and reference editing with the full O1 model.",
        "precision": "SDNQ 4-bit", "download_gb": 10.7, "vram_gb": 16,
        "license": "MIT", "license_url": "https://huggingface.co/HiDream-ai/HiDream-O1-Image",
        "hub_repo": "WaveCut/HiDream-O1-Image-SDNQ-4bit-dynamic-uint4-th1e-2", "hub_revision": "601607d413f01bc69e708a6467356640900db374",
        "weight_dir": "weights", "port": 7894,
        "steps": 50, "max_steps": 100, "max_references": 8,
        "transparent": False, "max_size": 2048, "files": None,
    },
}

SERVICES = [
    {"id": "images", "name": "Images", "available": True, "description": "Create, edit and combine references."},
    {"id": "3d", "name": "3D objects", "available": False, "description": "From a concept to something dimensional."},
    {"id": "video", "name": "Video", "available": False, "description": "Give your ideas a sense of motion."},
    {"id": "audio", "name": "Audio", "available": False, "description": "Sound, speech and music on your machine."},
]
