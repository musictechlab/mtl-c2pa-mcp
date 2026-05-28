"""Core C2PA reading logic using the official c2pa-python library."""

import json
from pathlib import Path
from typing import Any

# Extension -> MIME type mapping for formats that commonly carry C2PA manifests.
# Audio focus (MP3 / WAV / FLAC) reflects the primary MusicTech Lab use case
# (e.g. Google Lyria AI-generated tracks), but image/video formats are included
# so the same MCP can be reused across media types.
MIME_TYPES: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".avif": "image/avif",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".pdf": "application/pdf",
}

SUPPORTED_EXTENSIONS = set(MIME_TYPES.keys())


class C2paError(Exception):
    """Raised for C2PA-specific failures (no manifest, parse error, unsupported format)."""


def _resolve_path(file_path: str) -> Path:
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path.is_file():
        raise ValueError(f"Not a file: {path}")
    return path


def _mime_for(path: Path) -> str:
    ext = path.suffix.lower()
    mime = MIME_TYPES.get(ext)
    if mime is None:
        raise ValueError(
            f"Unsupported extension: {ext}. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
    return mime


def read_manifest_store(file_path: str) -> dict[str, Any]:
    """Read the full C2PA manifest store from a file.

    Returns the parsed JSON dictionary as produced by the c2pa Reader.
    Raises C2paError if the file has no manifest.
    """
    from c2pa import C2paError as _C2paBindingError
    from c2pa import Reader

    path = _resolve_path(file_path)
    mime = _mime_for(path)

    try:
        with open(path, "rb") as stream:
            with Reader(mime, stream) as reader:
                manifest_json = reader.json()
    except FileNotFoundError:
        raise
    except OSError as e:
        raise C2paError(f"Could not open file: {e}") from e
    except _C2paBindingError as e:
        msg = str(e)
        if "no claim" in msg.lower() or "manifest" in msg.lower():
            raise C2paError(f"No C2PA manifest found in {path.name}") from e
        raise C2paError(f"C2PA read failed: {msg}") from e

    if not manifest_json:
        raise C2paError(f"No C2PA manifest found in {path.name}")

    try:
        return json.loads(manifest_json)
    except json.JSONDecodeError as e:
        raise C2paError(f"Malformed C2PA JSON: {e}") from e


def has_manifest(file_path: str) -> bool:
    """Return True if the file carries a readable C2PA manifest."""
    try:
        read_manifest_store(file_path)
        return True
    except (C2paError, FileNotFoundError, ValueError):
        return False


def get_active_manifest(store: dict[str, Any]) -> dict[str, Any] | None:
    """Return the active manifest dict from a manifest store, or None."""
    active_label = store.get("active_manifest")
    manifests = store.get("manifests", {})
    if active_label and active_label in manifests:
        return manifests[active_label]
    if manifests:
        return next(iter(manifests.values()))
    return None


def summarize(file_path: str) -> dict[str, Any]:
    """Build a human-friendly summary of the active manifest.

    Highlights the fields most useful when inspecting AI-generated audio:
    generator, AI-source flag, actions performed, ingredients, watermarks,
    and signature/validation state.
    """
    path = _resolve_path(file_path)
    store = read_manifest_store(file_path)
    active = get_active_manifest(store)

    if active is None:
        raise C2paError(f"Manifest store has no manifests: {path.name}")

    generator = _extract_generator(active)
    actions = _extract_actions(active)
    digital_sources = sorted(
        {a["digitalSourceType"] for a in actions if a.get("digitalSourceType")}
    )
    ingredients = [
        {
            "title": ing.get("title"),
            "format": ing.get("format"),
            "relationship": ing.get("relationship"),
            "instance_id": ing.get("instance_id") or ing.get("instanceId"),
        }
        for ing in active.get("ingredients", [])
    ]
    watermarks = _extract_watermarks(active)
    validation = store.get("validation_state") or store.get("validation_status")

    return {
        "file": str(path),
        "active_manifest": store.get("active_manifest"),
        "instance_id": active.get("instance_id") or active.get("instanceId"),
        "generator": generator,
        "is_ai_generated": any(
            "trainedAlgorithmicMedia" in d
            or "compositeWithTrainedAlgorithmicMedia" in d
            for d in digital_sources
        ),
        "digital_source_types": digital_sources,
        "actions": actions,
        "ingredients_count": len(ingredients),
        "ingredients": ingredients,
        "watermarks": watermarks,
        "signature_issuer": _extract_signature_issuer(active),
        "validation": validation,
        "assertion_labels": [
            a.get("label") for a in active.get("assertions", []) if a.get("label")
        ],
    }


def list_assertions(file_path: str) -> dict[str, Any]:
    """Return all assertions from the active manifest."""
    store = read_manifest_store(file_path)
    active = get_active_manifest(store)
    if active is None:
        raise C2paError("Manifest store has no manifests")
    return {
        "file": str(_resolve_path(file_path)),
        "active_manifest": store.get("active_manifest"),
        "assertions": active.get("assertions", []),
    }


def list_ingredients(file_path: str) -> dict[str, Any]:
    """Return ingredients (sources used to create this asset) from the active manifest."""
    store = read_manifest_store(file_path)
    active = get_active_manifest(store)
    if active is None:
        raise C2paError("Manifest store has no manifests")
    return {
        "file": str(_resolve_path(file_path)),
        "active_manifest": store.get("active_manifest"),
        "ingredients": active.get("ingredients", []),
    }


def verify(file_path: str) -> dict[str, Any]:
    """Return signature and validation state for the file."""
    store = read_manifest_store(file_path)
    active = get_active_manifest(store)

    validation_state = store.get("validation_state") or store.get("validation_status")
    issuer = _extract_signature_issuer(active) if active else None
    signature_info = active.get("signature_info") if active else None

    failures = []
    successes = []
    raw_results = store.get("validation_results") or {}
    for bucket in ("activeManifest", "ingredientDeltas"):
        node = raw_results.get(bucket) or {}
        failures.extend(node.get("failure", []) or [])
        successes.extend(node.get("success", []) or [])

    return {
        "file": str(_resolve_path(file_path)),
        "active_manifest": store.get("active_manifest"),
        "validation_state": validation_state,
        "signature_issuer": issuer,
        "signature_info": signature_info,
        "successes": successes,
        "failures": failures,
        "is_valid": _is_valid(validation_state, failures),
    }


def scan_directory(directory: str, recursive: bool = True) -> dict[str, Any]:
    """Scan a directory for media files and report which carry C2PA manifests."""
    dir_path = Path(directory).expanduser().resolve()
    if not dir_path.is_dir():
        raise ValueError(f"Not a directory: {dir_path}")

    pattern = "**/*" if recursive else "*"
    files: list[dict[str, Any]] = []

    for p in sorted(dir_path.glob(pattern)):
        if not p.is_file() or p.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        entry: dict[str, Any] = {"file": str(p)}
        try:
            store = read_manifest_store(str(p))
            active = get_active_manifest(store) or {}
            entry["has_manifest"] = True
            entry["generator"] = _extract_generator(active)
            actions = _extract_actions(active)
            sources = sorted(
                {a["digitalSourceType"] for a in actions if a.get("digitalSourceType")}
            )
            entry["digital_source_types"] = sources
            entry["is_ai_generated"] = any(
                "trainedAlgorithmicMedia" in s for s in sources
            )
        except C2paError:
            entry["has_manifest"] = False
        except (FileNotFoundError, ValueError) as e:
            entry["error"] = str(e)
        files.append(entry)

    return {
        "directory": str(dir_path),
        "total_files": len(files),
        "with_manifest": sum(1 for f in files if f.get("has_manifest")),
        "files": files,
    }


def library_info() -> dict[str, Any]:
    """Return c2pa-python library version and supported MIME types."""
    import importlib.metadata

    try:
        import c2pa
    except ImportError as e:
        return {"available": False, "error": str(e)}

    info: dict[str, Any] = {"available": True}
    try:
        info["package_version"] = importlib.metadata.version("c2pa-python")
    except importlib.metadata.PackageNotFoundError:
        info["package_version"] = None

    sdk_version = getattr(c2pa, "sdk_version", None)
    if callable(sdk_version):
        try:
            info["sdk_version"] = sdk_version()
        except TypeError:
            info["sdk_version"] = None
    else:
        info["sdk_version"] = sdk_version

    try:
        from c2pa import Reader

        info["supported_mime_types"] = sorted(Reader.get_supported_mime_types())
    except (ImportError, AttributeError):
        info["supported_mime_types"] = sorted(set(MIME_TYPES.values()))

    info["supported_extensions"] = sorted(SUPPORTED_EXTENSIONS)
    return info


def _extract_generator(manifest: dict[str, Any]) -> dict[str, Any] | None:
    info = manifest.get("claim_generator_info")
    if isinstance(info, list) and info:
        first = info[0]
        return {"name": first.get("name"), "version": first.get("version")}
    legacy = manifest.get("claim_generator")
    if legacy:
        return {"name": legacy}
    return None


def _extract_actions(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for assertion in manifest.get("assertions", []):
        label = assertion.get("label", "")
        if not label.startswith("c2pa.actions"):
            continue
        for action in assertion.get("data", {}).get("actions", []) or []:
            actions.append(
                {
                    "action": action.get("action"),
                    "digitalSourceType": action.get("digitalSourceType"),
                    "description": action.get("description"),
                    "softwareAgent": action.get("softwareAgent"),
                }
            )
    return actions


def _extract_watermarks(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Find soft-binding / watermark assertions (e.g. Google SynthID)."""
    watermarks: list[dict[str, Any]] = []
    for assertion in manifest.get("assertions", []):
        label = assertion.get("label", "")
        if label.startswith("c2pa.soft_binding") or "watermark" in label.lower():
            watermarks.append({"label": label, "data": assertion.get("data")})
            continue
        # Also surface "Applied … watermark" descriptions from actions.v2
        for action in assertion.get("data", {}).get("actions", []) or []:
            desc = (action.get("description") or "").lower()
            if "watermark" in desc:
                watermarks.append(
                    {
                        "label": label,
                        "action": action.get("action"),
                        "description": action.get("description"),
                    }
                )
    return watermarks


def _extract_signature_issuer(manifest: dict[str, Any] | None) -> str | None:
    if not manifest:
        return None
    sig = manifest.get("signature_info") or {}
    return sig.get("issuer") or sig.get("common_name")


def _is_valid(state: Any, failures: list[Any]) -> bool:
    if failures:
        return False
    if isinstance(state, str):
        return state.lower() in {"valid", "trusted"}
    return state is None
