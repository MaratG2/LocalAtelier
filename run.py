import argparse
from pathlib import Path

from atelier.app import create_app
from atelier.access_log import PrivateRequestHandler

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Local Atelier — your local creative workspace")
    parser.add_argument("--port", type=int, default=7870)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    app = create_app(data_root=args.data_dir)
    try:
        app.run(host="127.0.0.1", port=args.port, debug=False, threaded=True,
                request_handler=PrivateRequestHandler)
    finally:
        app.extensions["runtime"].release()
