import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))
import bot_oneshot as bot  # noqa: E402
import hormuz  # noqa: E402

CONTOH = {"straitStatus": {"status": "RESTRICTED", "since": "2026-02-28", "description": "x"},
          "shipCount": {"percentOfNormal": 4, "last24h": 9, "normalDaily": 60},
          "strandedVessels": {"total": 211, "tankers": 86},
          "insurance": {"level": "EXTREME", "multiplier": 53.3},
          "throughput": {"percentOfNormal": 4, "last7Days": [412000] * 7},
          "tankerRates": {"changePercent": 1140},
          "globalTradeImpact": {"percentOfWorldOilAtRisk": 21},
          "diplomacy": {"status": "TALKS_IN_PROGRESS", "headline": "h", "date": "2026-11-02"},
          "news": [{"title": "t", "source": "s", "publishedAt": "2026-11-15T01:00:00Z"}],
          "lastUpdated": "2026-11-13T00:00:00Z"}


def test_ringkas_menandai_deret_statis_dan_data_basi():
    r = hormuz.ringkas(CONTOH, sekarang=datetime(2026, 11, 16, tzinfo=timezone.utc))
    assert r["status"] == "RESTRICTED" and r["kapal_tertahan"]["tanker"] == 86
    assert any("identik" in p for p in r["peringatan_mutu"])
    assert any("berumur" in p for p in r["peringatan_mutu"])
    assert "PIHAK KETIGA" in r["cara_pakai"] and "CL=F" in r["cara_pakai"]


def test_hormuz_hanya_ikut_brief_minyak(monkeypatch):
    dipanggil = []
    monkeypatch.setattr(bot, "_jalankan_terukur",
                        lambda label, args, min_kar=0: (dipanggil.append(args[0]), ("{}", None))[1])
    monkeypatch.setattr(bot, "_sisipkan_jejak", lambda bagian: None)
    monkeypatch.setattr(bot, "_sisipkan_pantau", lambda bagian, teks: None)
    bot.data_mentah_pasar("CL=F", "forex", proyeksi=False)
    assert "cloud/hormuz.py" in dipanggil
    dipanggil.clear()
    bot.data_mentah_pasar("GC=F", "forex", proyeksi=False)
    assert "cloud/hormuz.py" not in dipanggil
