# Local Atelier

A local creative workspace for your own GPU. Organize projects, create images, textured 3D objects and video with sound, edit references, and manage the models installed on your machine.

The application is free and MIT licensed. Inference uses your hardware; no hosted inference account or usage credits are required. Model weights have their own licenses, including the Qwen Research License and MiniMax H3 Community License.

![Local Atelier image studio with locally generated results](docs/screenshots/studio.png)

## What works

- Light studio interface with Home, Images, 3D studio, Video, Projects, Model library, and Settings.
- Project creation, renaming, descriptions, pinning, archiving, and restoration.
- Qwen-Image-2.1 with INT8 ConvRot diffusion and text encoder weights.
- HiDream O1 with SDNQ 4-bit weights and its image pipeline included in this repository.
- Text-to-image, single-image editing, and multiple reference images.
- Native transparent PNG output with Qwen; RGB output with HiDream.
- Aspect ratio, 1K/1.5K/2K export sizes, steps, seeds, batches, and a persistent job history.
- Search, favorites, grid/list views, image details, reusable settings with original references and edit masks, and PNG/JSON downloads.
- Confirmed deletion for images, videos and meshes, with recovery from Trash or permanent removal of their saved files.
- A password-locked personal space with encrypted projects, media and history. See [personal-space storage and access](docs/personal-space.md).
- Install/resume, publisher-checksum verification, and deletion of owned model installations.
- Automatic model switching: stop the previous worker before loading the next one on the GPU.
- Optional local image plugins with independent model runtimes, supported-mode controls and a Git-ignored `addons/` folder. See [the plugin API guide](docs/plugins.md).
- TRELLIS.2 image-to-3D and text-to-3D, with one managed 3D model.
- Interactive orbit viewer with PBR, clay, wireframe, base-color, metallic, roughness, and surface-normal views.
- Material-preserving simplification, embedded GLB imports, and GLB/glTF/OBJ/STL/PLY/texture exports.

VDN-H3 / MiniMax H3 adds text, keyframe and reference video generation, preview finishing, stereo sound and MP4/WAV exports. See [the video guide](docs/video-studio.md) and [the 3D studio guide](docs/3d-studio.md) for workflows and limits. Standalone audio generation remains planned.

Video generation is **Powered by MiniMax H3**.

![Local Atelier 3D studio with a real TRELLIS.2 result](docs/screenshots/mesh-studio.png)

## Windows setup

