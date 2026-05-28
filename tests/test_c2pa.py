"""Unit tests for the c2pa wrapper.

Tests use a real-shaped manifest store JSON (modelled on the Google Lyria
"Sovereign Ascent" example) injected via monkeypatching, so they don't need
a signed media fixture to exercise the parsing/summary logic.
"""

import json
from pathlib import Path

import pytest

from mtl_c2pa_mcp import c2pa as c2pa_mod


LYRIA_STORE = {
    "active_manifest": "urn:c2pa:80faaddf-fe27-1e7d-0ce5-4a70eeba2dd1",
    "manifests": {
        "urn:c2pa:80faaddf-fe27-1e7d-0ce5-4a70eeba2dd1": {
            "claim_generator_info": [
                {
                    "name": "Google C2PA Core Generator Library",
                    "version": "916434528:916944653",
                }
            ],
            "instance_id": "347d89b0-7e42-e884-20f6-44cf622e4ff8",
            "assertions": [
                {
                    "label": "c2pa.actions.v2",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.created",
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia",
                                "description": "Created by Google Generative AI.",
                            },
                            {
                                "action": "c2pa.edited",
                                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia",
                                "description": "Applied imperceptible SynthID watermark.",
                            },
                        ]
                    },
                }
            ],
            "ingredients": [],
            "signature_info": {"issuer": "Google LLC"},
        }
    },
    "validation_state": "valid",
}


@pytest.fixture
def fake_mp3(tmp_path: Path) -> Path:
    p = tmp_path / "Sovereign_Ascent.mp3"
    p.write_bytes(b"\xff\xfb\x90\x00")  # arbitrary bytes — Reader is monkeypatched
    return p


@pytest.fixture(autouse=True)
def stub_read_manifest_store(monkeypatch, fake_mp3):
    """Bypass the real Reader; return the canned Lyria-shaped store."""

    def _fake(file_path: str):
        path = c2pa_mod._resolve_path(file_path)
        c2pa_mod._mime_for(path)
        return LYRIA_STORE

    monkeypatch.setattr(c2pa_mod, "read_manifest_store", _fake)


def test_summary_flags_ai_generated(fake_mp3):
    summary = c2pa_mod.summarize(str(fake_mp3))
    assert summary["is_ai_generated"] is True
    assert summary["generator"]["name"] == "Google C2PA Core Generator Library"
    assert summary["signature_issuer"] == "Google LLC"
    assert summary["validation"] == "valid"


def test_summary_extracts_actions(fake_mp3):
    summary = c2pa_mod.summarize(str(fake_mp3))
    actions = [a["action"] for a in summary["actions"]]
    assert actions == ["c2pa.created", "c2pa.edited"]


def test_summary_detects_synthid_watermark(fake_mp3):
    summary = c2pa_mod.summarize(str(fake_mp3))
    watermark_descriptions = [w.get("description", "") for w in summary["watermarks"]]
    assert any("SynthID" in d for d in watermark_descriptions)


def test_summary_no_ingredients_for_ai_track(fake_mp3):
    summary = c2pa_mod.summarize(str(fake_mp3))
    assert summary["ingredients_count"] == 0


def test_assertions_returns_active_assertions(fake_mp3):
    result = c2pa_mod.list_assertions(str(fake_mp3))
    assert result["active_manifest"].startswith("urn:c2pa:")
    assert result["assertions"][0]["label"] == "c2pa.actions.v2"


def test_ingredients_returns_empty_list(fake_mp3):
    result = c2pa_mod.list_ingredients(str(fake_mp3))
    assert result["ingredients"] == []


def test_verify_reports_valid(fake_mp3):
    result = c2pa_mod.verify(str(fake_mp3))
    assert result["validation_state"] == "valid"
    assert result["signature_issuer"] == "Google LLC"
    assert result["failures"] == []
    assert result["is_valid"] is True


def test_resolve_path_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        c2pa_mod._resolve_path(str(tmp_path / "nope.mp3"))


