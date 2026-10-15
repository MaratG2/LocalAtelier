# Video studio

Local Atelier runs **VDN-H3, based on MiniMax H3**, through a pinned FreeVideo runtime on Windows. It generates video and stereo audio together. No paid endpoint, hosted prompt service, ComfyUI server, or external personal generator is used. LTX is not included in this release.

## Create a clip

Install **VDN-H3 · MiniMax H3** in Model library. The package contains 56.7 GB of model data, plus Python, CUDA packages and compilation caches. The prepared INT8 ConvRot transformer avoids downloading or converting the original full-precision transformer. Installation is resumable; verification checks all 1,201 pinned files against SHA-256 or Git blob hashes. Model removal preserves projects and clips.

Open Video, choose a project and describe the scene, motion, camera and sound. The default is Light quality, a requested five seconds, a 896 × 512 final canvas, and Preview first. H3 aligns time to its temporal grid: five requested seconds becomes 124 frames, about 5.17 seconds at 24 fps. The interface displays this alignment before generation.

Modes:

- **Text:** a scene and sound description.
- **Frames:** a first image, a last image, or both. Upload a PNG/JPEG/WebP or select a project image. Image studio also has an **Animate image** action.
- **References:** images, video and audio describing subjects, appearance, movement or sound. Up to nine images, three videos and three audio clips, with at most twelve inputs. Project clips can also be selected as references. Media clips must be 2–15 seconds and at most 64 MB each. Combined video and audio durations are each capped at fifteen seconds; audio carried by a video counts toward the audio allowance. These are validation limits, not a promise that every combination fits 16 GB VRAM.

Describe the role of each reference in the prompt. Keyframes and reference collections are separate modes. Uploaded reference clips stay out of the generated-clip gallery.

## Quality and preview finishing

| Preset | Sampling | Preview first |
|---|---|---|
| Light | 8 steps on a smaller canvas, then 3 refinement steps | Available |
| Medium | 12 steps at the final resolution | Unavailable |
| High | 16 steps at the final resolution | Unavailable |
| Max | 20 steps at the final resolution | Unavailable |

These follow FreeVideo's quality presets. Higher step counts take longer; they are not an unconditional quality ranking for every prompt.

A preview stops after the first pass and keeps its conditioning and latent tensors next to the MP4. **Finish preview** queues a new asset with the same prompt, seed, geometry and references. The runtime reuses the saved pass, upscales its latents and refines the result; the original preview remains available. A changed runtime or incompatible receipt may require resampling, which is reported in progress. Imported MP4s cannot be finished this way. Retained previews occupy more disk space than their MP4 files.

Supported final canvases are 896 × 512, 512 × 896, 512 × 512, 1344 × 768, 768 × 1344 and 768 × 768. Requested durations run from two to ten seconds. Start with the smaller canvas and Light preview on a 16 GB card. Longer clips, larger canvases and multimodal inputs increase resource needs. The first run also compiles kernels; subsequent timings can differ substantially.

## Library and exports

Clips share the existing project system. Search, favorite, rename, move between projects, trash and restore them. The player supports play/pause, seeking, a real five-frame filmstrip, volume, mute and full screen. Portrait clips keep their original aspect ratio.

Downloads include the MP4 with its native audio, stereo WAV at 32 kHz, PNG cover and JSON generation settings. Playback uses the browser's media decoder. The MP4 remains downloadable if a browser cannot play it.

Image, mesh and video jobs use one queue, with at most four waiting/running jobs in total. Switching providers releases the owned GPU processes. Cancelling a video terminates its process tree and does not register a partial clip. Restarted jobs are marked interrupted. Model installation, verification and deletion are blocked while that model has active jobs; inputs cannot be trashed while an active job references them.

## Runtime and storage

Everything is owned by this checkout:

```text
models/vdn-h3/.runtime/FreeVideo/   pinned Apache-2.0 coordinator
models/vdn-h3/.runtime/vdn/         pinned model code and patched Diffusers
models/vdn-h3/.runtime/ComfyUI/     pinned native encoder library; no UI server
models/vdn-h3/.runtime/python/      owned Python 3.12 interpreter
models/vdn-h3/.venv/               isolated CUDA environment
models/vdn-h3/weights/             transformer, encoder, VAEs and sampling tables
models/vdn-h3/.cache/              local compilation and package caches
data/assets/<asset-id>/            MP4, cover, filmstrip, settings and receipts
data/runtime/vdn-h3.log            latest coordinator log
```

FreeVideo is pinned to `0af617eb54dec1d8c06f9e7de2147c5b6a3f4772`; OpenVDN to `30b6b380c2482f3519469350810c2955d8847fd9`; the patched Diffusers tree is `37068ab7331d8b28f4cf718dba7015c742a306d2`; the encoder library is `421a1c245c682c04d4325ba365f40c834c66f5b0`. The complete weight manifest is `atelier/manifests/vdn-h3.json`. Model and environment directories are excluded from Git.

H3 keeps a session-owned FreeVideo resident worker between successful generations, including in personal space and incognito. The per-request coordinator still runs memory guards and saves diagnostics, while compatible encoder, transformer and decoder models can be reused. Switching models or workspaces, locking/leaving a private session, cancellation, errors, or enabling **Unload after generation** releases the worker. Personal-space outputs are sealed after each job; keeping weights loaded does not keep unencrypted output files.

The worker uses adaptive memory placement and weight streaming. On a 16 GB GPU it may still evict individual components to make room for encoding, sampling or decoding; changes to geometry or execution settings can also invalidate a cached model. Worker reuse removes the forced whole-process reload after every clip, but does not promise every component always fits in VRAM. Progress distinguishes an actual cached video-model reuse from session reuse. It does not change the Windows pagefile, kill other applications or silently lower the requested geometry. Native worker progress is displayed by stage; this is not an elapsed-time forecast. Runtime errors remain visible in job history and Settings logs.

## License

FreeVideo/OpenVDN software and MiniMax H3 weights have separate terms. The application remains MIT; FreeVideo/OpenVDN code is Apache-2.0, and the downloaded encoder library retains GPL-3.0. The weights use the **MiniMax H3 Community License**, not MIT or Apache-2.0. Its territorial definition excludes the EU, UK, Republic of Korea and USA; it also contains commercial and attribution conditions. Read the [pinned model license](https://huggingface.co/OpenVDN/vdn-minimax-h3/blob/751739ee5b9e3ac802dca5d5111075fdaeb47885/LICENSE) for the actual terms. Local Atelier does not grant additional model rights. See `THIRD_PARTY_NOTICES.md` and `licenses/MiniMax-H3.txt`.

Primary sources: [FreeVideo](https://github.com/FlashML-org/FreeVideo), [MiniMax H3](https://github.com/MiniMax-AI/MiniMax-H3), [prepared VDN-H3 weights](https://huggingface.co/OpenVDN/vdn-minimax-h3-edge). Hardware measurements and browser checks belong in `docs/verification.md`; upstream claims are not local measurements.
