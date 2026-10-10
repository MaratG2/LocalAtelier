# 3D studio

Local Atelier 0.2 adds local mesh generation with **TRELLIS.2-4B**. It uses the Q8 GGUF conversion through the native CUDA implementation [trellis.cpp](https://github.com/pwilkin/trellis.cpp), with 512³ and 1024³ geometry presets. TRELLIS.2 is the only 3D model in the catalog. It is not the original TRELLIS v1 pipeline.

## Create an object

1. Install **TRELLIS.2** in Model library. The installer downloads the pinned runtime and approximately 10 GB of weights, then checks their hashes.
2. Open **3D studio** and select a project.
3. In **Image to 3D**, upload a PNG/JPEG/WebP or choose an existing project image. Use one whole object with a clear silhouette. An image's detail panel also has **Create a 3D object**.
4. Start with **512³**, 12 sampling steps, a 2048-pixel texture atlas and a 30,000-triangle target. The 1024³ setting uses the model's shape cascade and takes longer. Both presets use a 512-resolution PBR field for predictable memory use.
5. Generate, then orbit, pan and zoom the result. PBR, clay, wireframe, base color, roughness, metallic and surface normals are available in the viewer. Save preview downloads the current view as a PNG.

**Text to 3D** first generates a reference with the studio's managed Qwen-Image-2.1 installation, at 1024² and 25 steps. The concept is saved in Images. The image worker is then stopped before TRELLIS.2 starts. This is a two-stage image-to-3D workflow, not native text conditioning in TRELLIS.2. Qwen must be installed and verified for this mode. No additional text-to-image model is downloaded.

Background removal uses BiRefNet. In Auto mode an existing alpha matte is preserved. “Remove background again” forces a fresh matte. Disabling PBR produces geometry without textures.

## Inspect, organize and export

- Each mesh stores geometry, UVs, material maps, a preview, actual triangle/vertex counts, input references, seed, options, model revision and runtime revision.
- Search, favorites, renaming, moving between projects, recoverable trash and project archives work with mesh assets. Click the result title to open details and material maps.
- **Simplify** saves a separate derivative. It preserves UV/material boundaries; an error bound or seams can prevent the requested triangle target. The actual count is always displayed. It runs on CPU and needs Node.js, but no model installation.
- **Import GLB** accepts a static embedded GLB up to 64 MB and 2 million triangles. External texture/buffer URLs and required compressed extensions are rejected. Imported meshes can be inspected, simplified and exported without a GPU model.

| Export | Contents |
|---|---|
| GLB | Single file containing geometry, UVs and PBR materials |
| glTF ZIP | Scene JSON plus binary buffers containing geometry and textures |
| OBJ ZIP | Mesh, MTL and base-color texture; original PBR maps also included separately |
| STL / PLY | Geometry; no promise of material preservation |
| Texture maps ZIP | Actual generated maps, normally base color and packed metallic/roughness |

The **Surface normals** view displays geometry normals. It is not a claimed generated normal-map texture. No heuristic normal, roughness or metallic maps are fabricated from the color image.

## Runtime and scope

Runtime release: `pwilkin/trellis.cpp` **v0.8.1**, commit `c0bed38c1578f7e36e3e50c8ff1e38fa0d47583f`. The Windows CUDA archive is SHA-256 pinned in `atelier/trellis_install.py`. Required binaries are also recorded and verified against a manifest created from that checked archive.

Weights: [`ilintar/trellis2-gguf`](https://huggingface.co/ilintar/trellis2-gguf), revision `a57397bd3d351599d9729fc144b3f87c3f87d65b`, the ten files under `q8/`. These include TRELLIS.2 flows/decoders, its shared sparse-structure decoder, DINOv3 conditioning and BiRefNet matting. All remain under `models/trellis2/` in this checkout.

The application starts one native CUDA process for a mesh job, reads stage progress from its log, and releases it afterwards. It requires an available GPU and refuses CPU inference fallback. One shared queue prevents competing image and mesh inference. Cancellation stops the owned native process; concept-image generation and CPU simplification finish their current stage before cancellation takes effect. Restarted jobs are marked interrupted, not silently rerun.

This release does not provide rigging, animation, arbitrary-mesh AI retexturing, multi-view conditioning, quad retopology, or FBX conversion. Generated geometry is a reconstruction of one view; hidden surfaces are inferred, and thin details may need manual work. There is no mock-model fallback in the application.

## Prototype lineage

The feature flow was developed from [felippeomgt/mymeshy](https://github.com/felippeomgt/mymeshy), revision `1854487f1e6c918becc859850727bc83d9ad24cd`: reference generation, background removal, mesh processing, material inspection and portable export. Local Atelier integrates that flow into its own projects, SQLite assets and single GPU queue. It replaces the prototype's original TRELLIS adapter and automatic model/mock fallback with a single explicit TRELLIS.2 runtime. It uses the model's native PBR decoder and attribute-aware meshoptimizer simplification rather than heuristic materials. Upstream MIT attribution is retained in `licenses/MyMeshy-MIT.txt`.

The application is MIT licensed. TRELLIS.2 and the runtime have their own MIT notices; DINOv3 retains Meta's separate license. The text workflow also uses Qwen's model license. See [third-party notices](../THIRD_PARTY_NOTICES.md).
