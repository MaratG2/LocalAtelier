# Local image plugins

Local Atelier discovers `addons/<plugin-id>/plugin.json` at startup. **Model library → Local plugins → Scan plugins** reloads the registry when generation and installation are idle. Scanning reads manifests; it does not import Python adapters. Malformed plugins appear as errors without hiding built-in models.

`addons/.gitignore` and the root ignore rules exclude plugin source, manifests, weights, virtual environments and caches from the main repository. Keep a plugin in its own repository if it should be distributed separately. Adding a plugin never publishes it. Git ignore rules do not prevent an explicit `git add --force`; inspect staged files before publishing.

Plugins execute trusted Python code with the current user's permissions. This is an extension API, not a sandbox. There is no remote marketplace or automatic code download during discovery.

## Manifest version 1

```json
{
  "api_version": 1,
  "id": "example-images",
  "name": "Example images",
  "version": "1.0.0",
  "adapter": "adapter.py",
  "models": [{
    "id": "illustration",
    "name": "Example illustration model",
    "family": "Example",
    "description": "A locally configured image model.",
    "source_url": "https://example.org/model",
    "license_url": "https://example.org/license",
    "license": "Publisher terms",
    "precision": "FP16",
    "download_gb": 7,
    "vram_gb": 16,
    "steps": 30,
    "max_steps": 80,
    "max_size": 1536,
    "max_references": 1,
    "modes": ["t2i", "edit"],
    "edit_kind": "img2img",
    "required_files": ["weights/checkpoint.safetensors", ".venv/Scripts/python.exe"],
    "image_options": {
      "guidance": {"min": 1, "max": 15, "default": 6},
      "strength": {"min": 0.1, "max": 1, "default": 0.45},
      "negative_prompt": {"default": ""}
    },
    "config": {}
  }]
}
```

This is an illustrative schema, not a downloadable model. IDs use lowercase letters, digits and hyphens, begin with a letter, and must be unique within a plugin. The plugin ID must match the directory name. The public model ID becomes `addon.example-images.illustration`. Links use HTTPS. Source, adapter and required-file paths must remain within their owning folders without symbolic links or junctions.

Use `setup_hint` to display an incomplete configuration in the library while disabling installation. Only declare supported modes. `edit_kind: img2img` labels Edit as **Redraw**: its prompt describes the finished image, and strength controls how much the input changes. `reference` means actual reference conditioning, not ordinary image-to-image denoising. Project text styles still apply to every model; automatic style-image injection requires reference-mode support.

`image_options` exposes optional guidance, strength and negative prompt controls in Advanced. Requests validate values against the manifest, preserve them in generation settings and restore them when reusing an image. Native transparency is currently reserved for built-in providers.

## Python adapter contract

The adapter exports three functions:

- `install(root, model, run, progress)` creates a model's independent environment and downloads pinned weights. `root` is `addons/<plugin-id>/.models/<model-id>`. The model's private `config` is available as `model['_config']`. `run(args, cwd, env=None)` runs an installation command with captured logs; `progress(phase, percent=None)` updates the model library. Raise an exception on failure. Downloads should resume and must verify integrity before use.
- `verify(root, model, progress)` checks dependencies and checkpoint hashes and returns a JSON-serializable dictionary containing a nonempty `files` list. Each entry should identify the file, its verified digest and size. Only successful verification writes the readiness marker and marks the model installed. The registry fingerprints the manifest and adapter; changes require verification again.
- `generate(runtime, root, model, request, references, callback)` returns `(PIL.Image.Image, metadata_dict)`. The request contains validated generation settings and `model_options`; references are local asset paths. `callback(phase, percent)` reports progress. Never return a mock result in production.

The studio owns GPU switching and calls generation under its runtime lock. Launch all GPU processes with `runtime._start(args, cwd, env, log_name)` so switching, shutdown and temporary-session cleanup can stop them. Never connect to an existing external generator. The adapter can reuse its own live processes for subsequent requests; `runtime.processes` is empty after a switch. Use loopback ports and fail if a requested fixed port is occupied. `_wait(url, seconds)` waits for an owned process to become healthy.

Use `runtime.root` for inputs, outputs, logs and caches. It points to disposable storage in temporary mode. Do not write prompts, reference images or output images into the plugin's persistent model folder. Delete extra engine outputs after returning the image; the studio handles the asset library, Pixel processing, history, export and temporary sessions. An adapter remains responsible for its external libraries' caches and logs.

The same rule applies in encrypted personal space. `runtime.store.private` covers both incognito and personal sessions; `runtime.store.personal` identifies persistent encrypted storage. Image workers stay loaded within an open session unless automatic unloading is enabled. Closing or expiring a session releases its owned worker and removes its scratch directory. Remove intermediate media after every job while retaining model caches. Never persist prompts or media outside `runtime.root`; the host cannot enforce this on arbitrary Python adapters. See [personal-space storage and security boundaries](personal-space.md).

Masked edit requests include `edit_mask_id` and `mask_feather`. The mask is a grayscale asset with white selecting the area to edit. `atelier.masking.inference_mask(runtime.store, request, size)` prepares a slightly expanded diffusion mask; ComfyUI adapters can use `atelier.providers.workflow.add_mask_nodes`. The host composites the finished image over the original with an inward feather and conservative boundary color matching, preserving every pixel outside the mask and the original dimensions. Adapters without masked diffusion still receive reference conditioning and protected-area compositing.

Delete model removes only the marked `.models/<model-id>` bundle, after checking ownership and active jobs. Plugin source and other models remain. Removing a plugin folder removes discovery; it does not delete generated assets from project history. Disabled or broken manifests must be repaired before their models can be managed again.

## Local endpoints

- `GET /api/plugins`: discovered plugins and manifest errors.
- `POST /api/plugins/refresh`: idle-only rescan; unloads an active plugin worker.
- Existing `/api/models`, install/verify/delete and `/api/jobs` endpoints handle namespaced plugin models.

Private adapter paths and model configuration are omitted from the model-library response. Model names and provider metadata remain visible to the local studio. Temporary mode cannot change the plugin registry or install/delete models.