Requirements: a recent NVIDIA driver, a CUDA-capable NVIDIA GPU, [uv](https://docs.astral.sh/uv/getting-started/installation/), and Node.js 22 or newer. The target machine is an RTX 5060 Ti 16 GB with 32 GB of system RAM. Allow approximately 55–65 GB for both image model installations and environments, plus space for outputs and package caches. TRELLIS.2 adds about 10 GB of Q8 weights and a native CUDA runtime.

```powershell
git clone https://github.com/MaratG2/LocalAtelier.git
cd LocalAtelier
./setup.ps1
./Start.cmd
```

If local script execution is restricted, run `powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1` for setup. This changes execution policy only for that setup process. Afterwards, double-click **Start.cmd**: startup uses the local Python environment directly and does not require PowerShell.

Open **http://127.0.0.1:7870**, visit **Model library**, and install a model. Installation downloads its pinned weights and creates an isolated GPU environment (or a pinned native CUDA runtime for TRELLIS.2). Verification hashes every required file against the publisher's pinned manifest. A failed installation can be resumed from the same button. Internet access is needed for installation and verification; generation runs locally with offline model loading.

The studio runs in the background; the launcher window closes after startup. Reopening **Start.cmd** opens the existing studio without starting a duplicate. **Restart.cmd** requests a graceful restart; **Stop.cmd** stops the studio and releases its GPU workers. Do not terminate processes manually.

Backend source updates reload automatically after a three-second settling period, once generation, model operations and incognito sessions have ended. An open incognito session delays restart to protect its unsaved results. Normal saved projects and assets stay intact. Updates do not download themselves or install changed dependencies; rerun setup when dependencies change. Frontend builds are served immediately, but an already open page may need refreshing to load a new JavaScript bundle.

On the first managed launch, an older idle studio can be replaced automatically. The launcher verifies its API data directory, process command and working directory, then asks that studio to release its owned workers before replacing its web process. An unrelated process or a different checkout is never stopped. If the port is occupied by an unrecognized application, startup explains the conflict.

`Start.cmd --no-browser` skips opening a browser; `Start.cmd --port 7871` chooses another app port. Use the same port with Restart/Stop. The PowerShell entry point remains compatible (`./start.ps1 -NoBrowser` / `-Port 7871`) and now delegates to the same manager. Internal GPU worker ports 7892–7894 must be free. Startup diagnostics and launcher state are under `data/runtime/launcher/`. Automatic reload does not recover an unexpected server crash in a restart loop: inspect the logs and reopen Start.cmd after fixing the cause.

## Phone access on the same network

Connect the phone to the same home network as the computer. In **Settings → Use on your phone**, find the computer's network URL and open it on the phone. `localhost` and `127.0.0.1` always refer to the device opening the address, so they cannot reach the PC from a phone. Keep the PC awake and the studio running.

Run **Enable phone access.cmd** once and approve the Windows administrator prompt to allow the studio through Windows Firewall. The rule permits TCP port 7870 from the local subnet on physical Ethernet/Wi-Fi adapters only. For a custom port, run `powershell -NoProfile -ExecutionPolicy Bypass -File .\phone-access.ps1 -Port 7871`. Run the helper again after changing network adapters. Guest Wi-Fi isolation and VPNs can prevent devices from connecting; use the main home Wi-Fi network. Restart the studio if the computer's network address changes.

The normal workspace has no login and is available to trusted devices on the local subnet. Personal space still requires its password, but the HTTP connection is not encrypted. Do not expose this port to the internet. Host and origin validation stay enabled, and requests from outside detected home subnets are rejected. To disable LAN access, stop the studio, set `$env:ATELIER_LOCAL_ONLY='1'`, and start it again from that PowerShell session.

## Self-contained storage

Everything belonging to the studio lives under this checkout:

```text
atelier/                     API, queue, runtime management and inference providers
frontend/                    React + TypeScript interface and bundled fonts
.venv/                       lightweight application environment
models/qwen-image-2.1/        Qwen weights, environment and pinned ComfyUI engine
models/hidream-o1/            HiDream weights and environment
models/trellis2/              TRELLIS.2 Q8 weights and native CUDA runtime
models/vdn-h3/                H3 weights, owned Python, FreeVideo and encoder runtime
data/atelier.sqlite3         projects, assets, settings and job history
data/assets/                 PNGs, GLBs, MP4s, reference media, thumbnails and metadata
data/runtime/                worker logs and temporary runtime files
```

There is no installation discovery, external generator adapter, folder linking, or dependency on another personal repository. Only the declared packages, pinned ComfyUI engine, pinned TRELLIS.2 CUDA runtime, pinned H3 runtime sources, and published model weights are downloaded. Standard system tools and their caches are managed by their installers.

Weights, environments, local projects, generated assets, and logs are excluded from Git. Back up `data/` with the studio stopped to preserve your work. Deleting a model removes only its owned installation; it keeps every project and generated asset. Trash and archived projects are recoverable and continue to occupy disk space.

## Model profiles

| Model | Weights | Default steps | References | Output |
|---|---|---:|---:|---|
| Qwen-Image-2.1 | INT8 ConvRot, about 17.3 GB on disk | 25 | Up to 10 | RGB / native RGBA |
| HiDream O1 | SDNQ 4-bit, about 10.7 GB on disk | 50 | Up to 8 | RGB |
| TRELLIS.2 | GGUF Q8, about 10 GB on disk | 12 | One image | Textured GLB |
| VDN-H3 / MiniMax H3 | INT8 ConvRot + NVFP4 encoder, about 56.7 GB on disk | 8 + 3 | Keyframes or multimodal references | Video + stereo audio |

Disk size is not peak VRAM use. Qwen offloads components as needed; low-VRAM mode is available in Settings. HiDream keeps the vocabulary embedding/output head on CPU to make room for image inference. It renders at its model training scale before resizing to the requested export dimensions. Cold startup can take several minutes. Reference-heavy and larger jobs take longer and can need additional system RAM.

Start with 1K and the default steps. The queue runs one image, mesh or video job at a time, accepts up to four jobs, and allows batches of up to four images. “Stop after image” preserves the image currently being rendered and skips the remaining batch. Jobs interrupted by a studio restart are marked interrupted; completed assets remain available. Mesh cancellation terminates the owned TRELLIS process; during the concept-image stage it waits for the current image.

## Development

### Editing a selected area

In Images, add one reference and choose **Edit → Paint area to edit**. Paint the area to change, use the eraser or Undo to refine it, then choose **Use selection** and describe the desired change. Edge softness feathers the change inward, with gentle boundary color matching. Models that expose edit strength also show that control inside the selection editor. Draw slightly beyond the object when its silhouette needs to change.

Selected-area edits keep the original image dimensions and preserve every unselected pixel, including transparency. Qwen and supported ComfyUI image adapters also restrict latent denoising with the mask; HiDream uses the final protected composite. A mask controls where an edit appears, but the model and prompt still determine how well the new content fits the scene.

Image models stay loaded between generations in the same workspace or private session by default. Switching models or workspaces, locking or leaving a private session, and explicitly enabling **Unload after generation** release them. Private input/output scratch files are cleared after each job while the worker stays warm; closing the private session removes its remaining runtime scratch.

H3 also reuses a session-owned worker between clips. Compatible model components remain cached while memory permits; the 16 GB memory planner can still unload individual components between encoding, sampling and decoding. See [Video studio](docs/video-studio.md) for details.

See [creative workflows](docs/creative-workflows.md) for English/Russian localization, incognito sessions, project art direction, sprite sheets and tile maps.

```powershell
# API checks use isolated temporary storage and a fake GPU worker.
.venv/Scripts/python.exe -m unittest discover -s tests -v

# Production build
cd frontend
npm ci
npm run build

# Optional frontend dev server; keep the API on port 7870 in another terminal.
npm run dev
```

The frontend development server binds to 127.0.0.1:5175 and proxies `/api` to the local API. The production application serves the built frontend directly. CI checks the API and frontend without downloading weights or requiring a GPU.

See [Video studio](docs/video-studio.md) for H3 modes, presets, preview finishing and license details.

See [architecture](docs/architecture.md) for provider extension points, [hardware and browser checks](docs/verification.md) for measured results, and [third-party notices](THIRD_PARTY_NOTICES.md) for licenses. This release is a single-user, localhost desktop service; it has no remote account or multi-user server layer.
