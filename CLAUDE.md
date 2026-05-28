# mtl-c2pa-mcp

MCP server for reading C2PA content provenance manifests from media files.

## Tech Stack

- **Language**: Python 3.10+
- **Package manager**: Poetry
- **Core library**: c2pa-python (official Adobe Rust binding)
- **MCP framework**: FastMCP (mcp[cli])
- **Linter**: Ruff
- **Test framework**: pytest

## Commands

| Action | Command |
|--------|---------|
| Install | `poetry install` |
| Run server | `poetry run python -m mtl_c2pa_mcp` |
| Test | `poetry run pytest` |
| Lint | `poetry run ruff check .` |
| Format | `poetry run ruff format .` |

## Architecture

- `src/mtl_c2pa_mcp/server.py` — FastMCP tool definitions
- `src/mtl_c2pa_mcp/c2pa.py` — Wrapper around `c2pa-python` Reader: read manifest store, summarize, verify, scan
- `src/mtl_c2pa_mcp/__main__.py` — Entry point (`python -m mtl_c2pa_mcp`)

## C2PA primer

A C2PA manifest store has the shape:

```
{
  "active_manifest": "urn:c2pa:<uuid>",
  "manifests": {
    "urn:c2pa:<uuid>": {
      "claim_generator_info": [{"name": "...", "version": "..."}],
      "instance_id": "...",
      "assertions": [
        {"label": "c2pa.actions.v2", "data": {"actions": [...]}},
        {"label": "c2pa.hash.data", "data": {...}},
        ...
      ],
      "ingredients": [...],
      "signature_info": {"issuer": "...", "common_name": "..."}
    }
  },
  "validation_state": "valid",
  "validation_results": {...}
}
```

Key things to extract for a useful summary:

- **Generator**: `claim_generator_info[0]` — who produced the asset (e.g. "Google C2PA Core Generator Library")
- **Actions**: assertions with label starting `c2pa.actions` — what was done (created, edited)
- **Digital source type**: IPTC URI on actions — `trainedAlgorithmicMedia` means AI-generated
- **Watermarks**: soft-binding assertions or action descriptions mentioning "watermark" (e.g. SynthID)
- **Ingredients**: source assets used (parent/component) — empty for purely AI-generated tracks
- **Signature**: `signature_info.issuer` — who signed the claim

## Tested with

- Google Lyria MP3 downloads (May 2026 — first major AI-music service with C2PA)
- Adobe Content Credentials JPEGs
