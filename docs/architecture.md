# Architecture

Local Atelier separates the project library from GPU inference. The Flask application owns an SQLite database and image/mesh/video files. React consumes its JSON API. A single generation queue turns validated requests into persistent jobs and calls one selected worker at a time.

## 3D service

`atelier/mesh_jobs.py` validates and executes mesh jobs through the same queue as images. Text jobs reserve both Qwen and TRELLIS.2 against model deletion/verification, save their concept image, then switch the GPU to mesh generation. `atelier/providers/trellis2.py` owns the native CUDA CLI process, reports its seven stages, handles cancellation and requires GPU execution. `atelier/trellis_install.py` downloads and verifies the pinned release; no other application installation or server is discovered.

`atelier/meshes.py` reads embedded GLBs, saves mesh assets and actual material maps, creates a geometry preview, and exports portable formats. `frontend/scripts/simplify.mjs` performs attribute-aware simplification with glTF Transform and meshoptimizer. Models and project data stay separate; deleting a model never removes generated meshes.

`POST /api/meshes/jobs` accepts image-to-3D, text-to-3D and simplification requests. `POST /api/meshes/import` imports embedded GLBs. `/api/meshes/<id>/export?format=...` and `/textures/<name>` expose controlled output formats and whitelisted maps. `GET /api/assets?kind=mesh` returns mesh assets, while the default endpoint continues to return generated images. The schema stores mesh-specific details in existing asset/job JSON fields, preserving previous projects without a destructive migration.

`MeshStudio.tsx` composes the form, project assets and export/details dialogs. `MeshViewer.tsx` owns a Three.js renderer and orbit controls, with local procedural environment lighting and no CDN requests. The 3D route is loaded on demand. The browser can replace the initial CPU thumbnail with a bounded PNG rendered from the actual mesh; no generated concept mockup is used as an output preview.

## Video service

`atelier/videos.py` validates H3 requests and owns bounded media inspection, reference uploads, posters and filmstrips. `atelier/providers/vdn_h3.py` starts the pinned FreeVideo CLI inside its model bundle, monitors coordinator and worker event logs, and terminates only the owned process tree on cancellation. Preview assets retain their first-pass tensors; finishing produces a new asset with locked original settings. No hosted prompt service or external generator is used.

`atelier/video_install.py` installs an owned Python 3.12 environment and pinned source trees; `atelier/manifests/vdn-h3.json` lists 1,201 hashed model/config/table files. Prepared INT8 weights avoid full BF16 conversion. ComfyUI is used only as the encoder library inside a child process. Shared GPU serialization prevents H3 from overlapping image or mesh inference.

`POST /api/videos/jobs` accepts text, frames, references and finish requests. `POST /api/videos/uploads` validates short reference media. `GET /api/assets?kind=video` lists generated clips. Asset file responses support browser range requests; `/api/videos/<id>/filmstrip` returns sampled frames and `/audio` decodes a stereo WAV download. The React VideoStudio route is lazy loaded.

## Model lifecycle

`atelier/catalog.py` contains trusted, reviewed model definitions: pinned Hugging Face revisions, weight names, supported capabilities, inference defaults, and private worker ports. `atelier/models.py` installs each model under `models/<id>` with its own virtual environment and an ownership marker. Qwen additionally downloads a pinned ComfyUI source archive inside its bundle. Inference code is shipped under `atelier/providers/`; model installation never downloads another personal application.

Installation runs in a background thread and exposes phases, bounded logs, and errors to the library. Verification compares large LFS files using SHA-256 and ordinary repository files using Git blob SHA-1. A failed or missing file clears the verification stamp. Deletion checks the catalog ID, exact bundle location, ownership marker, symlink/junction status, and active job state before removing files. It cannot remove a path entered by a user because no arbitrary installation-path interface exists.

## Runtime

`atelier/runtime.py` owns child processes it starts. It terminates the previous process tree before loading a different model. Qwen uses a private HTTP worker plus the bundled ComfyUI process. HiDream uses a private HTTP worker with the vendored model implementation. A per-process token protects the worker endpoints; all services bind to loopback. The public application rejects cross-origin writes and untrusted hostnames.

The main application does not import Torch. Each worker imports only its own provider. Prompts and references travel over loopback; Hugging Face offline mode is set for inference. Settings can offload more Qwen components to system RAM or release the worker after each job. Normal shutdown releases all owned children. Force-killing the entire application bypasses Python cleanup; if needed, stop remaining Local Atelier worker processes before restarting.

## Projects, assets and jobs

`atelier/storage.py` initializes a WAL SQLite database under `data/`. Generated assets, references, thumbnails, and readable metadata sidecars share `data/assets/`. Generated PNGs also embed metadata. Projects are archived and images trashed through database flags. These actions preserve files and can be reversed. Model deletion does not touch assets.

`atelier/generation.py` validates requests, protects references used by active jobs, serializes GPU execution, and records batch results as each image completes. Seeds increment within a batch. Completed images survive later batch errors. Restarted jobs are marked interrupted rather than silently rerun. Cancellation is cooperative between images, so it does not invalidate an in-flight inference.

## Adding a provider

1. Add a reviewed catalog definition with a pinned revision, exact capabilities and license.
2. Add its inference implementation inside `atelier/providers/` and its dependency profile to the installer.
3. Extend `atelier/worker.py` and runtime startup for that provider. Return a Pillow image, metadata and real progress callbacks; propagate failures explicitly.
4. Exercise install, verify, delete, cold startup, model switching, reference handling, and real GPU inference on the target hardware.

The catalog is intentionally code-reviewed rather than an arbitrary executable plugin loader. New media types will also need asset delivery and editing surfaces appropriate to their format. Images, meshes and video share the asset table; a future standalone audio service needs its own validation and workspace.

## Boundaries

- GPU installation is Windows-only in this release; API unit tests run cross-platform.
- One user and one GPU queue; no login, remote server mode, or shared team projects.
- The gallery returns the newest 500 matching assets; pagination is future work.
- Ten Qwen/eight HiDream references are accepted by the interface, but the upper limit is not a performance promise on a 16 GB card.
- Trashing does not erase images from disk. Permanent asset purging is not implemented.
- Image and TRELLIS verification uses the publisher's online manifest; H3 ships a pinned manifest and verifies files locally. Offline generation needs an installed, verified model.
