# Local verification

Tested on 10–11 October 2026, Windows, NVIDIA GeForce RTX 5060 Ti 16 GB, 32 GB system RAM. The image workers use PyTorch 2.13.0 with CUDA 13.0; the 3D worker uses the native CUDA runtime described below.

Both image models were installed into new, isolated environments under this repository. Existing weight bytes were copied into the owned bundles to avoid redundant downloads, then checked against the pinned publisher manifests. TRELLIS.2 was installed through its managed downloader. No runtime uses another application checkout, environment, server or weight path. Inference processes and their command lines were inspected during model switching.

## Real GPU checks

| Case | Steps | Output | Observed generation time |
|---|---:|---|---:|
| Qwen text-to-image, green vase | 25 | 1024×1024 | 39.37 s |
| Qwen text-to-image, burgundy teapot | 25 | 1024×1024 | 39.07 s |
| Qwen composition using both preceding images | 25 | 1024×1024 | 82.87 s |
| Qwen background removal using a landscape reference | 25 | 1024×704 RGBA | 36.80 s |
| HiDream text-to-image, blue cup | 50 | 1024×1024 export from 2048×2048 inference | 325.20 s |
| HiDream reference edit, recolor the vase | 12 | 1024×1024 export from 2048×2048 inference | 124.95 s |

Times include prompt/reference encoding, inference and result decoding/transfer after the worker is ready; they exclude process startup. These are individual observations, not averaged benchmarks. Cold startup took several minutes in newly created environments. HiDream used PyTorch SDPA attention, with its vocabulary tables offloaded to CPU. The Qwen transparent result had alpha extrema 0 and 255; it was not an opaque image with a drawn checkerboard. Reference aspect ratios are rounded to the model's 64-pixel grid.

The real queue exercised Qwen → HiDream → Qwen switching. The earlier worker process tree was stopped before the next model loaded. Installation and verification were exercised with the actual model files. Permanent model deletion was exercised against owned disposable test bundles, including refusal of outside paths and missing ownership markers; the real multi-gigabyte installations were retained.

## Automated and browser checks

- 33 API/runtime tests passed. The original 21 cover project archive/restore, asset recovery, PNG metadata and alpha persistence, validation, queue bounds and cancellation, active-reference protection, model-operation exclusion, owned deletion, tamper detection, refusal of unverified weights, origin/host guards, and refusal to adopt an occupied worker port. Twelve mesh tests add embedded GLB validation, actual geometry/material persistence, six export formats, image/text queue flows, model/reference protection, cancellation, simplification lineage, texture routes and bounded rendered previews. GPU inference is replaced with explicit fixtures in these unit tests.
- TypeScript and Vite production build passed. The GitHub workflow repeats API tests and frontend compilation without GPU dependencies.
- In-app browser smoke checks covered the real home, project and image studio screens. Its viewport override did not hold the requested size, so regular Playwright Chromium checked explicit 1536×1024 and 390×844 viewports.
- Browser interaction checks passed: create/rename/pin/archive/restore project; favorite, list view, image details, PNG download, trash and restore; search and settings reuse; reference upload; model-delete dialog cancellation; diagnostics; mobile navigation and seed controls.
- No JavaScript errors, relevant console warnings, framework overlays, or horizontal overflow were observed in that run. The archive-list refresh and an asynchronous dialog-reopening bug found by the run were fixed and the flows retested.

## TRELLIS.2 GPU checks

Installed and fully checksum-verified `trellis.cpp` v0.8.1 and the pinned Q8 GGUF bundle (9,997,159,776 weight bytes). All runs used 12 mesh sampling steps, a 2048-pixel texture atlas and a 512-resolution PBR field. The geometry preset is independent of the atlas size.

| Case | Geometry | Actual triangles | Observed time |
|---|---:|---:|---:|
| Burgundy teapot from project image | 512³ | 30,000 | 120.24 s pipeline metadata |
| Same teapot, detailed geometry | 1024³ | 49,996 | 458.53 s wall clock |
| Treasure chest from text, including Qwen concept | 512³ | 30,000 | 413.38 s wall clock |

These are single observations, not averages. The first time includes native inference and mesh optimization, stopping before final asset serialization; the wall-clock measurements include the complete queued job and polling interval. The text test includes cold Qwen startup and a 1024², 25-step concept render. The saved concept was then passed to TRELLIS.2 after Qwen's process tree exited. Native inference is a new process for each mesh job.

The 1024³ run's sampled total GPU usage peaked at **8,067 MiB**, using `nvidia-smi` at approximately one-second intervals. The full text workflow peaked at **15,563 MiB** during Qwen, sampled about every two seconds. These totals include desktop/browser GPU use; they are not per-process CUDA allocation measurements and can miss short spikes. No out-of-memory error occurred in these runs. The 512³ image-only run was not instrumented for peak memory.

The real native-process cancellation check stopped a running job in **0.91 seconds** after the cancel request, left no result asset or job scratch folder, and released the active model. Cancellation during Qwen concept rendering and CPU simplification is cooperative at stage boundaries.

The generated meshes have UVs and actual base-color and packed metallic/roughness textures. All six export routes returned usable files. GLB and OBJ downloads were also exercised through the UI. Simplifying the detailed teapot to a 10,000-triangle target produced **20,264 triangles** while preserving UV/material boundaries; this confirms the UI's target-versus-actual distinction.

### 3D interface verification

The in-app browser displayed the live mesh workspace. Playwright Chromium exercised explicit 1536×1024 and 390×844 sizes because the in-app viewport override did not hold the requested dimensions. Checks covered image selection, text mode, material/clay/wireframe/channel views, rotation/reset, real simplification, export downloads, favorites, trash/restore, GLB import, and image-model filtering. Final checks also verified the complete Generate button remains visible, asset selection is stable, and actual rendered thumbnails replace CPU previews.

No JavaScript errors, failed application requests, framework overlays or horizontal overflow were found. Headless Chromium emitted GPU-readback performance warnings during preview capture. Vite reports a 672 kB minified 3D chunk; it is loaded only when opening the 3D studio, with a 171 kB gzip transfer. These warnings do not fail the build.

The final visual comparison retained the accepted concept's light/forest-green palette, existing navigation, settings/viewer/assets arrangement, and result/export footer. The live viewer shows actual generated geometry rather than the concept illustration. Settings include the controls the selected runtime really supports, and the narrower asset rail gives the viewport more space. Mobile stacks the controls, viewport and assets without horizontal scrolling.

![3D studio with a real generated mesh](screenshots/mesh-studio.png)

[Mobile capture](screenshots/mesh-mobile.png)

## Scope of these results

Maximum-reference-count image jobs, all aspect ratios, 2K Qwen exports, all mesh settings, and other GPUs/drivers were not exhaustively tested in this application. Mesh quality was visually checked on the teapot and chest; this does not establish general reconstruction quality or printing readiness. Model capabilities in the catalog are not speed or memory guarantees for every setting. Video and audio remain planned. GPU inference is not run in GitHub CI. See the [3D guide](3d-studio.md) for unsupported workflows and export limits.
