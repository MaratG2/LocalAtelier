"""Pinned native TRELLIS.2 runtime. No shell installers or external model folders."""
import hashlib
import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath

import httpx

VERSION = "v0.8.1"
REVISION = "c0bed38c1578f7e36e3e50c8ff1e38fa0d47583f"
ARCHIVE_SHA256 = "d2ea7b57174d3bff438064faf0b5fbcc55c29c31e6bba5f41030936fa366ed48"
URL = f"https://github.com/pwilkin/trellis.cpp/releases/download/{VERSION}/trellis-cuda-windows-x64.zip"


def binary_at(root):
    return Path(root) / ".runtime/trellis/trellis-cli.exe"


def file_hash(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def runtime_valid(root, verify=False):
    root = Path(root)
    manifest = root / ".runtime/trellis-manifest.json"
    if not binary_at(root).is_file() or not manifest.is_file():
        return False
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data["archive_sha256"] != ARCHIVE_SHA256 or not data["files"]:
            return False
        for item in data["files"]:
            path = root / ".runtime/trellis" / item["name"]
            if not path.resolve().is_relative_to((root / ".runtime/trellis").resolve()):
                return False
            if not path.is_file() or path.stat().st_size != item["size"]:
                return False
            if verify and file_hash(path) != item["sha256"]:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def install_runtime(root, update):
    root = Path(root)
    if runtime_valid(root, verify=True):
        return
    runtime = root / ".runtime/trellis"
    runtime.mkdir(parents=True, exist_ok=True)
    archive = root / ".runtime/trellis-cuda.zip"
    if not archive.is_file() or file_hash(archive) != ARCHIVE_SHA256:
        update("Downloading TRELLIS.2 CUDA runtime", 0)
        with httpx.Client(follow_redirects=True, timeout=120) as client, client.stream("GET", URL) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))
            received = 0
            with archive.open("wb") as output:
                for chunk in response.iter_bytes(1024 * 1024):
                    output.write(chunk)
                    received += len(chunk)
                    update("Downloading TRELLIS.2 CUDA runtime", round(received / total * 100) if total else None)
        if file_hash(archive) != ARCHIVE_SHA256:
            raise RuntimeError("TRELLIS.2 runtime checksum does not match the pinned release")
    update("Unpacking verified CUDA runtime", None)
    files = []
    with zipfile.ZipFile(archive) as zipped:
        members = [m for m in zipped.infolist() if not m.is_dir()]
        # Releases may place the binaries at the root or under one top-level directory.
        exe = next((m for m in members if PurePosixPath(m.filename).name == "trellis-cli.exe"), None)
        if exe is None:
            raise RuntimeError("The runtime archive has no TRELLIS CLI")
        prefix = PurePosixPath(exe.filename).parent
        for member in members:
            source = PurePosixPath(member.filename)
            if not source.is_relative_to(prefix):
                continue
            relative = source.relative_to(prefix)
            target = (runtime / Path(*relative.parts)).resolve()
            if not target.is_relative_to(runtime.resolve()):
                raise RuntimeError("Invalid runtime archive path")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            files.append({"name": relative.as_posix(), "size": target.stat().st_size, "sha256": file_hash(target)})
    (root / ".runtime/trellis-manifest.json").write_text(json.dumps({
        "version": VERSION, "revision": REVISION, "archive_sha256": ARCHIVE_SHA256, "files": files,
    }, indent=2), encoding="utf-8")
    archive.unlink()
