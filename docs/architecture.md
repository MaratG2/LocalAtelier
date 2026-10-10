# Architecture

Local Atelier separates the project library from GPU inference. The Flask application owns an SQLite database and image files. React consumes its JSON API. A single generation queue turns validated requests into persistent jobs and calls one selected worker at a time.

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

The catalog is intentionally code-reviewed rather than an arbitrary executable plugin loader. New media types will also need asset delivery and editing surfaces appropriate to their format. The current image-specific persistence fields are not a completed 3D/video/audio implementation.

## Boundaries

- GPU installation is Windows-only in this release; API unit tests run cross-platform.
- One user and one GPU queue; no login, remote server mode, or shared team projects.
- The gallery returns the newest 500 matching assets; pagination is future work.
- Ten Qwen/eight HiDream references are accepted by the interface, but the upper limit is not a performance promise on a 16 GB card.
- Trashing does not erase images from disk. Permanent asset purging is not implemented.
- Model verification needs the publisher's online manifest. Offline generation needs an already installed model.