def test_mime_for_unknown_extension_raises(tmp_path):
    p = tmp_path / "x.xyz"
    p.write_bytes(b"")
    with pytest.raises(ValueError):
        c2pa_mod._mime_for(p)


def test_mime_for_known_extensions():
    assert c2pa_mod._mime_for(Path("a.mp3")) == "audio/mpeg"
    assert c2pa_mod._mime_for(Path("a.wav")) == "audio/wav"
    assert c2pa_mod._mime_for(Path("a.jpg")) == "image/jpeg"
    assert c2pa_mod._mime_for(Path("a.mp4")) == "video/mp4"


class TestExtractors:
    def test_extract_generator_handles_list_form(self):
        gen = c2pa_mod._extract_generator(
            LYRIA_STORE["manifests"][LYRIA_STORE["active_manifest"]]
        )
        assert gen == {
            "name": "Google C2PA Core Generator Library",
            "version": "916434528:916944653",
        }

    def test_extract_generator_handles_legacy_string(self):
        gen = c2pa_mod._extract_generator({"claim_generator": "old_tool/1.0"})
        assert gen == {"name": "old_tool/1.0"}

    def test_extract_generator_returns_none_if_missing(self):
        assert c2pa_mod._extract_generator({}) is None

    def test_is_valid_with_no_failures_and_valid_state(self):
        assert c2pa_mod._is_valid("valid", []) is True

    def test_is_valid_with_failures(self):
        assert (
            c2pa_mod._is_valid("valid", [{"code": "signingCredential.untrusted"}])
            is False
        )

    def test_is_valid_with_invalid_state(self):
        assert c2pa_mod._is_valid("invalid", []) is False


class TestScan:
    def test_scan_directory_flags_ai_files(self, tmp_path, monkeypatch):
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        (scan_dir / "lyria.mp3").write_bytes(b"\xff\xfb\x90\x00")
        (scan_dir / "plain.mp3").write_bytes(b"\xff\xfb\x90\x00")

        def _selective(file_path: str):
            if "lyria" in file_path:
                return LYRIA_STORE
            raise c2pa_mod.C2paError("No C2PA manifest found")

        monkeypatch.setattr(c2pa_mod, "read_manifest_store", _selective)

        result = c2pa_mod.scan_directory(str(scan_dir), recursive=False)
        assert result["total_files"] == 2
        assert result["with_manifest"] == 1

        ai_entry = next(f for f in result["files"] if f["file"].endswith("lyria.mp3"))
        assert ai_entry["has_manifest"] is True
        assert ai_entry["is_ai_generated"] is True

        plain_entry = next(
            f for f in result["files"] if f["file"].endswith("plain.mp3")
        )
        assert plain_entry["has_manifest"] is False


class TestLibraryInfo:
    def test_library_info_reports_available(self):
        info = c2pa_mod.library_info()
        assert info["available"] is True
        assert info["package_version"]
        assert "audio/mpeg" in info["supported_mime_types"]


class TestServerWiring:
    """Smoke tests confirming the MCP tools wire up to the c2pa module."""

    def test_server_imports(self):
        from mtl_c2pa_mcp import server

        assert server.mcp.name == "mtl-c2pa"

    def test_summary_tool_returns_valid_json(self, fake_mp3):
        from mtl_c2pa_mcp.server import c2pa_summary

        out = c2pa_summary(str(fake_mp3))
        data = json.loads(out)
        assert data["is_ai_generated"] is True

    def test_read_tool_returns_store(self, fake_mp3):
        from mtl_c2pa_mcp.server import c2pa_read

        out = c2pa_read(str(fake_mp3))
        data = json.loads(out)
        assert data["active_manifest"].startswith("urn:c2pa:")

    def test_missing_file_returns_error_payload(self, tmp_path):
        from mtl_c2pa_mcp.server import c2pa_summary

        out = c2pa_summary(str(tmp_path / "missing.mp3"))
        data = json.loads(out)
        assert "error" in data
