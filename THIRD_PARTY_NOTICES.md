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
