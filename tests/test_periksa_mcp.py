import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))
import periksa_mcp as pm  # noqa: E402


def test_samarkan_nilai_rahasia_dan_pola_kunci(monkeypatch):
    monkeypatch.setenv("COINMARKETCAP_API_KEY", "rahasia-12345678")
    teks = pm.samarkan("gagal dengan kunci rahasia-12345678 dan " + "a" * 40)
    assert "rahasia-12345678" not in teks and "a" * 40 not in teks


def test_ringkas_stream_tidak_mencetak_jawaban(capsys):
    ev = [{"type": "system", "subtype": "init", "tools": ["ToolSearch", "mcp__cmc__x"],
           "mcp_servers": [{"name": "cmc", "status": "pending"}]},
          {"type": "assistant", "message": {"content": [
              {"type": "tool_use", "name": "ToolSearch"},
              {"type": "text", "text": "JAWABAN_RAHASIA"}]}},
          {"type": "result", "subtype": "success", "result": "JAWABAN_RAHASIA",
           "num_turns": 2, "duration_ms": 3000}]
    pm.ringkas_stream(json.dumps(e) for e in ev)
    out = capsys.readouterr().out
    assert "('cmc', 'pending')" in out and "alat MCP terlihat = 1" in out
    assert "panggil: ToolSearch" in out and "JAWABAN_RAHASIA" not in out


def test_server_stdio_yang_tidak_ada():
    h = pm.periksa_stdio("x", {"command": "perintah-yang-tidak-ada-123"}, 5)
    assert h["status"] == "GAGAL START"
