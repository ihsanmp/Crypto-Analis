"""Pembuat session string Telegram — DIJALANKAN DI KOMPUTERMU SENDIRI, sekali saja.

BACA INI DULU. Session string yang dihasilkan berkas ini memberi AKSES PENUH ke akun
Telegram-mu: membaca seluruh percakapan termasuk yang pribadi, mengirim pesan atas namamu,
melihat daftar kontak. Ia BUKAN API key — tidak ada versi read-only, dan mencabutnya
berarti mengakhiri semua sesi Telegram-mu di semua perangkat.

Karena itu:
  - Jalankan HANYA di komputermu sendiri, tidak pernah di CI atau mesin orang lain.
  - Hasilnya tempel LANGSUNG ke GitHub Secrets. Jangan ke chat, jangan ke berkas di repo,
    jangan ke catatan.
  - Kalau merasa bocor: Telegram -> Settings -> Devices -> Terminate all other sessions.

Repo ini sudah pernah kebocoran token bot lewat fixture tes dan terbuka 16 hari sebelum
ketahuan. Token bot bisa dicabut dalam 30 detik; session akun tidak sesederhana itu.

Persiapan:
  1. Buka my.telegram.org -> API development tools -> catat api_id dan api_hash
  2. pip install telethon
  3. python cloud/tgsesi.py

Nilainya diminta lewat prompt, bukan lewat argumen baris perintah — argumen tersimpan di
riwayat shell.
"""

import sys


def main():
    try:
        from telethon.sessions import StringSession
        from telethon.sync import TelegramClient
    except ImportError:
        print("Telethon belum terpasang. Jalankan:  pip install telethon", file=sys.stderr)
        sys.exit(2)

    print(__doc__.split("Persiapan:")[0].strip())
    print()
    print("-" * 70)
    jawab = input("Sudah paham risikonya dan yakin melanjutkan? (ketik: ya) ").strip()
    if jawab.lower() != "ya":
        print("Dibatalkan.")
        sys.exit(1)

    try:
        api_id = int(input("api_id  : ").strip())
    except ValueError:
        print("api_id harus angka.", file=sys.stderr)
        sys.exit(2)
    api_hash = input("api_hash: ").strip()
    if not api_hash:
        print("api_hash kosong.", file=sys.stderr)
        sys.exit(2)

    # StringSession("") = sesi baru di memori, tidak menulis berkas .session ke disk.
    # Berkas .session yang tertinggal di folder repo adalah cara paling mudah kredensial
    # ini ikut ter-commit tanpa disadari.
    with TelegramClient(StringSession(""), api_id, api_hash) as klien:
        sesi = klien.session.save()
        aku = klien.get_me()
        print()
        print(f"Masuk sebagai: {aku.first_name} (@{aku.username or 'tanpa username'})")
        print()
        print("=" * 70)
        print("SESSION STRING (salin SELURUHNYA, satu baris):")
        print("=" * 70)
        print(sesi)
        print("=" * 70)
        print()
        print("Langkah berikutnya:")
        print("  1. Salin baris di atas")
        print("  2. GitHub -> Settings -> Secrets and variables -> Actions")
        print("  3. New repository secret, nama: TELEGRAM_SESSION")
        print("  4. Tempel, simpan")
        print("  5. BERSIHKAN layar terminalmu (perintah: cls / clear)")
        print()
        print("Simpan juga api_id & api_hash sebagai TELEGRAM_API_ID dan")
        print("TELEGRAM_API_HASH — keduanya dibutuhkan tgbaca.py untuk menyambung.")


if __name__ == "__main__":
    main()
