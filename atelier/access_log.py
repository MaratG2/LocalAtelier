"""Access logs omit queries, which can contain private library search text."""

from werkzeug.serving import WSGIRequestHandler


class PrivateRequestHandler(WSGIRequestHandler):
    def log_request(self, code="-", size="-"):
        # Never interpolate requestline: it includes the complete query string.
        # Keep only the route for diagnostics, including malformed HTTP requests.
        route = getattr(self, "path", "").split("?", 1)[0].split("#", 1)[0]
        self.log("info", '"%s %s %s" %s %s',
                 getattr(self, "command", "-"), route,
                 getattr(self, "request_version", "-"), code, size)
