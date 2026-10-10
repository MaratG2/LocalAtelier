"""Mesh assets, embedded-only imports and portable exports.

Workflow and ground-normalization adapted from felippeomgt/mymeshy (MIT).
See licenses/MyMeshy-MIT.txt. Materials come from TRELLIS.2, never heuristics.
"""
import io
import json
import shutil
import struct
import subprocess
import zipfile
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw

from .storage import identifier, now

EXPORT_FORMATS = {"glb", "gltf", "obj", "stl", "ply", "textures"}


def embedded_glb(raw):
    if len(raw) < 20 or raw[:4] != b"glTF":
        raise ValueError("Choose a binary glTF (.glb) model")
    version, length, size, kind = struct.unpack_from("<4I", raw, 4)
    if version != 2 or length != len(raw) or kind != 0x4E4F534A or size > len(raw) - 20:
        raise ValueError("Invalid GLB container")
    try:
        document = json.loads(raw[20:20 + size])
        if not isinstance(document, dict):
            raise ValueError()
        for entry in document.get("buffers", []) + document.get("images", []):
            if not isinstance(entry, dict):
                raise ValueError("Invalid GLB resource")
            if "uri" in entry:
                raise ValueError("Use a GLB with embedded textures and buffers; external resources are not supported")
        for accessor in document.get("accessors", []):
            if not isinstance(accessor, dict):
                raise ValueError("Invalid GLB accessor")
            if not isinstance(accessor.get("count", 0), int) or not 0 <= accessor.get("count", 0) <= 6_000_000:
                raise ValueError("The mesh is too large; use at most 2 million triangles")
        if document.get("extensionsRequired", []):
            unsupported = set(document["extensionsRequired"]) - {"EXT_texture_webp"}
            if unsupported:
                raise ValueError("Export an uncompressed GLB before importing this model")
    except (json.JSONDecodeError, TypeError, KeyError, AttributeError) as error:
        raise ValueError("Invalid GLB document") from error
    return document


def load_scene(path):
    raw = Path(path).read_bytes() if not isinstance(path, bytes) else path
    embedded_glb(raw)
    try:
        scene = trimesh.load(io.BytesIO(raw), file_type="glb", force="scene", process=False)
        meshes = list(scene.geometry.values())
        if not meshes or any(not isinstance(m, trimesh.Trimesh) for m in meshes):
            raise ValueError("The GLB contains no triangle mesh")
        if sum(len(m.faces) for m in meshes) > 2_000_000:
            raise ValueError("Use at most 2 million triangles")
        if any(not np.isfinite(m.vertices).all() for m in meshes):
            raise ValueError("The mesh contains invalid coordinates")
        return scene
    except (ValueError, OSError, IndexError, KeyError) as error:
        raise ValueError(f"The mesh could not be read: {error}") from error


def mesh_stats(scene):
    meshes = list(scene.geometry.values())
    return {
        "triangles": sum(len(m.faces) for m in meshes),
        "vertices": sum(len(m.vertices) for m in meshes),
        "materials": len({id(getattr(m.visual, "material", None)) for m in meshes}),
        "has_uv": any(getattr(m.visual, "uv", None) is not None for m in meshes),
        "bounds": np.asarray(scene.extents).round(5).tolist(),
    }


