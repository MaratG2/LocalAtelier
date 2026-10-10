"""Private GPU worker. It imports only the selected provider's dependencies."""
import argparse
import base64
import hmac
import io
import json
import os
import queue
import threading
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, request
from PIL import Image, ImageOps

from .catalog import CATALOG


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=CATALOG, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if args.model == "qwen-image-2.1":
        from .providers.qwen import ComfyBackend
        backend = ComfyBackend()
        backend.check()
    else:
        from .providers.hidream.backend import HiDreamBackend
        backend = HiDreamBackend(args.weights, args.data / "temp")
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=128 * 1024 * 1024, TRUSTED_HOSTS=["localhost", "127.0.0.1", "[::1]"])
    token = os.environ["ATELIER_WORKER_TOKEN"]
    jobs = {}
    lock = threading.Lock()

    @app.before_request
    def authorize():
        if not hmac.compare_digest(request.headers.get("X-Atelier-Worker", ""), token):
            return jsonify(error="This is a private Local Atelier worker"), 403

    @app.get("/api/status")
    def status():
        return jsonify(status="ready", model_id=args.model)

    @app.post("/api/generate/start")
    def start():
        data = request.get_json()
        if not isinstance(data, dict) or not isinstance(data.get("prompt"), str):
            return jsonify(error="Invalid generation request"), 400
        if not lock.acquire(blocking=False):
            return jsonify(error="Worker is already generating"), 409
        job_id = uuid.uuid4().hex
        events = queue.Queue()
        jobs[job_id] = events
        def work():
            try:
                refs = []
                for value in data.get("refs_b64", []):
                    with Image.open(io.BytesIO(base64.b64decode(value, validate=True))) as image:
                        refs.append(ImageOps.exif_transpose(image).convert("RGBA"))
                width, height = data["width"], data["height"]
                if refs and data.get("keep_original_aspect"):
                    from .providers.hidream.settings import aspect_dimensions
                    width, height = aspect_dimensions(*refs[0].size, max(width, height))
                params = dict(prompt=data["prompt"], width=width, height=height, seed=data["seed"], references=refs,
                              callback=lambda step,total:events.put({"type":"progress","step":step,"total":total}),
                              num_inference_steps=data["num_inference_steps"], transparent_background=data.get("transparent_background", False))
                if args.model == "qwen-image-2.1":
                    image = backend.generate(**params)
                    metadata = {}
                else:
                    image, metadata = backend.generate(mode=data["mode"], **params)
                if image.size != (width, height):
                    raise RuntimeError("Model output dimensions did not match the requested canvas")
                buf = io.BytesIO()
                image.save(buf, format="PNG")
                events.put({"type":"done","image":base64.b64encode(buf.getvalue()).decode("ascii"),"width":width,"height":height,
                            "seed":data["seed"],"mock_mode":False,"model_id":args.model,**metadata})
            except Exception as error:
                events.put({"type":"error","message":str(error)})
            finally:
                lock.release()
        threading.Thread(target=work, daemon=True).start()
        return jsonify(job_id=job_id)

    @app.get("/api/generate/stream/<job_id>")
    def stream(job_id):
        events = jobs.get(job_id)
        if events is None:
            return jsonify(error="Job not found"), 404
        def send():
            try:
                while True:
                    try:
                        event = events.get(timeout=10)
                    except queue.Empty:
                        yield ": keep-alive\n\n"
                        continue
                    yield "data: " + json.dumps(event) + "\n\n"
                    if event["type"] in {"done", "error"}:
                        break
            finally:
                jobs.pop(job_id, None)
        return Response(send(), mimetype="text/event-stream")
    app.run(host="127.0.0.1", port=args.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
