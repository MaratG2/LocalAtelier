# Local verification

Tested on 10 October 2026, Windows, NVIDIA GeForce RTX 5060 Ti 16 GB, 32 GB system RAM, PyTorch 2.13.0 with CUDA 13.0.

Both models were installed into new, isolated environments under this repository. Existing weight bytes were copied into the owned bundles to avoid redundant downloads, then checked against the pinned publisher manifests. Neither runtime uses another application checkout, environment, server or weight path. Inference processes and their command lines were inspected during model switching.

## Real GPU checks

| Case | Steps | Output | Observed generation time |
|---|---:|---|---:|
| Qwen text-to-image, green vase | 25 | 1024×1024 | 39.37 s |
| Qwen text-to-image, burgundy teapot | 25 | 1024×1024 | 39.07 s |
| Qwen composition using both preceding images | 25 | 1024×1024 | 82.87 s |
| Qwen background removal using a landscape reference | 25 | 1024×704 RGBA | 36.80 s |
| HiDream text-to-image, blue cup | 50 | 1024×1024 export from 2048×2048 inference | 325.20 s |

Times include prompt/reference encoding, inference and result decoding/transfer after the worker is ready; they exclude process startup. These are individual observations, not averaged benchmarks. Cold startup took several minutes in newly created environments. HiDream used PyTorch SDPA attention, with its vocabulary tables offloaded to CPU. The Qwen transparent result had alpha extrema 0 and 255; it was not an opaque image with a drawn checkerboard. Reference aspect ratios are rounded to the model's 64-pixel grid.

The real queue exercised Qwen → HiDream → Qwen switching. The earlier worker process tree was stopped before the next model loaded. Installation and verification were exercised with the actual model files. Permanent model deletion was exercised against owned disposable test bundles, including refusal of outside paths and missing ownership markers; the real multi-gigabyte installations were retained.

## Automated and browser checks

- 21 API/runtime tests: project archive/restore, asset recovery, PNG metadata and alpha persistence, validation, queue bounds and cancellation, active-reference protection, model-operation exclusion, owned deletion, tamper detection, refusal of unverified weights, origin/host guards, and refusal to adopt an occupied worker port.
- TypeScript and Vite production build passed. The GitHub workflow repeats API tests and frontend compilation without GPU dependencies.
- In-app browser smoke checks covered the real home, project and image studio screens. Its viewport override did not hold the requested size, so regular Playwright Chromium checked explicit 1536×1024 and 390×844 viewports.
- Browser interaction checks passed: create/rename/pin/archive/restore project; favorite, list view, image details, PNG download, trash and restore; search and settings reuse; reference upload; model-delete dialog cancellation; diagnostics; mobile navigation and seed controls.
- No JavaScript errors, relevant console warnings, framework overlays, or horizontal overflow were observed in that run. The archive-list refresh and an asynchronous dialog-reopening bug found by the run were fixed and the flows retested.

## Scope of these results

Maximum-reference-count jobs, all aspect ratios, 2K Qwen exports, and other GPUs/drivers were not exhaustively tested in this application. Model capabilities in the catalog are not speed or memory guarantees for every setting. 3D, video and audio are planned services only. GPU inference is not run in GitHub CI.
