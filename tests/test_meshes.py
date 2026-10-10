import io
import json
import shutil
import struct
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import trimesh
from PIL import Image

from atelier.app import create_app
from atelier.catalog import CATALOG
from atelier.generation import save_image
from atelier.meshes import embedded_glb, load_scene, mesh_stats, save_mesh
from atelier.providers.trellis2 import MeshCancelled


def fixture_glb():
    mesh = trimesh.creation.icosphere(subdivisions=2)
    uv = np.column_stack((np.arctan2(mesh.vertices[:, 2], mesh.vertices[:, 0]) / (2 * np.pi) + .5,
                          np.arcsin(mesh.vertices[:, 1]) / np.pi + .5))
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=trimesh.visual.material.PBRMaterial(
        baseColorTexture=Image.new("RGB", (16, 16), "#872e37"), metallicRoughnessTexture=Image.new("RGB", (16, 16), (0, 150, 0))))
    return mesh.export(file_type="glb")


class MeshRuntime:
    def __init__(self, store):
        self.store = store
        self.root = store.root / "runtime"
        self.root.mkdir()
        self.active_model = None
        self.phase = "Idle"
        self.calls = []
        self.gate = threading.Event()
        self.gate.set()

    def generate(self, request, refs, callback):
        self.calls.append("image")
        callback("Concept", 50)
        return Image.new("RGB", (64, 64), "red"), {"test_fixture": True}

    def generate_mesh(self, request, reference, callback, cancelled):
        self.calls.append("mesh")
        callback("Shape", 50)
        while not self.gate.wait(.01):
            if cancelled():
                raise MeshCancelled()
        output = self.root / "trellis2/fixture"
        output.mkdir(parents=True, exist_ok=True)
        path = output / "model.glb"
        path.write_bytes(fixture_glb())
        return path, {"test_fixture": True}

    def release(self, model_id=None):
        self.active_model = None

    def logs(self):
        return {}


class MeshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = create_app(project_root=self.root, runtime_factory=MeshRuntime)
        self.app.testing = True
        self.client = self.app.test_client()
        self.store = self.app.extensions["store"]
        self.runtime = self.app.extensions["runtime"]
        self.queue = self.app.extensions["jobs"]
        self.models = self.app.extensions["models"]
        self.simplifier = patch("atelier.mesh_jobs.simplify_mesh", side_effect=lambda source, target, *args: shutil.copyfile(source, target))
        self.simplifier.start()

    def tearDown(self):
        self.runtime.gate.set()
        self.queue.queue.join()
        self.simplifier.stop()
        self.temp.cleanup()

    def register(self, model="trellis2"):
        self.store.execute("INSERT INTO models(id,source,runtime_path,verified,linked) VALUES(?,?,?,?,?)", (model, "managed", str(self.root / "models" / model), time.time(), time.time()))

    def image(self):
        return save_image(self.store, Image.new("RGB", (64, 64)), "inbox", kind="reference", name="Object")

    def request(self, **kwargs):
        return {"mode": "image-to-3d", "reference_ids": [self.image()["id"]], **kwargs}

    def import_mesh(self):
        response = self.client.post("/api/meshes/import", data={"mesh": (io.BytesIO(fixture_glb()), "object.glb")})
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        return response.json

    def test_only_trellis2_is_a_3d_model(self):
        self.assertEqual([m["id"] for m in CATALOG.values() if m["service"] == "3d"], ["trellis2"])
        self.assertEqual(self.client.post("/api/jobs", json={"model_id": "trellis2", "prompt": "test"}).status_code, 400)

    def test_import_stores_real_geometry_materials_thumbnail_and_project_count(self):
        asset = self.import_mesh()
        self.assertEqual(asset["kind"], "mesh")
        self.assertTrue(asset["metadata"]["stats"]["has_uv"])
        self.assertEqual(asset["metadata"]["stats"]["triangles"], 320)
        self.assertEqual(len(asset["metadata"]["textures"]), 2)
        self.assertEqual(self.client.get("/api/assets").json, [])
        self.assertEqual(self.client.get("/api/assets?kind=mesh").json[0]["id"], asset["id"])
        self.assertEqual(self.client.get("/api/projects").json[0]["asset_count"], 1)
        preview = self.client.get(asset["thumbnail_url"])
        with Image.open(io.BytesIO(preview.data)) as image:
            self.assertGreater(len(image.getcolors(512 * 512)), 5)
        preview.close()

    def test_export_formats_are_loadable_and_preserve_pbr_where_supported(self):
        asset = self.import_mesh()
        for format in ("glb", "gltf", "obj", "stl", "ply", "textures"):
            with self.subTest(format=format):
                response = self.client.get(f"/api/meshes/{asset['id']}/export?format={format}")
                self.assertEqual(response.status_code, 200, response.get_data(as_text=False)[:100])
                if format in ("gltf", "obj", "textures"):
                    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                        self.assertTrue(archive.namelist())
                        if format == "obj":
                            self.assertIn("model.obj", archive.namelist())
                            self.assertTrue(any(name.endswith(".mtl") for name in archive.namelist()))
                        if format == "gltf":
                            doc = json.loads(archive.read("model.gltf"))
                            self.assertTrue(doc["materials"][0]["pbrMetallicRoughness"].get("metallicRoughnessTexture"))
                elif format == "glb":
                    self.assertEqual(mesh_stats(load_scene(response.data))["triangles"], 320)
                else:
                    mesh = trimesh.load(io.BytesIO(response.data), file_type=format, force="mesh")
                    self.assertEqual(len(mesh.faces), 320)

    def test_import_rejects_external_resources_and_bad_containers(self):
        doc = json.dumps({"asset": {"version": "2.0"}, "buffers": [{"uri": "http://example.test/secret.bin", "byteLength": 4}]}).encode()
        doc += b" " * (-len(doc) % 4)
        bad = b"glTF" + struct.pack("<4I", 2, len(doc) + 20, len(doc), 0x4E4F534A) + doc
        for raw in (b"not a mesh", bad):
            response = self.client.post("/api/meshes/import", data={"mesh": (io.BytesIO(raw), "object.glb")})
            self.assertEqual(response.status_code, 400)

    def test_invalid_3d_requests_are_rejected(self):
        self.register()
        for kwargs in ({"mode": "multi-view"}, {"resolution": 768}, {"resolution": True}, {"texture_size": 1000}, {"num_inference_steps": 0},
                       {"target_triangles": -1}, {"seed": -1}, {"texture": "yes"}, {"reference_ids": []}, {"reference_ids": [None]},
                       {"reference_ids": ["missing"]}, {"prompt": []}, {"model_id": "trellis-v1"}, {"background_removal": "threshold"}, {"project_id": []}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.client.post("/api/meshes/jobs", json=self.request(**kwargs)).status_code, 400)

    def test_image_to_mesh_runs_in_shared_queue_and_saves_asset(self):
        self.register()
        response = self.client.post("/api/meshes/jobs", json=self.request())
        self.assertEqual(response.status_code, 202)
        self.queue.queue.join()
        job = self.store.job(response.json["id"])
        self.assertEqual(job["status"], "complete", job["error"])
        self.assertEqual(self.runtime.calls, ["mesh"])
        self.assertEqual(self.store.asset(job["result_ids"][0])["kind"], "mesh")

    def test_text_to_mesh_requires_qwen_and_protects_both_models(self):
        self.register()
        body = {"mode": "text-to-3d", "prompt": "A teapot"}
        self.assertEqual(self.client.post("/api/meshes/jobs", json=body).status_code, 400)
        self.register("qwen-image-2.1")
        self.runtime.gate.clear()
        response = self.client.post("/api/meshes/jobs", json=body)
        self.assertEqual(response.status_code, 202)
        self.assertTrue(self.models.in_use("qwen-image-2.1"))
        self.assertTrue(self.models.in_use("trellis2"))
        self.runtime.gate.set()
        self.queue.queue.join()
        job = self.store.job(response.json["id"])
        self.assertEqual(job["status"], "complete", job["error"])
        self.assertEqual(self.runtime.calls, ["image", "mesh"])
        self.assertEqual(len(self.client.get("/api/assets").json), 1)
        self.assertEqual(len(self.client.get("/api/assets?kind=mesh").json), 1)

    def test_mesh_is_not_an_image_reference(self):
        self.register()
        mesh = self.import_mesh()
        self.assertEqual(self.client.post("/api/meshes/jobs", json=self.request(reference_ids=[mesh["id"]])).status_code, 400)
        self.register("qwen-image-2.1")
        self.assertEqual(self.client.post("/api/jobs", json={"model_id": "qwen-image-2.1", "mode": "edit", "prompt": "test", "reference_ids": [mesh["id"]]}).status_code, 400)

    def test_simplify_does_not_require_model_and_preserves_original(self):
        mesh = self.import_mesh()
        metadata = {**mesh["metadata"], "preview_rendered": True, "preview_updated": time.time()}
        self.store.execute("UPDATE assets SET metadata=? WHERE id=?", (json.dumps(metadata), mesh["id"]))
        response = self.client.post("/api/meshes/jobs", json={"mode": "simplify", "source_mesh_id": mesh["id"], "target_triangles": 1000})
        self.assertEqual(response.status_code, 202)
        self.queue.queue.join()
        job = self.store.job(response.json["id"])
        self.assertEqual(job["status"], "complete", job["error"])
        self.assertEqual(len(self.client.get("/api/assets?kind=mesh").json), 2)
        self.assertEqual(self.runtime.calls, [])
        derivative = self.store.asset(job["result_ids"][0])
        self.assertEqual(derivative["metadata"]["parent_asset_id"], mesh["id"])
        self.assertNotIn("preview_rendered", derivative["metadata"])
        self.assertNotIn("preview_updated", derivative["metadata"])

    def test_active_mesh_job_can_cancel_and_protects_its_reference(self):
        self.register()
        self.runtime.gate.clear()
        reference = self.image()
        response = self.client.post("/api/meshes/jobs", json=self.request(reference_ids=[reference["id"]]))
        deadline = time.monotonic() + 5
        while not self.runtime.calls and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(self.client.patch(f"/api/assets/{reference['id']}", json={"deleted": True}).status_code, 400)
        self.client.post(f"/api/jobs/{response.json['id']}/cancel")
        self.queue.queue.join()
        self.assertEqual(self.store.job(response.json["id"])["status"], "cancelled")
        self.assertEqual(self.client.get("/api/assets?kind=mesh").json, [])

    def test_texture_routes_whitelist_and_mesh_trash_restore(self):
        asset = self.import_mesh()
        self.assertEqual(self.client.get(f"/api/meshes/{asset['id']}/textures/metadata.json").status_code, 404)
        texture = asset["metadata"]["textures"][0]["name"]
        response = self.client.get(f"/api/meshes/{asset['id']}/textures/{texture}")
        self.assertEqual(response.status_code, 200)
        response.close()
        self.client.patch(f"/api/assets/{asset['id']}", json={"deleted": True})
        self.assertEqual(self.client.get("/api/assets?kind=mesh").json, [])
        self.assertEqual(len(self.client.get("/api/assets?kind=mesh&trash=true").json), 1)
        self.assertEqual(self.client.get(f"/api/meshes/{asset['id']}/export").status_code, 400)
        self.client.patch(f"/api/assets/{asset['id']}", json={"deleted": False})
        self.assertEqual(len(self.client.get("/api/assets?kind=all").json), 1)

    def test_rendered_preview_is_bounded_and_does_not_change_geometry(self):
        asset = self.import_mesh()
        path = self.store.assets / asset["filename"]
        original = path.read_bytes()
        image = io.BytesIO()
        Image.new("RGB", (512, 512), "green").save(image, "PNG")
        image.seek(0)
        response = self.client.post(f"/api/meshes/{asset['id']}/preview", data={"image": (image, "preview.png")})
        self.assertEqual(response.status_code, 200)
        updated = self.store.asset(asset["id"])
        self.assertTrue(updated["metadata"]["preview_rendered"])
        self.assertIn("?v=", updated["thumbnail_url"])
        self.assertEqual(path.read_bytes(), original)
        response = self.client.post(f"/api/meshes/{asset['id']}/preview", data={"image": (io.BytesIO(b"invalid"), "preview.png")})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
