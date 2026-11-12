# Ringkasan REST API SiTanggap K3

Semua endpoint API menggunakan prefix `/api`. Endpoint selain login memerlukan session login. Permintaan POST/PATCH/DELETE juga memerlukan header `X-CSRF-Token` yang diperoleh dari `/api/auth/me` atau respons login.

## Autentikasi

| Method | Endpoint | Keterangan |
|---|---|---|
| POST | `/api/auth/login` | Login menggunakan JSON `username` dan `password` |
| GET | `/api/auth/me` | Profil akun dan token CSRF |
| POST | `/api/auth/logout` | Mengakhiri session |
| POST | `/api/auth/change-password` | Mengganti kata sandi |
| GET | `/api/health` | Pemeriksaan status layanan |

## Laporan

| Method | Endpoint | Peran |
|---|---|---|
| GET | `/api/dashboard` | Semua pengguna login; data Pelapor dibatasi ke laporan miliknya |
| GET | `/api/reports` | Semua pengguna login; mendukung `q`, `risk`, `status` |
| POST | `/api/reports` | Semua pengguna login; `multipart/form-data` jika menyertakan foto |
| GET | `/api/reports/<id>` | Pemilik laporan, HSE, atau Administrator |
| PATCH | `/api/reports/<id>` | HSE atau Administrator |
| POST | `/api/reports/<id>/comments` | Pemilik laporan, HSE, atau Administrator |
| GET | `/api/reports/export.csv` | Semua pengguna login; data mengikuti hak akses dan filter |
| GET | `/api/attachments/<id>` | Pemilik laporan, HSE, atau Administrator |

## Pengguna

| Method | Endpoint | Peran |
|---|---|---|
| GET | `/api/users` | Administrator |
| POST | `/api/users` | Administrator; membuat akun HSE/Pelapor |
| PATCH | `/api/users/<id>` | Administrator; ubah nama atau status aktif |

## Contoh struktur data laporan

```json
{
  "reporter": "Nama Pelapor",
  "report_date": "2026-11-12T08:30",
  "location": "Lantai 2, zona struktur A",
  "category": "Jatuh dari ketinggian",
  "title": "Pekerjaan di tepi lantai tanpa pelindung",
  "description": "Ditemukan pekerja melakukan aktivitas di dekat tepi lantai tanpa guardrail.",
  "likelihood": 4,
  "impact": 5,
  "assignee": "Pengawas Lapangan",
  "due_date": "2026-11-13",
  "corrective_action": "Hentikan sementara pekerjaan dan pasang pembatas area."
}
```

Skor dan tingkat risiko dihitung server. ID laporan, pembuat, waktu pencatatan, status awal, serta riwayat dibuat oleh backend.
