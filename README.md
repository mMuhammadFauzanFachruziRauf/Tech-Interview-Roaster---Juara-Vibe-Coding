# 🚀 Tech Interview Roaster — #JuaraVibeCoding

> Simulator wawancara teknis berbasis AI yang dirancang untuk menghancurkan kelemahan arsitektur sistem Anda sebelum interviewer sungguhan melakukannya.

---

## 📌 Tentang Project

**Tech Interview Roaster** adalah simulator *technical interview* berbasis AI menggunakan **Google Gemini 2.5 Flash**.

Aplikasi ini bertindak sebagai:
- Tech Lead galak
- System Design Reviewer
- Architecture Critic
- Production Reliability Auditor

Tujuannya bukan memberi validasi palsu, tapi memaksa developer berpikir seperti engineer industri nyata.

---

## 🌟 Fitur Utama

### 🎭 Interviewer Persona Mode
Pilih tipe interviewer AI:

| Persona | Fokus |
|---|---|
| Google SRE | Reliability, SLA, RPO/RTO, observability |
| Netflix Architect | Skalabilitas ekstrem & distributed systems |
| Startup CTO | Efisiensi biaya & pragmatisme |
| Psycho Mode | Brutal. Tidak ada ampun. |

---

### 👁️ Multimodal Architecture Analysis (Vision)

Upload diagram arsitektur (`PNG/JPG`) dan AI akan:
- membaca alur sistem,
- menemukan bottleneck,
- mendeteksi SPOF,
- mengkritik keputusan desain.

---

### ⚔️ Defense Mode

AI tidak hanya menyerang.

Anda juga bisa:
- membela keputusan arsitektur,
- memberi justifikasi teknis,
- lalu AI akan menilai apakah argumen tersebut valid atau hanya coping engineering.

---

### 🛣️ Architecture Improvement Roadmap

AI akan memberikan roadmap perbaikan:
- 🔴 High Priority
- 🟡 Medium Priority
- 🟢 Low Priority

Bukan sekadar kritik kosong.

---

### 💾 Session Persistence

Riwayat interview terakhir disimpan menggunakan:
- Local Storage
- Session Recovery

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| AI Model | Google Gemini 2.5 Flash |
| Backend | FastAPI (Python 3.11) |
| Frontend | Vanilla JavaScript + CSS3 |
| Infrastructure | Docker + Google Cloud Run |
| API SDK | Google GenAI SDK |

---

## 🚀 Menjalankan Secara Lokal

### 1. Clone Repository

```bash
git clone https://github.com/mMuhammadFauzanFachruziRauf/Tech-Interview-Roaster---Juara-Vibe-Coding.git
cd Tech-Interview-Roaster---Juara-Vibe-Coding
```

---

### 2. Setup Virtual Environment

#### Linux / macOS
```bash
python -m venv venv
source venv/bin/activate
```

#### Windows
```bash
python -m venv venv
.\venv\Scripts\activate
```

---

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

---

### 4. Setup Environment Variables

Buat file `.env`:

```env
GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE
```

---

### 5. Jalankan Aplikasi

```bash
python main.py
```

Buka browser:

```txt
http://localhost:8080
```

---

# 🐳 Deployment (Google Cloud Run)

Deploy langsung menggunakan source-based deployment:

```bash
gcloud run deploy tech-interview-roaster --source . --region asia-southeast2 --allow-unauthenticated
```

---

## 🔐 Security & Optimization

### ✅ Server-side Validation
- Pembatasan ukuran gambar (maks 5MB)
- Validasi input teks

### ✅ Error Handling
Menangani:
- API timeout
- Gemini overload (503)
- invalid image upload

### ✅ XSS Protection
Sanitasi output AI sebelum dirender ke DOM.

### ✅ Docker Hardening
Menggunakan `.dockerignore` agar:
- `.env`
- cache
- log
tidak ikut masuk image container.

---

## 📁 Struktur Project

```bash
.
├── static/
├── templates/
├── main.py
├── requirements.txt
├── Dockerfile
├── .dockerignore
└── README.md
```

---

## 📸 Preview

### Landing Page
```md
![Landing Page](assets/landing-page.png)
```

### Roast Result
```md
![Roast Result](assets/roast-result.png)
```

---

## 💡 Kenapa Project Ini Dibuat?

Banyak developer:
- terlalu fokus coding,
- tapi lemah saat mempertahankan arsitektur sistem.

Padahal di dunia nyata:
- keputusan teknis harus bisa dipertanggungjawabkan,
- bukan sekadar “jalan di localhost”.

Project ini dibuat untuk melatih:
- system design thinking,
- scalability awareness,
- reliability mindset,
- engineering tradeoff analysis.

---

## ⚠️ Realita Engineering

Aplikasi ini sengaja dibuat agresif.

Karena production environment:
- tidak peduli perasaan developer,
- hanya peduli reliability,
- latency,
- cost,
- dan survivability.

---

## 👨‍💻 Author

### Muhammad Fauzan Fachruzi Rauf
Information Technology Student — UNIMED

Dibuat untuk kompetisi:

#JuaraVibeCoding  
Google for Developers 2026

---

# 📌 TODO / Future Improvements

- [ ] Redis Session Memory
- [ ] WebSocket Real-time Roast
- [ ] Multi-user Authentication
- [ ] Architecture Scoring System
- [ ] AI-generated Infrastructure Diagram
- [ ] Export PDF Interview Report
- [ ] Kubernetes Scenario Simulation

---

# ⭐ Repository Tips

## Bersihkan File Log

```bash
git rm uvicorn.err.log uvicorn.out.log
git commit -m "chore: remove unnecessary log files"
git push origin main
```

---

## Tambahkan Screenshot

README tanpa visual = engagement rendah.

Minimal tambahkan:
- landing page,
- upload architecture flow,
- hasil roasting AI.

Karena orang menilai project dalam <10 detik.

---

# 📄 License

MIT License

---