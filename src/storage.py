"""Media keys remain portable DB strings; only materialized copies are disposable.

External storage uses fsspec's provider-neutral filesystem interface. Install the
chosen provider's driver separately and supply options through the environment.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import mimetypes
from urllib.parse import quote, urlsplit
from typing import BinaryIO

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def validate_key(key: str) -> str:
    parts = PurePosixPath(key).parts
    if (not key or "\\" in key or ":" in key or "\x00" in key
            or key.startswith("/") or ".." in parts or "." in key.split("/")):
        raise ValueError("Media key must be a relative path without traversal")
    if not key.startswith(("data/uploads/videos/", "data/uploads/targets/", "data/events/")):
        raise ValueError("Media key is outside the supported media namespaces")
    return key


class StorageBackend(ABC):
    @abstractmethod
    def save(self, key: str, source: BinaryIO) -> str: ...

    @abstractmethod
    def open(self, key: str) -> BinaryIO: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def materialize(self, key: str) -> Path: ...

    def save_bytes(self, key: str, data: bytes) -> str:
        return self.save(key, io.BytesIO(data))


class LocalStorageBackend(StorageBackend):
    def __init__(self, root: Path = PROJECT_ROOT):
        self.root = Path(root).resolve()

    def path(self, key: str) -> Path:
        path = (self.root / validate_key(key)).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Media path escapes storage root")
        return path

    def save(self, key: str, source: BinaryIO) -> str:
        path = self.path(key)
        # Existing upload handlers may already have staged at the local destination.
        # Replacing a file held open by the caller is not supported on Windows.
        source_name = getattr(source, "name", None)
        if isinstance(source_name, (str, os.PathLike)) and Path(source_name).resolve() == path:
            return key
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
            temporary = Path(tmp.name)
            try:
                shutil.copyfileobj(source, tmp)
            except BaseException:
                tmp.close()
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return key

    def open(self, key: str) -> BinaryIO:
        return self.path(key).open("rb")

    def exists(self, key: str) -> bool:
        return self.path(key).is_file()

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)

    def materialize(self, key: str) -> Path:
        path = self.path(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return path


class ExternalStorageBackend(StorageBackend):
    def __init__(self, url: str, options: dict, cache_dir: Path):
        from fsspec.core import url_to_fs
        self.fs, self.prefix = url_to_fs(url, **options)
        protocols = self.fs.protocol
        protocols = (protocols,) if isinstance(protocols, str) else protocols
        if any(p in ("file", "local", "memory", "http", "https") for p in protocols):
            raise ValueError("External storage requires a durable writable remote filesystem")
        if not self.prefix.strip("/"):
            raise ValueError("External storage requires a dedicated bucket/container prefix")
        namespace = hashlib.sha256(url.encode()).hexdigest()[:20]
        self.cache = LocalStorageBackend(Path(cache_dir) / namespace)

    def _path(self, key: str) -> str:
        return self.prefix.rstrip("/") + "/" + validate_key(key)

    def save(self, key: str, source: BinaryIO) -> str:
        with self.fs.open(self._path(key), "wb") as output:
            shutil.copyfileobj(source, output)
        self.cache.delete(key)
        return key

    def open(self, key: str) -> BinaryIO:
        return self.fs.open(self._path(key), "rb")

    def exists(self, key: str) -> bool:
        return self.fs.isfile(self._path(key))

    def delete(self, key: str) -> None:
        path = self._path(key)
        if self.fs.exists(path):
            self.fs.rm(path)
        self.cache.delete(key)

    def materialize(self, key: str) -> Path:
        # Media keys are immutable UUID-based names. A cache is never authoritative.
        if not self.exists(key):
            raise FileNotFoundError(key)
        if not self.cache.exists(key):
            with self.open(key) as source:
                self.cache.save(key, source)
        return self.cache.materialize(key)


class SupabaseStorageBackend(StorageBackend):
    """Private bucket REST adapter; credentials stay server-side, DB keeps keys.

    Local files are disposable read caches. HTTP failures never expose response
    bodies, request headers or credential-bearing exception messages.
    """

    def __init__(self, url: str, token: str, bucket: str, cache_dir: Path):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.netloc or parsed.username
                or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ("", "/")):
            raise ValueError("SUPABASE_URL must be an HTTPS project origin")
        if not token or not bucket or any(c in bucket for c in "/\\"):
            raise ValueError("Supabase Storage credentials and bucket are required")
        self.base = url.rstrip("/") + "/storage/v1/object/" + quote(bucket, safe="")
        self.headers = {"apikey": token}
        if not token.startswith("sb_secret_"):
            self.headers["Authorization"] = "Bearer " + token
        namespace = hashlib.sha256(self.base.encode()).hexdigest()[:20]
        self.cache = LocalStorageBackend(Path(cache_dir) / namespace)

    def _request(self, method, key, **kwargs):
        import requests
        url = self.base + "/" + quote(validate_key(key), safe="/")
        headers = dict(self.headers)
        headers.update(kwargs.pop("headers", {}))
        try:
            response = requests.request(method, url, headers=headers,
                                        timeout=(15, 300), allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise OSError("Supabase Storage request failed") from None
        missing = response.status_code == 404
        if response.status_code == 400:
            try:
                body = response.json()
                missing = body.get("code") == "NoSuchKey" or str(body.get("statusCode")) == "404"
            except (ValueError, AttributeError):
                pass
        if missing:
            response.close()
            raise FileNotFoundError(key)
        if not 200 <= response.status_code < 300:
            status = response.status_code
            response.close()
            raise OSError(f"Supabase Storage HTTP {status}")
        return response

    def save(self, key: str, source: BinaryIO) -> str:
        # Upsert permits existing worker retries, preserving the original key.
        with self._request("POST", key, data=source, headers={
            "Content-Type": mimetypes.guess_type(key)[0] or "application/octet-stream",
            "x-upsert": "true",
        }):
            pass
        self.cache.delete(key)
        return key

    def open(self, key: str) -> BinaryIO:
        # Spool to disk above 8 MiB rather than loading a full MP4 into RAM.
        result = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
        try:
            with self._request("GET", key, stream=True) as response:
                for chunk in response.iter_content(1024 * 1024):
                    result.write(chunk)
            result.seek(0)
            return result
        except FileNotFoundError:
            result.close()
            raise
        except Exception:
            result.close()
            raise OSError("Supabase Storage download failed") from None

    def exists(self, key: str) -> bool:
        try:
            # Supabase can return HEAD 400 without its JSON NoSuchKey body.
            # A streamed range GET retains that error detail without reading MP4s.
            with self._request("GET", key, stream=True, headers={"Range": "bytes=0-0"}):
                return True
        except FileNotFoundError:
            return False

    def delete(self, key: str) -> None:
        try:
            with self._request("DELETE", key):
                pass
        except FileNotFoundError:
            pass
        self.cache.delete(key)

    def materialize(self, key: str) -> Path:
        if not self.exists(key):
            raise FileNotFoundError(key)
        if not self.cache.exists(key):
            with self.open(key) as source:
                self.cache.save(key, source)
        return self.cache.materialize(key)


def get_storage() -> StorageBackend:
    backend = os.environ.get("DATT_STORAGE_BACKEND", "local")
    if backend == "local":
        if os.environ.get("DATT_REQUIRE_PERSISTENCE") == "1":
            raise ValueError("Persistent deployment requires external media storage")
        return LocalStorageBackend(Path(os.environ.get("DATT_STORAGE_ROOT", PROJECT_ROOT)))
    if backend == "supabase":
        return SupabaseStorageBackend(
            os.environ.get("SUPABASE_URL", ""),
            os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
            os.environ.get("DATT_STORAGE_BUCKET") or os.environ.get("SUPABASE_STORAGE_BUCKET", ""),
            Path(os.environ.get("DATT_STORAGE_CACHE", str(PROJECT_ROOT / "data" / "media-cache"))),
        )
    if backend != "external":
        raise ValueError("DATT_STORAGE_BACKEND must be local, external or supabase")
    url = os.environ.get("DATT_STORAGE_URL")
    if not url:
        raise ValueError("DATT_STORAGE_URL is required for external storage")
    try:
        options = json.loads(os.environ.get("DATT_STORAGE_OPTIONS", "{}"))
        if not isinstance(options, dict):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("DATT_STORAGE_OPTIONS must be a JSON object") from None
    return ExternalStorageBackend(url, options, Path(os.environ.get(
        "DATT_STORAGE_CACHE", str(PROJECT_ROOT / "data" / "media-cache"))))


def save_image(path: str, image, params=None) -> bool:
    """Replace only the persistence operation, preserving existing JPEG settings.

    Custom snapshot directories remain supported for existing local tests.
    """
    import cv2
    dest = Path(path)
    storage = get_storage()
    try:
        key = dest.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        key = "data/events/" + dest.name
        if isinstance(storage, LocalStorageBackend):
            # Explicit caller-owned test/development directory.
            storage = LocalStorageBackend(dest.parent)
            ok, encoded = cv2.imencode(dest.suffix, image, params or [])
            if not ok:
                raise OSError("Image encoding failed")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(encoded.tobytes())
            return True
    ok, encoded = cv2.imencode(dest.suffix, image, params or [])
    if not ok:
        raise OSError("Image encoding failed")
    storage.save_bytes(key, encoded.tobytes())
    return True
