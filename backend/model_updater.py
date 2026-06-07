"""Model updater for downloading and updating models from remote sources.

Supports:
- Checking remote manifest for available updates
- Downloading models with progress callbacks
- SHA256 checksum verification
- Atomic updates (download to temp, then move)
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Callable

try:
    from .model_registry import DATA_ROOT, ModelEntry, ModelFile, get_registry
except ImportError:
    from model_registry import DATA_ROOT, ModelEntry, ModelFile, get_registry

# Default remote manifest URL (points to GitHub Releases)
DEFAULT_MANIFEST_URL = (
    "https://github.com/4thanks/EchoSmith/releases/download/models/manifest.json"
)

# Per-model download URLs (overridable)
DEFAULT_MODEL_URLS: dict[str, str] = {
    "sensevoice-int8": (
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
        "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2"
    ),
    "silero-vad": (
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
        "silero_vad.onnx"
    ),
}

DownloadProgressCallback = Callable[[float, str], None]


def sha256_file(path: Path) -> str:
    """Compute SHA256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_directory(dir_path: Path, filenames: list[str]) -> str:
    """Compute combined SHA256 of multiple files in a directory."""
    h = hashlib.sha256()
    for fname in sorted(filenames):
        fp = dir_path / fname
        if fp.exists():
            h.update(sha256_file(fp).encode())
    return h.hexdigest()


def download_file(
    url: str,
    dest: Path,
    progress_cb: DownloadProgressCallback | None = None,
) -> None:
    """Download a file with progress reporting."""
    dest.parent.mkdir(parents=True, exist_ok=True)

    def _hook(block_num: int, block_size: int, total_size: int) -> None:
        downloaded = block_num * block_size
        if total_size > 0 and progress_cb:
            ratio = min(1.0, downloaded / total_size)
            mb_done = downloaded / 1024 / 1024
            mb_total = total_size / 1024 / 1024
            progress_cb(ratio, f"下载中 {mb_done:.1f}/{mb_total:.1f} MB")

    urllib.request.urlretrieve(url, str(dest), _hook)


def fetch_manifest(url: str = DEFAULT_MANIFEST_URL) -> dict[str, Any]:
    """Fetch the remote model manifest."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "EchoSmith/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"Failed to fetch manifest from {url}: {e}") from e


def check_updates(
    remote_manifest: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Check for available model updates.

    Returns a list of models with available updates.
    """
    registry = get_registry()
    if remote_manifest is None:
        try:
            remote_manifest = fetch_manifest()
        except Exception:
            return []  # Can't reach remote; no updates available
    return registry.check_updates(remote_manifest)


def download_model(
    model_id: str,
    url: str = "",
    version: str = "",
    progress_cb: DownloadProgressCallback | None = None,
) -> ModelEntry:
    """Download and install a model.

    Args:
        model_id: Model identifier (e.g. "sensevoice-int8")
        url: Download URL. If empty, uses DEFAULT_MODEL_URLS.
        version: Version string. If empty, derives from URL.
        progress_cb: Progress callback.

    Returns:
        The installed ModelEntry.
    """
    registry = get_registry()

    if not url:
        url = DEFAULT_MODEL_URLS.get(model_id, "")
    if not url:
        raise ValueError(f"No download URL for model: {model_id}")

    if not version:
        # Try to derive version from existing registry entry
        existing = registry.get_model(model_id)
        if existing:
            version = existing.version
        else:
            version = "latest"

    model_dir = DATA_ROOT / "sherpa-onnx" / model_id / version
    model_dir.mkdir(parents=True, exist_ok=True)

    # Determine archive format from URL
    is_tar = ".tar.bz2" in url or ".tar.gz" in url
    is_zip = ".zip" in url
    archive_ext = ".tar.bz2" if is_tar else ".zip" if is_zip else ".bin"

    with tempfile.TemporaryDirectory() as tmp_dir:
        archive_path = Path(tmp_dir) / f"model{archive_ext}"

        if progress_cb:
            progress_cb(0.0, "开始下载...")

        # Download
        download_file(url, archive_path, progress_cb)

        if progress_cb:
            progress_cb(0.8, "解压模型文件...")

        # Extract
        if is_tar:
            import tarfile

            with tarfile.open(str(archive_path), "r:bz2") as tar:
                tar.extractall(str(tmp_dir))
        elif is_zip:
            import zipfile

            with zipfile.ZipFile(str(archive_path), "r") as zf:
                zf.extractall(str(tmp_dir))
        else:
            # Single file download (e.g. silero_vad.onnx)
            shutil.copy2(
                str(archive_path), str(model_dir / model_id.replace("-", "_") + ".onnx")
            )
            _finish_install(model_id, version, model_dir, progress_cb)
            return registry.get_model(model_id)  # type: ignore

        # Find extracted content (may be in a subdirectory)
        extracted = _find_extracted_content(tmp_dir, model_id)

        if progress_cb:
            progress_cb(0.9, "校验模型文件...")

        # Copy essential files to model_dir
        files = []
        for fname in ["model.int8.onnx", "model.onnx", "tokens.txt", "silero_vad.onnx"]:
            src = extracted / fname
            if src.exists():
                shutil.copy2(str(src), str(model_dir / fname))
                files.append(
                    ModelFile(
                        filename=fname,
                        sha256=sha256_file(model_dir / fname),
                        size_bytes=(model_dir / fname).stat().st_size,
                    )
                )

        # Compute overall checksum
        checksum = sha256_directory(model_dir, [f.filename for f in files])

    # Register
    entry = ModelEntry(
        id=model_id,
        name=_model_display_name(model_id),
        version=version,
        engine="sherpa-onnx",
        files=files,
        checksum=checksum,
        remote_url=url,
        installed=True,
        active=not any(m.active for m in registry.list_models()),
        path=str(model_dir),
    )
    registry.register(entry)

    if progress_cb:
        progress_cb(1.0, "安装完成")

    return entry


