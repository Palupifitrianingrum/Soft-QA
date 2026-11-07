# SOFT QA

### Aplikasi untuk Membantu Mengecek Kualitas Kode dengan AI

SOFT QA adalah aplikasi yang aku buat untuk membantu developer mengecek kualitas kode Python. Aplikasi ini bisa membantu menemukan kesalahan, mengecek keamanan kode, melakukan code review dengan AI, dan membuat pengujian otomatis.

## Fitur

- Analisis kode menggunakan Ruff dan Semgrep.
- Code review menggunakan AI Gemini.
- Mendeteksi kemungkinan bug dan masalah keamanan.
- Membuat test case otomatis menggunakan AI.
- Menjalankan pengujian menggunakan pytest dan Docker.
- Menampilkan hasil analisis dalam bentuk laporan PDF dan JSON.

## Teknologi yang Digunakan

- Python dan FastAPI
- React dan TypeScript
- Google Gemini API
- Ruff dan Semgrep
- Pytest dan Docker
- SQLite

## Cara Menjalankan

### Backend

```bash
cd backend
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Buat file `.env` di folder backend, lalu masukkan API Key Gemini:

```env
GEMINI_API_KEY=your_api_key
```

Jalankan backend:

```bash
uvicorn app.main:app --reload --port 8000
```

### Frontend

Buka terminal baru:

```bash
cd frontend
npm install
npm run dev
```

Kemudian buka `http://localhost:5173`.

## Status Proyek

Fitur utama sudah dibuat, tetapi masih ada beberapa bagian yang perlu diuji dan dipastikan berjalan dengan baik.

## Catatan

Saat ini SOFT QA masih ditujukan untuk penggunaan lokal dan belum memiliki fitur login atau autentikasi pengguna.

## Referensi

Proyek ini terinspirasi dari [QAura](https://github.com/Asem-Saber/QAura).
