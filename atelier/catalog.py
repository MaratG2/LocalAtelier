"""Trusted model adapters. Add future providers here, without changing projects."""
CATALOG = {
    "vdn-h3": {
        "id": "vdn-h3", "name": "VDN-H3 · MiniMax H3", "family": "MiniMax H3", "service": "video",
        "description": "Local video with stereo sound, keyframes and multimodal references. Preview first, then finish at full resolution.",
        "precision": "INT8 ConvRot · NVFP4 encoder", "download_gb": 56.7, "vram_gb": 16,
        "license": "MiniMax H3 Community License", "license_url": "https://huggingface.co/OpenVDN/vdn-minimax-h3/blob/751739ee5b9e3ac802dca5d5111075fdaeb47885/LICENSE",
        "hub_repo": "OpenVDN/vdn-minimax-h3-edge", "hub_revision": "da37681f5a1f7015fdb63482142b865111b687d3",
        "weight_dir": "weights", "port": None, "steps": 8, "max_steps": 20,
        "max_references": 12, "transparent": False, "max_size": 1344, "files": [],
    },
    "trellis2": {
        "id": "trellis2", "name": "TRELLIS.2", "family": "TRELLIS", "service": "3d",
        "description": "Image-to-3D with textured geometry and native PBR materials. One reference, a complete object.",
        "precision": "GGUF Q8 · CUDA", "download_gb": 10.0, "vram_gb": 16,
        "license": "MIT · DINOv3 license", "license_url": "https://github.com/microsoft/TRELLIS.2#license",
        "hub_repo": "ilintar/trellis2-gguf", "hub_revision": "a57397bd3d351599d9729fc144b3f87c3f87d65b",
        "weight_dir": "weights", "port": None, "steps": 12, "max_steps": 30,
        "max_references": 1, "transparent": False, "max_size": 1024,
        "files": ["q8/" + name + ".gguf" for name in (
            "birefnet", "dinov3", "ss_flow", "ss_dec", "shape_flow_512", "shape_flow_1024",
            "shape_dec", "tex_flow_512", "tex_flow_1024", "tex_dec")],
    },
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
    {"id": "3d", "name": "3D studio", "available": True, "description": "Create textured objects with TRELLIS.2."},
    {"id": "video", "name": "Video", "available": True, "description": "Create video and sound with MiniMax H3."},
    {"id": "audio", "name": "Audio", "available": False, "description": "Sound, speech and music on your machine."},
]
