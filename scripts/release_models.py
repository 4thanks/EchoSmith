#!/usr/bin/env python3
"""Generate manifest.json and checksums for model releases.

Usage:
    python scripts/release_models.py --models-dir /tmp/models --version 2024-07-17 --output /tmp/release

This script:
1. Scans the models directory for model archives
2. Computes SHA256 checksums for each file
3. Generates manifest.json for the model updater
4. Generates checksums.txt for verification
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path


def sha256_file(path: Path) -> str:
    """Compute SHA256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_model_dir(model_dir: Path) -> dict:
    """Scan a model directory and return metadata."""
    files = []
    total_size = 0

    for fname in sorted(model_dir.iterdir()):
        if fname.is_file():
            size = fname.stat().st_size
            total_size += size
            files.append({
                "filename": fname.name,
                "sha256": sha256_file(fname),
                "size_bytes": size,
            })

    return {
        "files": files,
        "total_size": total_size,
    }


def generate_manifest(
    models_dir: Path,
    version: str,
    output_dir: Path,
) -> dict:
    """Generate manifest.json for the model updater."""
    models = []

    # Model definitions
    model_defs = [
        {
            "id": "sensevoice-int8",
            "name": "SenseVoice INT8",
            "engine": "sherpa-onnx",
            "engine_version": "1.12.28",
            "dir_name": "sensevoice-int8",
            "download_url": (
                "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
                "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2"
            ),
        },
        {
            "id": "silero-vad",
            "name": "Silero VAD",
            "engine": "sherpa-onnx",
            "engine_version": "1.12.28",
            "dir_name": "silero-vad",
            "download_url": (
                "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
                "silero_vad.onnx"
            ),
        },
    ]

    for model_def in model_defs:
        model_dir = models_dir / model_def["dir_name"]
        if not model_dir.exists():
            print(f"  Skipping {model_def['id']}: directory not found")
            continue

        print(f"  Scanning {model_def['id']}...")
        info = scan_model_dir(model_dir)

        models.append({
            "id": model_def["id"],
            "name": model_def["name"],
            "version": version,
            "engine": model_def["engine"],
            "engine_version": model_def["engine_version"],
            "files": info["files"],
            "total_size": info["total_size"],
            "download_url": model_def["download_url"],
        })

    manifest = {
        "version": 1,
        "released_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "models": models,
    }

    # Write manifest
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"  Manifest written: {manifest_path}")

    return manifest


def generate_checksums(output_dir: Path) -> None:
    """Generate checksums.txt for all files in output directory."""
    checksums_path = output_dir / "checksums.txt"
    lines = []

    for f in sorted(output_dir.iterdir()):
        if f.is_file() and f.name != "checksums.txt":
            checksum = sha256_file(f)
            lines.append(f"{checksum}  {f.name}")

    checksums_path.write_text("\n".join(lines) + "\n")
    print(f"  Checksums written: {checksums_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate model release manifest")
    parser.add_argument(
        "--models-dir",
        required=True,
        help="Directory containing model subdirectories",
    )
    parser.add_argument(
        "--version",
        default=time.strftime("%Y-%m-%d"),
        help="Model version tag (default: today's date)",
    )
    parser.add_argument(
        "--output",
        default="/tmp/release",
        help="Output directory for manifest and checksums",
    )
    args = parser.parse_args()

    models_dir = Path(args.models_dir)
    output_dir = Path(args.output)

    if not models_dir.exists():
        print(f"Error: models directory not found: {models_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Generating release manifest for version: {args.version}")
    print(f"Models directory: {models_dir}")
    print(f"Output directory: {output_dir}")
    print()

    manifest = generate_manifest(models_dir, args.version, output_dir)
    generate_checksums(output_dir)

    print()
    print("Release artifacts:")
    for f in sorted(output_dir.iterdir()):
        size = f.stat().st_size
        if size > 1024 * 1024:
            print(f"  {f.name}: {size / 1024 / 1024:.1f} MB")
        else:
            print(f"  {f.name}: {size / 1024:.1f} KB")

    print()
    print("Done!")


if __name__ == "__main__":
    main()