def render_thumbnail(scene, target):
    """Small deterministic geometry preview without a display server or another GPU job."""
    canvas = Image.new("RGB", (512, 512), "#edf2eb")
    draw = ImageDraw.Draw(canvas)
    parts = scene.dump()
    all_points = np.concatenate([m.vertices for m in parts])
    center = (all_points.min(0) + all_points.max(0)) / 2
    scale = 1.55 / max(np.ptp(all_points, axis=0).max(), 1e-6)
    yaw, pitch = -0.55, 0.25
    rotation = np.array([[np.cos(yaw), 0, np.sin(yaw)], [0, 1, 0], [-np.sin(yaw), 0, np.cos(yaw)]])
    rotation = np.array([[1, 0, 0], [0, np.cos(pitch), -np.sin(pitch)], [0, np.sin(pitch), np.cos(pitch)]]) @ rotation
    faces_to_draw = []
    for mesh in parts:
        points = ((mesh.vertices - center) * scale) @ rotation.T
        faces = mesh.faces
        # Keep bounded for unusually dense imports; generated assets default to 30K triangles.
        faces = faces[::max(1, len(faces) // 100_000)]
        normals = np.cross(points[faces[:, 1]] - points[faces[:, 0]], points[faces[:, 2]] - points[faces[:, 0]])
        normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-9)
        shade = np.clip(normals @ np.array([-0.3, 0.65, 0.7]), 0, 1) * .55 + .45
        colors = np.tile([91, 124, 107], (len(faces), 1)).astype(float)
        material = getattr(mesh.visual, "material", None)
        texture = getattr(material, "baseColorTexture", None)
        uv = getattr(mesh.visual, "uv", None)
        if texture is not None and uv is not None:
            tex = np.asarray(texture.convert("RGB"))
            sample = np.asarray(uv)[faces].mean(axis=1)
            x = np.clip(sample[:, 0] * (tex.shape[1] - 1), 0, tex.shape[1] - 1).astype(int)
            y = np.clip((1 - sample[:, 1]) * (tex.shape[0] - 1), 0, tex.shape[0] - 1).astype(int)
            colors = tex[y, x].astype(float)
        xy = points[:, :2] * [245, -245] + [256, 260]
        for face, color, light in zip(faces, colors, shade):
            faces_to_draw.append((points[face, 2].mean(), xy[face], tuple(np.clip(color * light, 0, 255).astype(int))))
    for _, points, color in sorted(faces_to_draw, key=lambda item: item[0]):
        draw.polygon([tuple(p) for p in points], fill=color)
    canvas.save(target, "PNG")


def save_mesh(store, source, project_id, *, name, prompt="", seed=None, metadata=None, model_id="trellis2"):
    scene = load_scene(source)
    asset_id = identifier()
    folder = store.assets / asset_id
    folder.mkdir()
    target = folder / "model.glb"
    if isinstance(source, bytes):
        target.write_bytes(source)
    else:
        shutil.copyfile(source, target)
    metadata = {key: value for key, value in (metadata or {}).items() if key not in {"preview_rendered", "preview_updated"}}
    metadata.update(media_type="mesh", stats=mesh_stats(scene), textures=[])
    for index, mesh in enumerate(scene.geometry.values()):
        material = getattr(mesh.visual, "material", None)
        for channel, attr in [("base-color", "baseColorTexture"), ("metallic-roughness", "metallicRoughnessTexture"), ("normal", "normalTexture"), ("occlusion", "occlusionTexture")]:
            texture = getattr(material, attr, None)
            if texture is not None:
                filename = f"material-{index}-{channel}.png"
                texture.save(folder / filename, "PNG")
                metadata["textures"].append({"name": filename, "channel": channel, "width": texture.width, "height": texture.height})
    render_thumbnail(scene, folder / "preview.png")
    (folder / "metadata.json").write_text(json.dumps({**metadata, "prompt": prompt, "model_id": model_id}, indent=2), encoding="utf-8")
    store.execute("INSERT INTO assets(id,project_id,kind,filename,thumbnail,name,prompt,model_id,width,height,seed,metadata,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (asset_id, project_id, "mesh", f"{asset_id}/model.glb", f"{asset_id}/preview.png", name, prompt, model_id, 512, 512, seed, json.dumps(metadata), now()))
    store.execute("UPDATE projects SET updated=? WHERE id=?", (now(), project_id))
    return store.asset(asset_id)


def zip_files(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(Path(name).name, data.encode("utf-8") if isinstance(data, str) else data)
    return output.getvalue()


def export_mesh(store, asset, format):
    if format not in EXPORT_FORMATS:
        raise ValueError("Choose GLB, glTF, OBJ, STL, PLY or texture maps")
    folder = (store.assets / asset["filename"]).parent
    if format == "glb":
        return (folder / "model.glb").read_bytes(), "glb", "model/gltf-binary"
    if format == "textures":
        files = {t["name"]: (folder / t["name"]).read_bytes() for t in asset["metadata"]["textures"]}
        if not files:
            raise ValueError("This mesh has no texture maps")
        return zip_files(files), "textures.zip", "application/zip"
    scene = load_scene(folder / "model.glb")
    if format == "gltf":
        return zip_files(scene.export(file_type="gltf")), "gltf.zip", "application/zip"
    if format == "obj":
        obj, textures = trimesh.exchange.obj.export_obj(scene, return_texture=True)
        files = {"model.obj": obj, **(textures or {})}
        for texture in asset["metadata"]["textures"]:
            files[texture["name"]] = (folder / texture["name"]).read_bytes()
        files["README.txt"] = "OBJ/MTL uses base color. Original PBR maps are included separately. GLB/glTF preserves the complete material."
        return zip_files(files), "obj.zip", "application/zip"
    mesh = scene.to_mesh()
    data = mesh.export(file_type=format)
    return data, format, "application/octet-stream"


def simplify_mesh(source, target, triangles, project_root):
    """Attribute-aware simplification preserves UVs and embedded PBR textures."""
    node = shutil.which("node.exe" if __import__("os").name == "nt" else "node")
    if not node:
        raise RuntimeError("Node.js is required for mesh simplification; run setup.ps1")
    from .models import CREATE_FLAGS
    result = subprocess.run([node, str(Path(project_root) / "frontend/scripts/simplify.mjs"), str(source), str(target), str(triangles)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, creationflags=CREATE_FLAGS)
    if result.returncode or not Path(target).is_file():
        raise RuntimeError("Mesh simplification failed: " + result.stderr[-1500:])
