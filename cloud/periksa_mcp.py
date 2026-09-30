"""Periksa server MCP di .mcp.cloud.json: menyala? berapa lama? berapa alat?

Latar: sampai 30 Sep 2026 log bot mencatat ketiga server `pending` saat sesi Claude
dimulai, dan ToolSearch tidak menemukan satu pun alat MCP (run 36707105373). Uji lokal
dengan server tiruan yang lambat 8 detik tetap tersambung, jadi masalahnya ada di
server/runner, bukan di CLI. Skrip ini menyalakan tiap server LANGSUNG (tanpa Claude),
mengirim `initialize` + `tools/list`, dan mencatat waktunya.

Keluaran hanya nama server, status, waktu, jumlah alat, dan potongan stderr yang sudah
disamarkan — repo ini publik.

    python cloud/periksa_mcp.py            # semua server
    python cloud/periksa_mcp.py --batas 60 # batas waktu per server (detik)
"""
import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KONFIG = os.path.join(BASE_DIR, ".mcp.cloud.json")
PROTOKOL = "2025-03-26"


def samarkan(teks):
    """Buang nilai rahasia dari environment dan pola mirip kunci dari teks log."""
    teks = teks or ""
    for nama, nilai in os.environ.items():
        if nilai and len(nilai) >= 8 and re.search(r"KEY|TOKEN|SECRET|PASS", nama):
            teks = teks.replace(nilai, "***")
    return re.sub(r"[A-Za-z0-9_\-]{32,}", "***", teks)


def _pesan(id_, metode, params=None):
    m = {"jsonrpc": "2.0", "method": metode}
    if id_ is not None:
        m["id"] = id_
    if params is not None:
        m["params"] = params
    return json.dumps(m) + "\n"


def _init_params():
    return {"protocolVersion": PROTOKOL, "capabilities": {},
            "clientInfo": {"name": "periksa-mcp", "version": "1"}}


def periksa_stdio(nama, cfg, batas):
    t0 = time.time()
    try:
        p = subprocess.Popen([cfg["command"]] + list(cfg.get("args") or []),
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, encoding="utf-8",
                             errors="replace", env={**os.environ, **(cfg.get("env") or {})})
    except (OSError, KeyError) as e:
        return {"server": nama, "status": "GAGAL START", "detail": samarkan(str(e))}

    antre, galat = queue.Queue(), []
    threading.Thread(target=lambda: [antre.put(b) for b in p.stdout], daemon=True).start()
    threading.Thread(target=lambda: [galat.append(b) for b in p.stderr], daemon=True).start()

    def tunggu(id_):
        while time.time() - t0 < batas:
            try:
                baris = antre.get(timeout=0.5)
            except queue.Empty:
                if p.poll() is not None:
                    return None
                continue
            try:
                m = json.loads(baris)
            except ValueError:
                continue          # log yang tercetak ke stdout (merusak protokol stdio)
            if m.get("id") == id_:
                return m
        return None

    hasil = {"server": nama}
    try:
        p.stdin.write(_pesan(1, "initialize", _init_params()))
        p.stdin.flush()
        m = tunggu(1)
        if not m:
            hasil.update(status="TIDAK MENJAWAB initialize" if p.poll() is None
                         else f"KELUAR kode {p.returncode}")
        else:
            hasil["detik_initialize"] = round(time.time() - t0, 1)
            p.stdin.write(_pesan(None, "notifications/initialized"))
            p.stdin.write(_pesan(2, "tools/list", {}))
            p.stdin.flush()
            m2 = tunggu(2)
            alat = ((m2 or {}).get("result") or {}).get("tools")
            hasil.update(status="OK" if alat else "TANPA tools/list",
                         alat=len(alat or []), detik_total=round(time.time() - t0, 1))
    except (BrokenPipeError, OSError) as e:
        hasil.update(status="PIPA PUTUS", detail=samarkan(str(e)))
    finally:
        p.kill()
    if hasil.get("status") != "OK":
        time.sleep(0.3)
        hasil["stderr"] = samarkan("".join(galat)[-600:]).strip()
    return hasil


def periksa_http(nama, cfg, batas):
    t0 = time.time()
    req = urllib.request.Request(
        cfg["url"], data=_pesan(1, "initialize", _init_params()).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream",
                 # User-Agent bawaan urllib ditolak 403 oleh Blockscout.
                 "User-Agent": "periksa-mcp/1"})
    try:
        with urllib.request.urlopen(req, timeout=batas) as r:
            isi = r.read(4000).decode("utf-8", "replace")
            return {"server": nama, "status": f"HTTP {r.status}",
                    "detik_initialize": round(time.time() - t0, 1),
                    "jawab_initialize": '"result"' in isi}
    except Exception as e:  # noqa: BLE001 — diagnosa: semua jenis kegagalan dilaporkan
        return {"server": nama, "status": "GAGAL", "detail": samarkan(str(e))[:300],
                "detik": round(time.time() - t0, 1)}


def ringkas_stream(baris_baris):
    """Ringkas keluaran `claude -p --output-format stream-json`: status MCP saat init,
    alat MCP yang terlihat, dan alat yang dipanggil. Tidak mencetak jawaban model."""
    for baris in baris_baris:
        try:
            e = json.loads(baris)
        except ValueError:
            continue
        if e.get("subtype") == "init":
            mcp = [t for t in e.get("tools") or [] if t.startswith("mcp__")]
            print("init: server =", [(m.get("name"), m.get("status"))
                                     for m in e.get("mcp_servers") or []],
                  f"| alat MCP terlihat = {len(mcp)}")
        elif e.get("type") == "assistant":
            for b in (e.get("message") or {}).get("content") or []:
                if b.get("type") == "tool_use":
                    print("  panggil:", b.get("name"))
        elif e.get("type") == "user":
            for b in (e.get("message") or {}).get("content") or []:
                if b.get("type") == "tool_result":
                    muat = [c.get("tool_name") for c in b.get("content") or []
                            if isinstance(c, dict) and c.get("type") == "tool_reference"]
                    print("  hasil:", f"memuat {muat}" if muat
                          else samarkan(json.dumps(b.get("content"))[:300]))
        elif e.get("type") == "system" and e.get("subtype") != "thinking_tokens":
            print("  system:", e.get("subtype"), samarkan(json.dumps(e)[:200]))
        elif e.get("type") == "result":
            print(f"akhir: {e.get('subtype')} · {e.get('num_turns')} putaran · "
                  f"{(e.get('duration_ms') or 0) / 1000:.0f} dtk")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batas", type=float, default=60.0)
    ap.add_argument("--ringkas-stream", action="store_true",
                    help="baca stream-json claude dari stdin dan ringkas status MCP-nya")
    a = ap.parse_args()
    if a.ringkas_stream:
        ringkas_stream(sys.stdin)
        return
    with open(KONFIG, encoding="utf-8") as f:
        server = json.load(f)["mcpServers"]
    gagal = 0
    for nama, cfg in server.items():
        h = (periksa_http if cfg.get("type") == "http" or "url" in cfg
             else periksa_stdio)(nama, cfg, a.batas)
        print(json.dumps(h, ensure_ascii=False))
        gagal += not (h.get("status") == "OK" or h.get("jawab_initialize"))
    sys.exit(1 if gagal else 0)


if __name__ == "__main__":
    main()
