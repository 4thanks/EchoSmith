"""Model registry for dynamic model management.

Manages model versions, activation, and local storage.
Registry is stored at ~/.local/share/echosmith/models/registry.json
Models are stored at ~/.local/share/echosmith/models/{engine}/{model_id}/{version}/
"""

from __future__ import annotations

import json
import os
import platform
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def _get_data_root() -> Path:
    """Return the platform-specific data root for EchoSmith."""
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA", "")
        if base:
            return Path(base) / "EchoSmith" / "models"
        return Path.home() / ".local" / "share" / "EchoSmith" / "models"
    elif platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "EchoSmith" / "models"
    else:
        xdg = os.environ.get("XDG_DATA_HOME", "")
        if xdg:
            return Path(xdg) / "echosmith" / "models"
        return Path.home() / ".local" / "share" / "echosmith" / "models"


DATA_ROOT = _get_data_root()
REGISTRY_PATH = DATA_ROOT / "registry.json"

# Legacy path for migration
LEGACY_MODEL_DIR = Path.home() / ".cache" / "sherpa-onnx" / "sense-voice"


@dataclass
class ModelFile:
    """A single model file with metadata."""

    filename: str
    sha256: str = ""
    size_bytes: int = 0


@dataclass
class ModelEntry:
    """A registered model version."""

    id: str
    name: str
    version: str
    engine: str
    engine_version: str = ""
    files: list[ModelFile] = field(default_factory=list)
    checksum: str = ""  # Overall manifest checksum
    remote_url: str = ""  # Source URL for updates
    remote_version: str = ""  # Latest remote version
    installed: bool = False
    active: bool = False
    installed_at: float = 0.0
    path: str = ""  # Resolved path to model directory

    def model_dir(self) -> Path:
        """Return the directory containing model files."""
        if self.path:
            return Path(self.path)
        return DATA_ROOT / self.engine / self.id / self.version

    def has_all_files(self) -> bool:
        """Check if all declared files exist on disk."""
        model_dir = self.model_dir()
        if not model_dir.exists():
            return False
        for f in self.files:
            if not (model_dir / f.filename).exists():
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["files"] = [asdict(f) for f in self.files]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ModelEntry:
        files = [ModelFile(**f) for f in d.get("files", [])]
        return cls(
            id=d["id"],
            name=d.get("name", d["id"]),
            version=d.get("version", "0.0.0"),
            engine=d.get("engine", "sherpa-onnx"),
            engine_version=d.get("engine_version", ""),
            files=files,
            checksum=d.get("checksum", ""),
            remote_url=d.get("remote_url", ""),
            remote_version=d.get("remote_version", ""),
            installed=d.get("installed", False),
            active=d.get("active", False),
            installed_at=d.get("installed_at", 0.0),
            path=d.get("path", ""),
        )


class ModelRegistry:
    """Persistent model registry backed by a JSON file."""

    def __init__(self, registry_path: Path = REGISTRY_PATH) -> None:
        self._path = registry_path
        self._models: dict[str, ModelEntry] = {}
        self._load()

    def _load(self) -> None:
        """Load registry from disk."""
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for entry_data in data.get("models", []):
                entry = ModelEntry.from_dict(entry_data)
                self._models[entry.id] = entry
        except (json.JSONDecodeError, KeyError, TypeError):
            pass  # Corrupted registry; start fresh

    def _save(self) -> None:
        """Persist registry to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "models": [entry.to_dict() for entry in self._models.values()],
        }
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def list_models(self) -> list[ModelEntry]:
        """Return all registered models."""
        return list(self._models.values())

    def get_model(self, model_id: str) -> ModelEntry | None:
        """Get a specific model by ID."""
        return self._models.get(model_id)

    def get_active(self) -> ModelEntry | None:
        """Get the currently active model."""
        for entry in self._models.values():
            if entry.active and entry.installed and entry.has_all_files():
                return entry
        # Fallback: return first installed model with files
        for entry in self._models.values():
            if entry.installed and entry.has_all_files():
                return entry
        return None

    def register(self, entry: ModelEntry) -> None:
        """Register or update a model entry."""
        self._models[entry.id] = entry
        self._save()

    def activate(self, model_id: str) -> None:
        """Set a model as the active one."""
        if model_id not in self._models:
            raise ValueError(f"Model not found: {model_id}")
        for entry in self._models.values():
            entry.active = False
        self._models[model_id].active = True
        self._save()

    def mark_installed(self, model_id: str, path: Path | None = None) -> None:
        """Mark a model as installed."""
        entry = self._models.get(model_id)
        if entry is None:
            raise ValueError(f"Model not found: {model_id}")
        entry.installed = True
        if path:
            entry.path = str(path)
        import time

        entry.installed_at = time.time()
        self._save()

    def uninstall(self, model_id: str) -> None:
        """Remove a model from registry and delete its files."""
        entry = self._models.get(model_id)
        if entry is None:
            return
        # Delete model directory
        model_dir = entry.model_dir()
        if model_dir.exists():
            shutil.rmtree(model_dir, ignore_errors=True)
        # Remove from registry
        del self._models[model_id]
        self._save()

    def check_updates(self, remote_manifest: dict[str, Any]) -> list[dict[str, Any]]:
        """Compare local models against a remote manifest.

        Returns a list of models with available updates.
        remote_manifest format: { "models": [ { "id", "version", ... }, ... ] }
        """
        updates = []
        for remote_model in remote_manifest.get("models", []):
            model_id = remote_model.get("id", "")
            remote_version = remote_model.get("version", "")
            local = self._models.get(model_id)
            if local is None:
                updates.append(
                    {
                        "id": model_id,
                        "name": remote_model.get("name", model_id),
                        "current_version": None,
                        "remote_version": remote_version,
                        "status": "new",
                    }
                )
            elif local.version != remote_version:
                updates.append(
                    {
                        "id": model_id,
                        "name": remote_model.get("name", model_id),
                        "current_version": local.version,
                        "remote_version": remote_version,
                        "status": "update_available",
                    }
                )
        return updates

    def import_legacy(self) -> bool:
        """Migrate models from legacy ~/.cache/sherpa-onnx/sense-voice/.

        Returns True if migration was performed.
        """
        if not LEGACY_MODEL_DIR.exists():
            return False
        # Check if already registered
        for entry in self._models.values():
            if entry.path and LEGACY_MODEL_DIR.exists():
                return False

        model_dir = LEGACY_MODEL_DIR
        has_int8 = (model_dir / "model.int8.onnx").exists()
        has_tokens = (model_dir / "tokens.txt").exists()
        if not (has_int8 and has_tokens):
            return False

        # Build file list
        files = []
        for fname in ["model.int8.onnx", "tokens.txt", "model.onnx", "silero_vad.onnx"]:
            fp = model_dir / fname
            if fp.exists():
                files.append(
                    ModelFile(
                        filename=fname,
                        size_bytes=fp.stat().st_size,
                    )
                )

        entry = ModelEntry(
            id="sensevoice-int8",
            name="SenseVoice INT8 (sherpa-onnx)",
            version="2024-07-17",
            engine="sherpa-onnx",
            files=files,
            installed=True,
            active=True,
            path=str(model_dir),
        )
        self.register(entry)
        return True


# Singleton
_registry: ModelRegistry | None = None


def get_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry
