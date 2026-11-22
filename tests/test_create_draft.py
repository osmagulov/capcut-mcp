"""Smoke test: build a draft in a temporary folder and check the resulting JSON.

CapCut itself is not needed: CAPCUT_DRAFTS_PATH points the server at a temp dir.
"""

import importlib
import json
import struct
import zlib

import pytest


def _write_png(path, w=16, h=16):
    """Write a tiny solid-colour PNG without extra dependencies."""
    raw = b"".join(b"\x00" + b"\xff\x80\x00" * w for _ in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def server(tmp_path, monkeypatch):
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    monkeypatch.setenv("CAPCUT_DRAFTS_PATH", str(drafts))
    import capcut_mcp.server as srv

    srv = importlib.reload(srv)  # DRAFTS_ROOT is read at import time
    assert srv.DRAFTS_ROOT == drafts
    return srv


def test_create_and_edit_draft(server, tmp_path):
    name = "Test draft"
    res = server.create_draft(name, width=1080, height=1920, fps=30)
    ddir = server.DRAFTS_ROOT / name
    assert res["project"]["resolution"] == "1080x1920"
    for f in ("draft_content.json", "draft_meta_info.json", "claude_project.json"):
        assert (ddir / f).is_file(), f

    png = tmp_path / "pic.png"
    _write_png(png)
    server.add_media(name, str(png), duration=2.0)
    server.add_text(name, "Hello", start=0.0, duration=2.0, size=12, color="#FFCC00")
    res = server.add_subtitles(name, srt_text="1\n00:00:00,500 --> 00:00:01,500\nПривет\n")
    assert res["duration_sec"] == pytest.approx(2.0)
    assert res["backup"]  # a backup is made before each overwrite

    content = json.loads((ddir / "draft_content.json").read_text(encoding="utf-8"))
    assert content["canvas_config"]["width"] == 1080
    assert content["canvas_config"]["height"] == 1920
    assert content["duration"] == 2_000_000
    track_types = sorted(t["type"] for t in content["tracks"])
    assert track_types.count("video") == 1
    assert track_types.count("text") >= 1
    texts = [json.loads(m["content"])["text"] for m in content["materials"]["texts"]]
    assert "Hello" in texts and "Привет" in texts

    meta = json.loads((ddir / "draft_meta_info.json").read_text(encoding="utf-8"))
    assert meta["draft_name"] == name
    assert meta["tm_duration"] == 2_000_000

    plan = server.get_project(name)
    assert [c["kind"] for c in plan["clips"]] == ["image", "text", "text"]

    # Moving/removing works and undo restores the previous state.
    server.remove_clip(name, plan["clips"][1]["id"])
    assert len(server.get_project(name)["clips"]) == 2
    server.undo_last_change(name)
    assert len(server.get_project(name)["clips"]) == 3

    drafts = server.list_drafts()["drafts"]
    assert drafts[0]["name"] == name and drafts[0]["editable"] is True


def test_foreign_draft_is_read_only(server):
    ddir = server.DRAFTS_ROOT / "Manual"
    ddir.mkdir()
    (ddir / "draft_content.json").write_text(json.dumps({"tracks": [], "materials": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        server.add_text("Manual", "x", start=0, duration=1)
    assert server.inspect_draft("Manual")["editable_by_claude"] is False