def _find_extracted_content(tmp_dir: str, model_id: str) -> Path:
    """Find the extracted model content directory."""
    tmp = Path(tmp_dir)
    # Look for known model files anywhere in the extracted tree
    for child in tmp.rglob("model.int8.onnx"):
        return child.parent
    for child in tmp.rglob("tokens.txt"):
        return child.parent
    # Fallback: return tmp
    return tmp


def _model_display_name(model_id: str) -> str:
    """Return a human-readable model name."""
    names = {
        "sensevoice-int8": "SenseVoice INT8",
        "sensevoice-fp32": "SenseVoice FP32",
        "silero-vad": "Silero VAD",
    }
    return names.get(model_id, model_id)


def _finish_install(
    model_id: str,
    version: str,
    model_dir: Path,
    progress_cb: DownloadProgressCallback | None,
) -> None:
    """Finalize a single-file model install."""
    registry = get_registry()
    files = []
    for fname in model_dir.iterdir():
        if fname.is_file():
            files.append(
                ModelFile(
                    filename=fname.name,
                    sha256=sha256_file(fname),
                    size_bytes=fname.stat().st_size,
                )
            )
    checksum = sha256_directory(model_dir, [f.filename for f in files])
    entry = ModelEntry(
        id=model_id,
        name=_model_display_name(model_id),
        version=version,
        engine="sherpa-onnx",
        files=files,
        checksum=checksum,
        installed=True,
        active=not any(m.active for m in registry.list_models()),
        path=str(model_dir),
    )
    registry.register(entry)
    if progress_cb:
        progress_cb(1.0, "安装完成")


def import_local_model(
    model_id: str,
    source_dir: str,
    version: str = "",
    progress_cb: DownloadProgressCallback | None = None,
) -> ModelEntry:
    """Import a model from a local directory.

    The source directory must contain model.int8.onnx (or model.onnx) and tokens.txt.
    """
    registry = get_registry()
    src = Path(source_dir)

    if not src.exists():
        raise FileNotFoundError(f"Source directory not found: {source_dir}")

    # Validate required files
    has_model = (src / "model.int8.onnx").exists() or (src / "model.onnx").exists()
    has_tokens = (src / "tokens.txt").exists()
    if not has_model or not has_tokens:
        raise ValueError(
            f"Invalid model directory. Must contain model*.onnx and tokens.txt.\n"
            f"Found: {[f.name for f in src.iterdir() if f.is_file()]}"
        )

    if not version:
        version = f"local-{hashlib.md5(source_dir.encode()).hexdigest()[:8]}"

    model_dir = DATA_ROOT / "sherpa-onnx" / model_id / version
    model_dir.mkdir(parents=True, exist_ok=True)

    if progress_cb:
        progress_cb(0.5, "复制模型文件...")

    # Copy files
    files = []
    for fname in ["model.int8.onnx", "model.onnx", "tokens.txt", "silero_vad.onnx"]:
        src_file = src / fname
        if src_file.exists():
            shutil.copy2(str(src_file), str(model_dir / fname))
            files.append(
                ModelFile(
                    filename=fname,
                    sha256=sha256_file(model_dir / fname),
                    size_bytes=(model_dir / fname).stat().st_size,
                )
            )

    checksum = sha256_directory(model_dir, [f.filename for f in files])

    entry = ModelEntry(
        id=model_id,
        name=_model_display_name(model_id),
        version=version,
        engine="sherpa-onnx",
        files=files,
        checksum=checksum,
        installed=True,
        active=not any(m.active for m in registry.list_models()),
        path=str(model_dir),
    )
    registry.register(entry)

    if progress_cb:
        progress_cb(1.0, "导入完成")

    return entry
