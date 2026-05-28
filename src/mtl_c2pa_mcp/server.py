"""MCP server exposing C2PA content provenance tools for Claude Code."""

import json

from mcp.server.fastmcp import FastMCP

from .c2pa import (
    C2paError,
    library_info,
    list_assertions,
    list_ingredients,
    read_manifest_store,
    scan_directory,
    summarize,
    verify,
)

mcp = FastMCP(
    "mtl-c2pa",
    instructions=(
        "C2PA (Content Provenance & Authenticity) reader. Inspect AI-provenance "
        "manifests embedded in media files such as Google Lyria MP3s, Adobe "
        "Content Credentials images, and other C2PA-signed assets. Use "
        "c2pa_summary for a quick human-friendly read, c2pa_read for the full "
        "manifest store, c2pa_verify to check signatures, and c2pa_scan to audit "
        "a directory."
    ),
)


def _error(exc: Exception) -> str:
    return json.dumps({"error": str(exc)}, ensure_ascii=False)


def _ok(payload: dict) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


@mcp.tool()
def c2pa_read(file_path: str) -> str:
    """Read the full C2PA manifest store from a media file.

    Returns the raw manifest store as produced by the C2PA reader, including
    all manifests, assertions, ingredients, validation state, and signature
    info. Use c2pa_summary for a friendlier overview.

    Args:
        file_path: Absolute path to the media file (mp3, jpg, png, mp4, etc.).
    """
    try:
        store = read_manifest_store(file_path)
        return _ok(store)
    except (FileNotFoundError, ValueError, C2paError) as e:
        return _error(e)


@mcp.tool()
def c2pa_summary(file_path: str) -> str:
    """Get a human-friendly summary of a file's C2PA manifest.

    Highlights the most useful fields: claim generator (e.g. "Google C2PA Core
    Generator Library"), whether the asset is AI-generated, what actions were
    performed (c2pa.created, c2pa.edited), digital source types, ingredients
    used, watermarks (e.g. Google SynthID), signature issuer, and validation
    state.

    Args:
        file_path: Absolute path to the media file.
    """
    try:
        return _ok(summarize(file_path))
    except (FileNotFoundError, ValueError, C2paError) as e:
        return _error(e)


@mcp.tool()
def c2pa_assertions(file_path: str) -> str:
    """List all assertions from the active manifest of a media file.

    Assertions are the building blocks of a C2PA claim: actions performed,
    metadata, hashes, training/data-mining declarations, soft bindings
    (watermarks), and more. Each carries a `label` (e.g. `c2pa.actions.v2`)
    and a `data` payload.

    Args:
        file_path: Absolute path to the media file.
    """
    try:
        return _ok(list_assertions(file_path))
    except (FileNotFoundError, ValueError, C2paError) as e:
        return _error(e)


@mcp.tool()
def c2pa_ingredients(file_path: str) -> str:
    """List ingredients (source assets used) from the active manifest.

    Ingredients describe the inputs that went into producing this asset —
    e.g. a parent image edited in Photoshop, or training-data references.
    Each ingredient has a title, format, relationship (parent/component),
    and may carry its own nested manifest.

    Args:
        file_path: Absolute path to the media file.
    """
    try:
        return _ok(list_ingredients(file_path))
    except (FileNotFoundError, ValueError, C2paError) as e:
        return _error(e)


@mcp.tool()
def c2pa_verify(file_path: str) -> str:
    """Verify the signature and validation state of a file's C2PA manifest.

    Returns the issuer (e.g. Google, Adobe), the C2PA validation state, and
    any validation failures or successes. Use this to check whether a manifest
    has been tampered with or whether the signing certificate is trusted.

    Args:
        file_path: Absolute path to the media file.
    """
    try:
        return _ok(verify(file_path))
    except (FileNotFoundError, ValueError, C2paError) as e:
        return _error(e)


@mcp.tool()
def c2pa_scan(directory: str, recursive: bool = True) -> str:
    """Scan a directory for media files and report C2PA manifest status.

    For every supported file, reports whether a C2PA manifest is present,
    the claim generator, and whether the asset is flagged as AI-generated.
    Useful for auditing a downloads folder, a music library, or a content
    archive for provenance coverage.

    Args:
        directory: Absolute path to the directory to scan.
        recursive: Whether to descend into subdirectories (default: true).
    """
    try:
        return _ok(scan_directory(directory, recursive=recursive))
    except (FileNotFoundError, ValueError, C2paError) as e:
        return _error(e)


@mcp.tool()
def c2pa_info() -> str:
    """Return c2pa-python library version and supported formats.

    Use this to confirm the MCP server can read C2PA manifests and to check
    which MIME types / extensions the underlying library supports.
    """
    return _ok(library_info())
