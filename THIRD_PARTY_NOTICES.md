# Third-party notices

Local Atelier's application code is MIT licensed; see LICENSE. Dependencies and model weights retain their own licenses.

- `atelier/providers/hidream/models/` contains adapted HiDream O1 inference code from [HiDream-ai/HiDream-O1-Image](https://github.com/HiDream-ai/HiDream-O1-Image). The MIT copyright notice is retained in `atelier/providers/hidream/LICENSE`. Adaptations include local imports, attention fallback, image memory offloading, progress reporting, and output sizing.
- `atelier/providers/hidream/models/qwen3_vl_transformers.py` includes code by the Qwen Team and Hugging Face, licensed under Apache 2.0. Its original header is retained. A copy of Apache 2.0 is in `licenses/Apache-2.0.txt`.
- [ComfyUI](https://github.com/Comfy-Org/ComfyUI) is downloaded separately into the Qwen model bundle at revision `0df64eb242b7c5759c3e86afd5d1846d923b1033`. Its own GPL-3.0 license and source remain in that bundle. Local Atelier communicates with the separate process using its HTTP API.
- Qwen weights are downloaded from [Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1). The underlying model uses the [Qwen Research License](https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE). Local Atelier's MIT license does not relicense those weights or grant commercial rights to them.
- HiDream weights are downloaded from [WaveCut's SDNQ 4-bit model](https://huggingface.co/WaveCut/HiDream-O1-Image-SDNQ-4bit-dynamic-uint4-th1e-2). See the publisher's model card and [original HiDream model](https://huggingface.co/HiDream-ai/HiDream-O1-Image) for model licensing.
- React, Vite, TypeScript, Lucide, Flask, Pillow, PyTorch, Transformers, Diffusers, SDNQ, and other installed dependencies retain their respective package licenses. Geist fonts are bundled via Fontsource under their SIL Open Font License; see `licenses/Geist-OFL.txt`.
- The decorative vase photograph used on Home was generated for this application. It is an interface asset, not a benchmark of either local model. Gallery images shown while using the application are actual locally generated assets.

Model files and dependency environments are not distributed in this Git repository.

- The 3D workflow and geometry normalization conventions draw on [felippeomgt/mymeshy](https://github.com/felippeomgt/mymeshy), revision `1854487f1e6c918becc859850727bc83d9ad24cd`, MIT © 2026 Felippe. Its notice is in `licenses/MyMeshy-MIT.txt`. No legacy model adapters or procedural generation fallback are included.
- [TRELLIS.2](https://github.com/microsoft/TRELLIS.2) is Microsoft's image-to-3D model. Its MIT license is in `licenses/Trellis2-MIT.txt`. Local Atelier downloads the Q8 conversions from [ilintar/trellis2-gguf](https://huggingface.co/ilintar/trellis2-gguf), with the exact revision and file list in the catalog.
- [trellis.cpp](https://github.com/pwilkin/trellis.cpp), MIT © 2026 Piotr Wilkin, supplies the separately downloaded native CUDA runtime. Its notice is in `licenses/TrellisCPP-MIT.txt`. The runtime is pinned by release and archive SHA-256. Its GGML, xatlas, CUDA runtime and other dependencies retain their upstream licenses.
- DINOv3 image conditioning retains the [DINOv3 license](https://github.com/facebookresearch/dinov3/blob/main/LICENSE.md), copied to `licenses/DINOv3.txt`. BiRefNet background-removal weights retain their [upstream MIT license](https://github.com/ZhengPeng7/BiRefNet). Local Atelier's application license does not relicense either component.
- Three.js, glTF Transform, meshoptimizer, trimesh and NumPy retain their installed package licenses. glTF Transform and meshoptimizer simplify geometry while preserving embedded materials and UV attributes.
