/**
 * Jembatan Telegram -> GitHub Actions.
 *
 * Alur: kamu ketik pesan di Telegram -> Telegram POST ke Worker ini -> Worker memicu
 * repository_dispatch di GitHub -> workflow jalan SAAT ITU JUGA (tanpa menunggu cron).
 *
 * Worker cuma hidup beberapa milidetik per pesan, jadi masuk kuota gratis Cloudflare
 * dengan sangat longgar (100.000 permintaan/hari).
 *
 * Variabel yang harus di-set di Cloudflare (Settings -> Variables and Secrets):
 *   TELEGRAM_SECRET   : string acak buatanmu sendiri; dicocokkan dengan secret_token
 *                       yang didaftarkan ke Telegram saat setWebhook. Ini yang mencegah
 *                       orang lain memalsukan permintaan ke Worker-mu.
 *   GITHUB_TOKEN      : Personal Access Token GitHub (lihat README untuk izin minimal)
 *   GITHUB_REPO       : "ihsanmp/Crypto-Analis"
 *   ALLOWED_CHAT_IDS  : chat ID yang boleh dilayani, pisahkan koma
 */

// Penanda versi. Worker berjalan TERPISAH dari repo — `git push` TIDAK memperbaruinya,
// harus ditempel ulang manual di dashboard Cloudflare. Versi ini muncul di respons GET
// supaya bisa dipastikan versi mana yang benar-benar aktif (dulu foto hilang diam-diam
// karena Worker masih versi lama, dan tidak ada cara memeriksanya dari luar).
const WORKER_VERSION = "2026-08-09-tutup-bocor";

export default {
  async fetch(request, env) {
    // Telegram selalu POST. GET dipakai untuk cek kesehatan & konfigurasi.
    // Sengaja hanya melaporkan ADA/TIDAK-nya rahasia, tidak pernah nilainya.
    if (request.method !== "POST") {
      return new Response(
        JSON.stringify(
          {
            ok: true,
            pesan: "Worker hidup. Endpoint ini hanya menerima webhook Telegram.",
            versi: WORKER_VERSION,
            dukung_foto: true,
            konfigurasi: {
              GITHUB_TOKEN: env.GITHUB_TOKEN ? "terisi" : "KOSONG",
              TELEGRAM_SECRET: env.TELEGRAM_SECRET ? "terisi" : "KOSONG",
              GITHUB_REPO: env.GITHUB_REPO || "KOSONG",
              // JANGAN cetak nilainya. Endpoint ini TERBUKA tanpa autentikasi, dan
              // chat ID adalah identifier akun Telegram — hal yang justru repot-repot
              // di-hash keluar dari repo publik. Komentar di atas sudah menyatakan
              // "tidak pernah nilainya", tapi baris ini dulu melanggarnya sendiri.
              ALLOWED_CHAT_IDS: env.ALLOWED_CHAT_IDS
                ? `terisi (${env.ALLOWED_CHAT_IDS.split(",").filter(Boolean).length} chat)`
                : "KOSONG",
            },
          },
          null,
          2,
        ),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }

    // Verifikasi bahwa permintaan benar-benar dari Telegram, bukan orang iseng.
    const secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
    if (!env.TELEGRAM_SECRET || secret !== env.TELEGRAM_SECRET) {
      return new Response("forbidden", { status: 403 });
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("ok"); // body aneh -> abaikan, jangan bikin Telegram retry
    }

    const msg = update.message || update.edited_message;
    const chatId = msg && msg.chat ? String(msg.chat.id) : "";
    // Foto: message.photo adalah array ukuran; ambil resolusi terbesar (elemen terakhir).
    const photos = msg && Array.isArray(msg.photo) ? msg.photo : [];
    let photoFileId = photos.length ? photos[photos.length - 1].file_id : "";
    // Gambar yang dikirim sebagai FILE (tombol "Send as file", umum dari desktop) tidak
    // masuk message.photo melainkan message.document. Tanpa cabang ini gambar itu hilang.
    if (!photoFileId && msg && msg.document &&
        String(msg.document.mime_type || "").startsWith("image/")) {
      photoFileId = msg.document.file_id;
    }
    // Caption gambar dipakai sebagai teks (jadi instruksi/pertanyaan untuk gambar itu).
    const text = msg && typeof (photoFileId ? msg.caption : msg.text) === "string"
      ? (photoFileId ? msg.caption : msg.text).trim()
      : "";

    // Tidak ada chat -> abaikan.
    if (!chatId) return new Response("ok");

    // Media yang BELUM didukung (dokumen/video/voice/sticker). Dulu ini dibuang diam-diam
    // sehingga user mengira bot rusak. Sekarang dicatat supaya kelihatan di log Cloudflare.
    if (!text && !photoFileId) {
      const jenis = msg
        ? Object.keys(msg).find((k) =>
            ["document", "video", "voice", "audio", "sticker", "animation"].includes(k),
          )
        : null;
      if (jenis) console.log(`diabaikan: jenis '${jenis}' belum didukung`);
      return new Response("ok");
    }

    // Penyaringan chat di sisi Worker (bot juga menyaring lagi — pertahanan berlapis).
    const allowed = (env.ALLOWED_CHAT_IDS || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    // GAGAL-TERTUTUP. Versi lama berbunyi `if (allowed.length && ...)` sehingga daftar
    // yang KOSONG berarti semua chat dilayani — satu salah konfigurasi diam-diam membuka
    // bot ke siapa pun. Sisi bot memang menyaring lagi dan menolak jalan tanpa daftar,
    // tapi run GitHub Actions telanjur terpicu dan kuotanya terpakai.
    if (!allowed.length || !allowed.includes(chatId)) {
      return new Response("ok");
    }

    // Picu workflow. Pesannya ikut dikirim supaya workflow tidak perlu polling.
    const res = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "crypto-analis-webhook",
      },
      body: JSON.stringify({
        event_type: "telegram",
        client_payload: {
          chat_id: chatId,
          text: text.slice(0, 2000),
          photo_file_id: photoFileId,   // "" kalau bukan foto
        },
      }),
    });

    if (!res.ok) {
      const detail = await res.text();
      console.log("dispatch gagal:", res.status, detail);
      // Balas ERROR ke Telegram, jangan "ok". Dengan begini kegagalan tercatat di
      // getWebhookInfo -> last_error_message, sehingga penyebabnya kelihatan dari luar
      // tanpa perlu membuka log Cloudflare. (Sebelumnya kegagalan ini tertelan diam-diam.)
      return new Response(`dispatch gagal: GitHub ${res.status} ${detail.slice(0, 200)}`, {
        status: 502,
      });
    }

    // Sukses -> balas 200 supaya Telegram tidak mengirim ulang.
    return new Response("ok");
  },
};
