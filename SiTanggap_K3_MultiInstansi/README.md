# SiTanggap K3 — Edisi Multi-Instansi (Multi-Tenant)

**Sistem Informasi Pelaporan Bahaya & Tindak Lanjut Keselamatan Konstruksi dengan Isolasi Data per Instansi**

Aplikasi ini dirancang agar satu server/website dapat digunakan secara bersama-sama oleh **banyak instansi, perusahaan konstruksi, maupun proyek yang berbeda**, tanpa risiko data saling tercampur atau terlihat oleh pihak lain.

---

## 1. Mekanisme Isolasi Data Antar Instansi

1. **Workspace Terpisah (`organizations`):**
   - Setiap instansi memiliki **Kode Instansi** unik (misalnya `pt-karya-k3`, `dinas-pu-diy`, `proyek-tol-a`).
   - Seluruh tabel (`users`, `reports`, `report_history`, `attachments`) terikat ketat pada `organization_id` milik sesi pengguna yang sedang login.
2. **Isolasi Penyimpanan Foto (`instance/uploads/org_<id>/`):**
   - Foto temuan bahaya yang diunggah disimpan pada folder fisik tersendiri berdasarkan ID instansi dan hanya dapat diakses melalui endpoint berotorisasi.
3. **Kode Undangan Instansi (`invite_code`):**
   - Setiap instansi mendapat **Kode Undangan** otomatis (format `K3-XXXX-XXXX`) yang dapat dibagikan oleh Administrator instansi kepada pekerja/petugas internalnya untuk bergabung, atau dapat diacak ulang (*rotate*) kapan saja demi keamanan.
4. **Nomor Laporan Independen per Instansi:**
   - Penomoran laporan (`STK3-202611-0001`, dst.) dihitung terpisah untuk masing-masing instansi.

---

## 2. Alur Penggunaan untuk Tiap Instansi

### A. Mendaftarkan Instansi / Proyek Baru
1. Buka halaman utama aplikasi, pilih tab **Instansi Baru**.
2. Isi **Nama Instansi**, buat **Kode Instansi** unik (huruf kecil/angka, contoh: `pt-konstruksi-maju`), serta buat akun **Administrator Instansi**.
3. Setelah masuk, buka menu **Instansi & Pengguna** untuk menyalin **Kode Undangan** dan **Kode Instansi**.

### B. Mengundang Anggota / Pekerja Lapangan
- **Cara Mandiri:** Bagikan **Kode Undangan** (`K3-XXXX-XXXX`) kepada pekerja/tim K3. Mereka cukup memilih tab **Gabung Instansi**, memasukkan Kode Undangan, lalu membuat akun Pelapor.
- **Cara Manual oleh Admin:** Administrator instansi dapat langsung membuatkan akun **Petugas K3 / HSE**, **Pelapor**, atau **Admin tambahan** melalui menu **Instansi & Pengguna**.

### C. Masuk (Login)
- Pengguna memasukkan **Kode Instansi**, **Username**, dan **Kata Sandi**. Kode Instansi terakhir otomatis tersimpan di browser perangkat pengguna untuk memudahkan login berikutnya.

---

## 3. Akun Demo Bawaan (Saat Database Pertama Kali Dibuat)
- **Kode Instansi:** `demo-k3`
- **Kode Undangan:** `K3-DEMO-2026`
- **Username Admin:** `admin`
- **Password Admin:** `AdminK3Resmi2026!`

---

## 4. Publikasi Resmi ke Internet (HTTPS)
Aplikasi dilengkapi `Procfile`, `Dockerfile`, dan `render.yaml` sehingga siap langsung di-deploy ke **Render.com**, **Railway**, **Fly.io**, atau **VPS (Docker + Nginx)** untuk mendapatkan tautan resmi ber-HTTPS (`https://...`).
