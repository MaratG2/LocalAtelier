import io
import json
import os
import shutil
import subprocess
import time
import threading
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory, send_file
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.exceptions import HTTPException

from .catalog import SERVICES
from .generation import GenerationQueue, save_image
from .models import CREATE_FLAGS, ModelManager
from .runtime import Runtime
from .storage import Store, identifier, now
from .privacy import SessionRouter
from .styles import project_style


def object_body():
    data = request.get_json()
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    return data


def text_field(value, name, limit, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError(f"{name} must contain {'0' if empty else '1'}–{limit} characters")
    return value.strip()


def create_app(data_root=None, project_root=None, runtime_factory=Runtime):
    root = Path(project_root or Path(__file__).resolve().parents[1])
    store = SessionRouter(Store(data_root or root / "data"))
    runtime = runtime_factory(store)
    models = ModelManager(store, root, runtime)
    jobs = GenerationQueue(store, runtime, models)
    app = Flask(__name__, static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=66 * 1024 * 1024, TRUSTED_HOSTS=["localhost", "127.0.0.1", "[::1]"])
    app.extensions.update(store=store, runtime=runtime, models=models, jobs=jobs)
    hardware = {"at": 0, "value": {}}
    threading.Thread(target=store.expire, args=(jobs,), daemon=True).start()

    @app.before_request
    def origin_guard():
        if app.config.get('STUDIO_STOPPING') and request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            return jsonify(error='Local Atelier is updating. Try again in a moment.'), 503
        key = request.cookies.get('atelier_temporary')
        session = store.sessions.get(key)
        g.session_context = store.context.set(key if session and not session.closed else None)
        if session and not session.closed:
            session.touched = time.monotonic()
        g.expired_session = bool(key and (not session or session.closed))
        if g.expired_session and request.method not in {'GET', 'HEAD'} and request.path.startswith('/api/') and not request.path.startswith('/api/temporary'):
            return jsonify(error='Temporary session ended. Reload the studio.'), 410
        if request.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("Origin")
            if origin and origin not in {request.host_url.rstrip("/"), "http://127.0.0.1:5175", "http://localhost:5175"}:
                return jsonify(error="Cross-origin requests are not allowed"), 403
            if store.temporary and (request.path.startswith('/api/projects') or request.path.startswith('/api/models') or request.path == '/api/settings'):
                raise ValueError('End temporary mode before changing projects, models or settings')

    @app.teardown_request
    def reset_session(error):
        if hasattr(g, 'session_context'):
            store.context.reset(g.session_context)

    @app.after_request
    def private_response(response):
        if getattr(g, 'expired_session', False):
            response.delete_cookie('atelier_temporary')
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Vary'] = 'Cookie'
        return response

    @app.route('/api/temporary', methods=['GET', 'POST', 'DELETE'])
    def temporary_session():
        if request.method == 'POST':
            key = request.cookies.get('atelier_temporary')
            if key in store.sessions and not store.sessions[key].closed:
                return jsonify(temporary=True)
            key = store.begin()
            response = jsonify(temporary=True)
            response.set_cookie('atelier_temporary', key, httponly=True, samesite='Strict')
            return response
        if request.method == 'DELETE':
            store.close(request.cookies.get('atelier_temporary'), jobs)
            response = jsonify(temporary=False, cleanup_error=store.cleanup_error)
            response.delete_cookie('atelier_temporary')
            return response
        return jsonify(temporary=store.temporary, cleanup_error=store.cleanup_error)

    @app.post('/api/temporary/close')
    def temporary_close():
        store.close(request.cookies.get('atelier_temporary'), jobs)
        response = jsonify(ok=True)
        response.delete_cookie('atelier_temporary')
        return response

    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.get("/api/status")
    def status():
        if time.monotonic() - hardware["at"] > 5:
            value = {"gpu_name": None, "gpu_total_mib": 0, "gpu_used_mib": 0, "disk_free_bytes": shutil.disk_usage(root).free}
            try:
                output = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3, creationflags=CREATE_FLAGS)
                name, total, used = output.stdout.splitlines()[0].rsplit(",", 2)
                value.update(gpu_name=name.strip(), gpu_total_mib=int(total), gpu_used_mib=int(used))
            except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
                pass
            hardware.update(at=time.monotonic(), value=value)
        return jsonify(name="Local Atelier", version="0.4.0", temporary=store.temporary, cleanup_error=store.cleanup_error, hardware=hardware["value"], active_model=runtime.active_model,
                       runtime_phase=runtime.phase, services=SERVICES, data_path=str(store.root), features=['image-pixelation'],
                       launcher=app.config.get('LAUNCHER', {'managed': False}))

    @app.route("/api/projects", methods=["GET", "POST"])
    def projects_route():
        if request.method == "GET":
            return jsonify(store.projects(request.args.get("archived") == "true"))
        data = object_body()
        name = text_field(data.get("name"), "Project name", 80)
        description = text_field(data.get("description", ""), "Description", 1000, empty=True)
        values = project_style(data, store)
        project_id = identifier()
        store.execute("INSERT INTO projects(id,name,description,created,updated) VALUES(?,?,?,?,?)", (project_id, name, description, now(), now()))
        if values:
            store.execute(f"UPDATE projects SET {','.join(key+'=?' for key in values)} WHERE id=?", (*values.values(), project_id))
        return jsonify(store.project(project_id)), 201

    @app.patch("/api/projects/<project_id>")
    def project_update(project_id):
        project = store.project(project_id)
        if not project:
            return jsonify(error="Project not found"), 404
        data = object_body()
        values = project_style(data, store)
        for key in data:
            if key in {'style_prompt', 'style_reference_id', 'inherit_style'}:
                continue
            if key == "name":
                values[key] = text_field(data[key], "Project name", 80)
            elif key == "description":
                values[key] = text_field(data[key], "Description", 1000, empty=True)
            elif key in {"favorite", "archived"} and isinstance(data[key], bool):
                values[key] = int(data[key])
            else:
                raise ValueError("Unsupported project setting")
        if values.get("archived"):
            if project_id == "inbox":
                raise ValueError("My creations is the default project and cannot be archived")
            if store.one("SELECT id FROM jobs WHERE project_id=? AND status IN ('queued','running')", (project_id,)):
                raise ValueError("Wait for the project's active generations before archiving")
        values["updated"] = now()
        store.execute(f"UPDATE projects SET {','.join(key+'=?' for key in values)} WHERE id=?", (*values.values(), project_id))
        return jsonify(store.project(project_id))

    @app.get("/api/assets")
    def assets_route():
        kind = request.args.get("kind", "image")
        if kind not in {"image", "mesh", "video", "all"}:
            raise ValueError("Unknown asset type")
        kinds = {"image": "a.kind='generated'", "mesh": "a.kind='mesh'", "video": "a.kind='video'", "all": "a.kind IN ('generated','mesh','video')"}
        filters, params = [kinds[kind], "a.deleted=?", "p.archived=0"], [int(request.args.get("trash") == "true")]
        if request.args.get("project"):
            filters.append("a.project_id=?")
            params.append(request.args["project"])
        if request.args.get("favorite") == "true":
            filters.append("a.favorite=1")
        if request.args.get("q"):
            filters.append("(a.prompt LIKE ? OR a.name LIKE ?)")
            params += ["%" + request.args["q"][:200] + "%"] * 2
        ids = store.all("SELECT a.id FROM assets a JOIN projects p ON p.id=a.project_id WHERE " + " AND ".join(filters) + " ORDER BY a.created DESC LIMIT 500", params)
        return jsonify([store.asset(row["id"]) for row in ids])

    @app.post("/api/uploads")
    def upload():
        project_id = request.form.get("project_id", "inbox")
        project = store.project(project_id)
        if not project or project["archived"]:
            raise ValueError("Select an active project")
        source = request.files.get("image")
        if not source:
            raise ValueError("Choose an image to upload")
        raw = source.read(24 * 1024 * 1024 + 1)
        if len(raw) > 24 * 1024 * 1024:
            raise ValueError("Images must be at most 24 MB")
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in {"PNG", "JPEG", "WEBP"} or image.width * image.height > 24_000_000:
                    raise ValueError("Use PNG, JPEG or WebP up to 24 megapixels")
                converted = ImageOps.exif_transpose(image).convert("RGBA")
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
            raise ValueError("The image could not be read") from error
        return jsonify(save_image(store, converted, project_id, kind="reference", name=(source.filename or "Reference")[:120])), 201

    @app.get("/api/assets/<asset_id>")
    def asset_details(asset_id):
        asset = store.asset(asset_id)
        if not asset or asset["deleted"]:
            return jsonify(error="Image not found"), 404
        return jsonify(asset)

    @app.get("/api/assets/<asset_id>/<variant>")
    def asset_file(asset_id, variant):
        asset = store.asset(asset_id)
        if not asset or variant not in {"file", "thumbnail", "metadata"}:
            return jsonify(error="Image not found"), 404
        if variant == "metadata":
            return jsonify({**asset["metadata"], "prompt": asset["prompt"], "model_id": asset["model_id"]})
        filename = asset["thumbnail"] if variant == "thumbnail" else asset["filename"]
        extension = Path(filename).suffix.lstrip('.')
        return send_file(store.assets / filename, as_attachment=request.args.get("download") == "true", download_name=f"atelier-{asset['seed'] or asset_id[:8]}.{extension}", max_age=0)

    @app.route('/api/assets/<asset_id>/game-export', methods=['GET', 'POST'])
    def game_export(asset_id):
        from .gamedev import export_bundle
        asset = store.asset(asset_id)
        if not asset or asset['deleted']:
            return jsonify(error='Image not found'), 404
        layout = object_body().get('layout') if request.method == 'POST' else None
        bundle, atlas = export_bundle(store, asset, layout)
        if request.args.get('preview') == 'true':
            data = io.BytesIO(); atlas.save(data, 'PNG'); data.seek(0)
            return send_file(data, mimetype='image/png')
        return send_file(io.BytesIO(bundle), mimetype='application/zip', as_attachment=True, download_name='atelier-game-assets.zip')

    @app.post('/api/videos/jobs')
    def video_jobs():
        return jsonify(jobs.submit(object_body(), video=True)), 202

    @app.post('/api/videos/uploads')
    def video_upload():
        from .videos import upload_media
        project_id = request.form.get('project_id', 'inbox')
        project = store.project(project_id)
        if not project or project['archived']:
            raise ValueError('Select an active project')
        source = request.files.get('media')
        if not source:
            raise ValueError('Choose a media file')
        return jsonify(upload_media(store, source, project_id)), 201

    @app.get('/api/videos/<asset_id>/filmstrip')
    def video_filmstrip(asset_id):
        asset = store.asset(asset_id)
        if not asset or asset['kind'] != 'video':
            return jsonify(error='Video not found'), 404
        return send_from_directory(store.assets / asset_id, 'filmstrip.jpg', max_age=86400)

    @app.get('/api/videos/<asset_id>/audio')
    def video_audio(asset_id):
        import av
        import wave
        asset = store.asset(asset_id)
        if not asset or asset['kind'] != 'video' or not asset['metadata'].get('has_audio'):
            return jsonify(error='Audio not found'), 404
        buffer = io.BytesIO()
        with av.open(str(store.assets / asset['filename'])) as container, wave.open(buffer, 'wb') as output:
            output.setnchannels(2); output.setsampwidth(2); output.setframerate(32000)
            resampler = av.AudioResampler(format='s16', layout='stereo', rate=32000)
            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    output.writeframes(converted.to_ndarray().tobytes())
            for converted in resampler.resample(None):
                output.writeframes(converted.to_ndarray().tobytes())
        buffer.seek(0)
        return send_file(buffer, mimetype='audio/wav', as_attachment=True, download_name=f'atelier-{asset_id[:8]}.wav')

    @app.post("/api/meshes/jobs")
    def mesh_jobs():
        return jsonify(jobs.submit(object_body(), mesh=True)), 202

    @app.post("/api/meshes/import")
    def mesh_import():
        from .meshes import save_mesh
        project_id = request.form.get("project_id", "inbox")
        project = store.project(project_id)
        if not project or project["archived"]:
            raise ValueError("Select an active project")
        source = request.files.get("mesh")
        if not source:
            raise ValueError("Choose a GLB file")
        raw = source.read(64 * 1024 * 1024 + 1)
        if len(raw) > 64 * 1024 * 1024:
            raise ValueError("Use a GLB smaller than 64 MB")
        asset = save_mesh(store, raw, project_id, name=Path(source.filename or "Imported mesh").stem[:120], model_id=None, metadata={"imported": True})
        return jsonify(asset), 201

    def mesh_asset(asset_id):
        asset = store.asset(asset_id)
        if not asset or asset["kind"] != "mesh" or asset["deleted"]:
            raise ValueError("Mesh not found")
        return asset

    @app.get("/api/meshes/<asset_id>/export")
    def mesh_export(asset_id):
        from .meshes import export_mesh
        asset = mesh_asset(asset_id)
        data, extension, mime = export_mesh(store, asset, request.args.get("format", "glb"))
        return send_file(io.BytesIO(data), mimetype=mime, as_attachment=True, download_name=f"atelier-{asset_id[:8]}.{extension}")

    @app.get("/api/meshes/<asset_id>/textures/<name>")
    def mesh_texture(asset_id, name):
        asset = mesh_asset(asset_id)
        if name not in {item["name"] for item in asset["metadata"].get("textures", [])}:
            return jsonify(error="Texture not found"), 404
        return send_from_directory(store.assets / asset_id, name, max_age=86400)

    @app.post("/api/meshes/<asset_id>/preview")
    def mesh_preview(asset_id):
        asset = mesh_asset(asset_id)
        source = request.files.get("image")
        if not source:
            raise ValueError("A preview image is required")
        raw = source.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError("Preview is too large")
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != "PNG" or image.width > 1024 or image.height > 1024:
                    raise ValueError("Use a PNG preview up to 1024 pixels")
                preview = image.convert("RGB")
                preview.thumbnail((512, 512))
                preview.save(store.assets / asset["thumbnail"], "PNG")
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
            raise ValueError("Invalid preview image") from error
        metadata = {**asset["metadata"], "preview_rendered": True, "preview_updated": now()}
        store.execute("UPDATE assets SET metadata=? WHERE id=?", (json.dumps(metadata), asset_id))
        return jsonify(ok=True)

    @app.patch("/api/assets/<asset_id>")
    def asset_update(asset_id):
        if not store.asset(asset_id):
            return jsonify(error="Image not found"), 404
        data = object_body()
        if store.temporary and not store.current.one('SELECT id FROM assets WHERE id=?', (asset_id,)):
            raise ValueError('Saved assets cannot be changed in temporary mode')
        values = {}
        for key, value in data.items():
            if key in {"favorite", "deleted"} and isinstance(value, bool):
                values[key] = int(value)
            elif key == "name":
                values[key] = text_field(value, "Name", 120)
            elif key == "project_id" and isinstance(value, str) and store.project(value) and not store.project(value)["archived"]:
                values[key] = value
            else:
                raise ValueError("Unsupported image setting")
        if values:
            if values.get("deleted") and store.one("SELECT id FROM jobs WHERE status IN ('queued','running') AND request LIKE ?", (f'%"{asset_id}"%',)):
                raise ValueError("This asset is referenced by a queued or running job")
            store.execute(f"UPDATE assets SET {','.join(key+'=?' for key in values)} WHERE id=?", (*values.values(), asset_id))
        return jsonify(store.asset(asset_id))

    @app.route("/api/jobs", methods=["GET", "POST"])
    def jobs_route():
        if request.method == "POST":
            return jsonify(jobs.submit(object_body())), 202
        ids = store.all("SELECT id FROM jobs ORDER BY created DESC LIMIT 30")
        return jsonify([store.job(row["id"]) for row in ids])

    @app.post("/api/jobs/<job_id>/cancel")
    def cancel(job_id):
        jobs.cancel(job_id)
        return jsonify(store.job(job_id))

    @app.get("/api/models")
    def models_route():
        return jsonify(models.list())

    @app.post("/api/models/<model_id>/<action>")
    def model_operation(model_id, action):
        return jsonify(models.start(model_id, action)), 202

    @app.delete("/api/models/<model_id>")
    def model_remove(model_id):
        from .catalog import CATALOG
        if model_id not in CATALOG or object_body().get("confirmation") != CATALOG[model_id]["name"]:
            raise ValueError("Confirm the model name before removing it")
        models.remove(model_id)
        return jsonify(ok=True)

    @app.route("/api/settings", methods=["GET", "PATCH"])
    def settings():
        if request.method == "PATCH":
            data = object_body()
            if set(data) - {"low_vram", "unload_after_job", "style_prompt"} or any(not isinstance(v, bool) for k, v in data.items() if k != 'style_prompt'):
                raise ValueError("Unsupported runtime setting")
            if 'style_prompt' in data:
                data['style_prompt'] = text_field(data['style_prompt'], 'Style prompt', 4000, empty=True)
            runtime_change = bool(set(data) - {'style_prompt'})
            if runtime_change and store.one("SELECT id FROM jobs WHERE status IN ('queued','running') LIMIT 1"):
                raise ValueError("Wait for queued generations before changing runtime settings")
            if runtime_change:
                runtime.release()
            for key, value in data.items():
                store.set_setting(key, value)
        return jsonify(low_vram=store.setting("low_vram", False), unload_after_job=store.setting("unload_after_job", False), style_prompt=store.setting('style_prompt', ''))

    @app.post("/api/runtime/release")
    def release():
        if store.one("SELECT id FROM jobs WHERE status IN ('queued','running') LIMIT 1"):
            raise ValueError("Wait for queued generations before releasing the GPU")
        runtime.release()
        return jsonify(ok=True)

    @app.get("/api/runtime/logs")
    def logs():
        return jsonify(runtime.logs())

    @app.get("/")
    @app.get("/<path:path>")
    def frontend(path=""):
        if path.startswith("api/"):
            return jsonify(error="Endpoint not found"), 404
        dist = root / "frontend/dist"
        if not (dist / "index.html").exists():
            return "Build the frontend with npm run build in frontend/", 503
        return send_from_directory(dist, path if path and (dist / path).is_file() else "index.html")

    return app
