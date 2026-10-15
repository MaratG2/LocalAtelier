import argparse
import json
import os
import threading
from pathlib import Path

from atelier.app import create_app
from atelier.access_log import PrivateRequestHandler
from atelier.lifecycle import ManagedLifecycle
from werkzeug.serving import make_server

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Local Atelier — your local creative workspace")
    parser.add_argument("--port", type=int, default=7870)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    app = create_app(data_root=args.data_dir)
    host = '0.0.0.0' if app.config['LAN_ENABLED'] else '127.0.0.1'
    managed = json.loads(os.environ.get('ATELIER_MANAGED', 'null'))
    lifecycle = None
    server = None
    try:
        if managed:
            lifecycle = ManagedLifecycle(app, Path(__file__).resolve().parent,
                                         app.extensions['store'].durable.root / 'runtime' / 'launcher', managed)
            server = make_server(host, args.port, app, threaded=True,
                                 request_handler=PrivateRequestHandler)
            server.daemon_threads = False
            threading.Thread(target=lifecycle.watch, args=(server,), daemon=True).start()
            server.serve_forever()
        else:
            app.run(host=host, port=args.port, debug=False, threaded=True,
                    request_handler=PrivateRequestHandler)
    finally:
        if server:
            server.server_close()
        app.extensions["runtime"].release()
    raise SystemExit(lifecycle.exit_code if lifecycle else 0)
