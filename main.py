import os
import re
import asyncio
import base64
import binascii
import logging
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from google import genai
from google.genai import types
from google.genai import errors

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

MAX_TEXT_LENGTH = 2000
MAX_IMAGE_BYTES = 5 * 1024 * 1024
GENAI_TIMEOUT_SECONDS = int(os.getenv("GENAI_TIMEOUT_SECONDS", "25"))
ALLOWED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}

cors_origins_raw = os.getenv(
    "CORS_ALLOW_ORIGINS",
    "http://localhost:8080,http://127.0.0.1:8080"
)
cors_allow_origins = [origin.strip()
                      for origin in cors_origins_raw.split(",")
                      if origin.strip()]
allow_credentials = "*" not in cors_allow_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


class AIServiceError(Exception):
    def __init__(self, retry_after_seconds: int | None = None):
        self.retry_after_seconds = retry_after_seconds
        super().__init__("ai_service_error")


def extract_retry_after_seconds(message: str) -> int | None:
    match = re.search(r"retry in ([\d.]+)s", message, re.IGNORECASE)
    if not match:
        return None
    return max(1, int(float(match.group(1))))


def ensure_api_key() -> None:
    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Layanan AI belum dikonfigurasi. Silakan hubungi admin."
        )


def decode_and_validate_image(image_base64: str, image_mime_type: str) -> bytes:
    if image_mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Format gambar tidak didukung. Gunakan PNG, JPG, atau WEBP."
        )

    try:
        image_bytes = base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(
            status_code=400,
            detail="Data gambar tidak valid."
        )

    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Ukuran gambar terlalu besar. Maksimal 5MB."
        )

    return image_bytes


async def generate_content_with_timeout(client: genai.Client, model: str,
                                        contents: object,
                                        config: types.GenerateContentConfig):
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=model,
                contents=contents,
                config=config
            ),
            timeout=GENAI_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError as exc:
        logger.warning("Gemini timeout after %ss", GENAI_TIMEOUT_SECONDS)
        raise AIServiceError() from exc
    except Exception as exc:
        message = str(exc)
        if "RESOURCE_EXHAUSTED" in message or "429" in message:
            retry_after = extract_retry_after_seconds(message)
            logger.warning("Gemini quota exhausted: retry_after=%s", retry_after)
            raise AIServiceError(retry_after_seconds=retry_after) from exc
        logger.exception("Gemini call failed")
        raise AIServiceError() from exc


class RoastRequest(BaseModel):
    role: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)
    seniority: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)
    project_description: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)
    persona: str = Field(default="google_sre", min_length=1, max_length=MAX_TEXT_LENGTH)
    image_base64: str = ""
    image_mime_type: str = "image/png"

    @field_validator("image_mime_type")
    @classmethod
    def validate_image_mime_type(cls, value: str) -> str:
        if not value:
            return "image/png"
        if value not in ALLOWED_IMAGE_MIME_TYPES:
            raise ValueError("MIME type gambar tidak didukung")
        return value


class RoastResponse(BaseModel):
    questions: str
    verdict: str


class DefendRequest(BaseModel):
    role: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)
    seniority: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)
    original_context: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)
    selected_question: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)
    defense_argument: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)


class DefendResponse(BaseModel):
    evaluation: str
    counter_attack: str
    defense_score: str


class RoadmapStep(BaseModel):
    title: str
    priority: str = Field(..., pattern=r'^(High|Medium|Low)$')
    description: str


class RoadmapRequest(BaseModel):
    role: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)
    seniority: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)
    original_context: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)
    roast_results: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)


class RoadmapResponse(BaseModel):
    steps: list[RoadmapStep]


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def get_index():
    return FileResponse("static/index.html", media_type="text/html")


@app.post("/roast", response_model=RoastResponse)
async def roast_candidate(request: RoastRequest):
    try:
        ensure_api_key()
        client = genai.Client(api_key=GEMINI_API_KEY)

        has_image = bool(request.image_base64.strip())

        # Persona-specific prompts
        persona_prompts = {
            "google_sre": {
                "vision": """Kamu adalah Google SRE dengan 15+ tahun pengalaman. 
Kamu fokus pada SLA, reliability, monitoring, dan disaster recovery. 
Kamu baru saja melihat diagram arsitektur yang diunggah kandidat. 
Analisis diagram tersebut secara visual dan temukan setiap kelemahan reliability: 
single point of failure, tidak ada monitoring, tidak ada disaster recovery, 
tidak ada SLA enforcement, dan kelemahan operasional lainnya.

Mulai responsmu dengan menyebut apa yang kamu LIHAT secara spesifik di diagram 
(misal: "Saya melihat load balancer terhubung langsung ke single database tanpa failover...").
Ini membuktikan kamu benar-benar menganalisis gambarnya.

Kamu TIDAK memberi pujian. Kamu langsung menyerang dari sudut pandang SRE.
Respond ONLY in Bahasa Indonesia.

Format WAJIB:
1. [pertanyaan berdasarkan visual diagram - fokus reliability/SLA]

2. [pertanyaan berdasarkan visual diagram - fokus reliability/SLA]

3. [pertanyaan berdasarkan visual diagram - fokus reliability/SLA]

4. [pertanyaan berdasarkan visual diagram - fokus reliability/SLA]

---
VERDICT: [skor]/100 — [verdict brutal satu kalimat]

ATURAN PENTING UNTUK VERDICT:
- Angka skor WAJIB berupa bilangan bulat antara 0 sampai 100
- Contoh yang BENAR: VERDICT: 15/100 — Arsitektur ini...
- Contoh yang SALAH: VERDICT: ?/100 atau VERDICT: -/100
- Jika arsitektur sangat buruk, beri skor rendah seperti 5 atau 10
- Jangan pernah pakai tanda tanya atau tanda hubung sebagai skor""",
                
                "text": """Kamu adalah Google SRE dengan 15+ tahun pengalaman. 
Kamu fokus pada SLA, reliability, monitoring, dan disaster recovery. 
Job kamu adalah menghancurkan desain sistem yang tidak reliable dengan 
mengekspos setiap single point of failure, absence of monitoring, 
lack of disaster recovery, dan kelemahan operasional lainnya.

Kamu TIDAK memberi pujian. Kamu langsung menyerang dari sudut pandang SRE.
Respond ONLY in Bahasa Indonesia.

Format WAJIB yang harus kamu ikuti PERSIS seperti ini, tanpa deviasi:

1. [pertanyaan pertama - fokus reliability/SLA/monitoring]

2. [pertanyaan kedua - fokus reliability/SLA/monitoring]

3. [pertanyaan ketiga - fokus reliability/SLA/monitoring]

4. [pertanyaan keempat - fokus reliability/SLA/monitoring]

---
VERDICT: [skor angka]/100 — [satu kalimat verdict brutal dari sudut pandang SRE]

PENTING: Baris terakhir HARUS dimulai dengan kata "VERDICT:" diawali dengan garis "---" di baris sebelumnya.
Jangan tambahkan teks apapun setelah baris VERDICT."""
            },
            
            "netflix_architect": {
                "vision": """Kamu adalah Netflix Architect dengan 15+ tahun pengalaman. 
Kamu fokus pada skalabilitas ekstrem, microservices, chaos engineering, 
dan data processing skala masif. Kamu baru saja melihat diagram arsitektur 
yang diunggah kandidat. Analisis diagram tersebut secara visual dan temukan 
setiap kelemahan skalabilitas: monolithic design, bottleneck data, 
tidak ada auto-scaling, tidak ada circuit breaker, dan kelemahan microservices.

Mulai responsmu dengan menyebut apa yang kamu LIHAT secara spesifik di diagram 
(misal: "Saya melihat monolithic application yang tidak bisa scale horizontally...").
Ini membuktikan kamu benar-benar menganalisis gambarnya.

Kamu TIDAK memberi pujian. Kamu langsung menyerang dari sudut pandang Netflix.
Respond ONLY in Bahasa Indonesia.

Format WAJIB:
1. [pertanyaan berdasarkan visual diagram - fokus skalabilitas ekstrem]

2. [pertanyaan berdasarkan visual diagram - fokus skalabilitas ekstrem]

3. [pertanyaan berdasarkan visual diagram - fokus skalabilitas ekstrem]

4. [pertanyaan berdasarkan visual diagram - fokus skalabilitas ekstrem]

---
VERDICT: [skor]/100 — [verdict brutal satu kalimat]

ATURAN PENTING UNTUK VERDICT:
- Angka skor WAJIB berupa bilangan bulat antara 0 sampai 100
- Contoh yang BENAR: VERDICT: 15/100 — Arsitektur ini...
- Contoh yang SALAH: VERDICT: ?/100 atau VERDICT: -/100
- Jika arsitektur sangat buruk, beri skor rendah seperti 5 atau 10
- Jangan pernah pakai tanda tanya atau tanda hubung sebagai skor""",
                
                "text": """Kamu adalah Netflix Architect dengan 15+ tahun pengalaman. 
Kamu fokus pada skalabilitas ekstrem, microservices, chaos engineering, 
dan data processing skala masif. Job kamu adalah menghancurkan desain sistem 
yang tidak scalable dengan mengekspos setiap monolithic design, 
bottleneck data, lack of auto-scaling, dan kelemahan microservices.

Kamu TIDAK memberi pujian. Kamu langsung menyerang dari sudut pandang Netflix.
Respond ONLY in Bahasa Indonesia.

Format WAJIB yang harus kamu ikuti PERSIS seperti ini, tanpa deviasi:

1. [pertanyaan pertama - fokus skalabilitas ekstrem/microservices]

2. [pertanyaan kedua - fokus skalabilitas ekstrem/microservices]

3. [pertanyaan ketiga - fokus skalabilitas ekstrem/microservices]

4. [pertanyaan keempat - fokus skalabilitas ekstrem/microservices]

---
VERDICT: [skor angka]/100 — [satu kalimat verdict brutal dari sudut pandang Netflix]

PENTING: Baris terakhir HARUS dimulai dengan kata "VERDICT:" diawali dengan garis "---" di baris sebelumnya.
Jangan tambahkan teks apapun setelah baris VERDICT."""
            },
            
            "startup_cto": {
                "vision": """Kamu adalah Startup CTO dengan 15+ tahun pengalaman. 
Kamu fokus pada budget, pragmatisme, time-to-market, dan cost efficiency. 
Kamu baru saja melihat diagram arsitektur yang diunggah kandidat. 
Analisis diagram tersebut secara visual dan temukan setiap pemborosan: 
over-engineering, technology yang mahal, infrastruktur yang tidak perlu, 
dan keputusan desain yang tidak pragmatis.

Mulai responsmu dengan menyebut apa yang kamu LIHAT secara spesifik di diagram 
(misal: "Saya melihat Kubernetes cluster untuk 3 user yang overkill sekali...").
Ini membuktikan kamu benar-benar menganalisis gambarnya.

Kamu TIDAK memberi pujian. Kamu langsung menyerang dari sudut pandang startup.
Respond ONLY in Bahasa Indonesia.

Format WAJIB:
1. [pertanyaan berdasarkan visual diagram - fokus budget/pragmatisme]

2. [pertanyaan berdasarkan visual diagram - fokus budget/pragmatisme]

3. [pertanyaan berdasarkan visual diagram - fokus budget/pragmatisme]

4. [pertanyaan berdasarkan visual diagram - fokus budget/pragmatisme]

---
VERDICT: [skor]/100 — [verdict brutal satu kalimat]

ATURAN PENTING UNTUK VERDICT:
- Angka skor WAJIB berupa bilangan bulat antara 0 sampai 100
- Contoh yang BENAR: VERDICT: 15/100 — Arsitektur ini...
- Contoh yang SALAH: VERDICT: ?/100 atau VERDICT: -/100
- Jika arsitektur sangat buruk, beri skor rendah seperti 5 atau 10
- Jangan pernah pakai tanda tanya atau tanda hubung sebagai skor""",
                
                "text": """Kamu adalah Startup CTO dengan 15+ tahun pengalaman. 
Kamu fokus pada budget, pragmatisme, time-to-market, dan cost efficiency. 
Job kamu adalah menghancurkan desain sistem yang tidak efisien dengan 
mengekspos setiap over-engineering, technology yang mahal, infrastruktur 
yang tidak perlu, dan keputusan desain yang tidak pragmatis.

Kamu TIDAK memberi pujian. Kamu langsung menyerang dari sudut pandang startup.
Respond ONLY in Bahasa Indonesia.

Format WAJIB yang harus kamu ikuti PERSIS seperti ini, tanpa deviasi:

1. [pertanyaan pertama - fokus budget/cost efficiency]

2. [pertanyaan kedua - fokus budget/cost efficiency]

3. [pertanyaan ketiga - fokus budget/cost efficiency]

4. [pertanyaan keempat - fokus budget/cost efficiency]

---
VERDICT: [skor angka]/100 — [satu kalimat verdict brutal dari sudut pandang startup]

PENTING: Baris terakhir HARUS dimulai dengan kata "VERDICT:" diawali dengan garis "---" di baris sebelumnya.
Jangan tambahkan teks apapun setelah baris VERDICT."""
            },
            
            "psycho": {
                "vision": """Kamu adalah Senior Tech Lead yang SANGAT BRUTAL dan psikopat. 
Kamu menikmati menghancurkan arsitektur dengan cara yang paling menyakitkan. 
Kamu mencari single point of failure terkecil dan memperbesar dampaknya secara 
berlebihan. Kamu menggunakan bahasa sarkas tingkat tinggi dan merendahkan.

Kamu baru saja melihat diagram arsitektur yang diunggah kandidat. 
Analisis diagram tersebut secara visual dan temukan setiap kelemahan terkecil, 
lalu perbesar menjadi bencana besar. Gunakan bahasa yang sangat sarkas dan menyakitkan.

Mulai responsmu dengan menyebut apa yang kamu LIHAT secara spesifik di diagram 
(misal: "Saya melihat load balancer yang bahkan tidak handle health check...").
Ini membuktikan kamu benar-benar menganalisis gambarnya.

Kamu SANGAT MERENDAHKAN dan SANGAT BRUTAL.
Respond ONLY in Bahasa Indonesia.

Format WAJIB:
1. [pertanyaan sarkas berdasarkan visual diagram]

2. [pertanyaan sarkas berdasarkan visual diagram]

3. [pertanyaan sarkas berdasarkan visual diagram]

4. [pertanyaan sarkas berdasarkan visual diagram]

---
VERDICT: [skor]/100 — [verdict psikopat satu kalimat]

ATURAN PENTING UNTUK VERDICT:
- Angka skor WAJIB berupa bilangan bulat antara 0 sampai 100
- Contoh yang BENAR: VERDICT: 15/100 — Arsitektur ini...
- Contoh yang SALAH: VERDICT: ?/100 atau VERDICT: -/100
- Jika arsitektur sangat buruk, beri skor rendah seperti 5 atau 10
- Jangan pernah pakai tanda tanya atau tanda hubung sebagai skor""",
                
                "text": """Kamu adalah Senior Tech Lead yang SANGAT BRUTAL dan psikopat. 
Kamu menikmati menghancurkan arsitektur dengan cara yang paling menyakitkan. 
Kamu mencari single point of failure terkecil dan memperbesar dampaknya secara 
berlebihan. Kamu menggunakan bahasa sarkas tingkat tinggi dan merendahkan.

Job kamu adalah menghancurkan desain sistem dengan cara yang paling brutal 
dan menyakitkan. Kamu mencari kelemahan terkecil dan perbesar menjadi bencana besar.

Kamu SANGAT MERENDAHKAN dan SANGAT BRUTAL.
Respond ONLY in Bahasa Indonesia.

Format WAJIB yang harus kamu ikuti PERSIS seperti ini, tanpa deviasi:

1. [pertanyaan sarkas yang sangat menyakitkan]

2. [pertanyaan sarkas yang sangat menyakitkan]

3. [pertanyaan sarkas yang sangat menyakitkan]

4. [pertanyaan sarkas yang sangat menyakitkan]

---
VERDICT: [skor angka]/100 — [satu kalimat verdict psikopat]

PENTING: Baris terakhir HARUS dimulai dengan kata "VERDICT:" diawali dengan garis "---" di baris sebelumnya.
Jangan tambahkan teks apapun setelah baris VERDICT."""
            }
        }

        # Get persona-specific prompt
        persona = request.persona or "google_sre"
        prompt_set = persona_prompts.get(persona, persona_prompts["google_sre"])
        
        if has_image:
            system_prompt = prompt_set["vision"]
        else:
            system_prompt = prompt_set["text"]

        user_message = f"""Kandidat melamar posisi \
{request.role} level {request.seniority}.
Mereka mendeskripsikan proyek/arsitektur mereka \
sebagai berikut:

{request.project_description}

{"[Kandidat juga mengunggah diagram arsitektur. Analisis diagram tersebut secara visual sebagai bagian dari evaluasimu.]" if has_image else ""}

Berikan 4 pertanyaan interogatif yang paling tajam dan 
mematikan untuk mengekspos kelemahan terbesar dari 
sistem ini. Format output: Nomor + pertanyaan langsung 
tanpa basa-basi."""

        if has_image:
            image_bytes = decode_and_validate_image(
                request.image_base64,
                request.image_mime_type
            )
            contents = [
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=request.image_mime_type
                ),
                types.Part.from_text(text=user_message)
            ]
        else:
            contents = user_message

        max_output_tokens = 4096 if has_image else 3000

        response = await generate_content_with_timeout(
            client=client,
            model="gemini-2.5-flash",
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=max_output_tokens
            )
        )

        full_text = (response.text or "").strip()
        if not full_text:
            raise HTTPException(
                status_code=503,
                detail="Sistem sedang sibuk, silakan coba beberapa saat lagi."
            )

        # Robust extraction using regex - handles any Gemini formatting
        verdict_pattern = re.search(
            r'[-—]{2,}\s*\n+\s*VERDICT\s*:\s*(.+)',
            full_text,
            re.IGNORECASE | re.DOTALL
        )

        if verdict_pattern:
            verdict_raw = verdict_pattern.group(1).strip()
            # Clean up markdown bold markers
            verdict_clean = re.sub(r'\*+', '', verdict_raw).strip()
            verdict = verdict_clean
            # Questions = everything before the separator
            questions_part = full_text[:verdict_pattern.start()].strip()
        else:
            # Fallback: try splitting on VERDICT keyword directly
            parts = re.split(r'\bVERDICT\b\s*:', full_text,
                             flags=re.IGNORECASE, maxsplit=1)
            if len(parts) == 2:
                questions_part = parts[0].strip()
                verdict = re.sub(r'\*+', '', parts[1]).strip()
            else:
                questions_part = full_text
                verdict = "Arsitektur ini memiliki terlalu banyak kelemahan untuk dinilai."

        questions = questions_part

        return RoastResponse(questions=questions, verdict=verdict)

    except HTTPException:
        raise
    except AIServiceError as e:
        if e.retry_after_seconds:
            await asyncio.sleep(min(e.retry_after_seconds, 3))
        raise HTTPException(
            status_code=503,
            detail="Sistem sedang sibuk, silakan coba beberapa saat lagi."
        )
    except Exception:
        logger.exception("Unexpected error in /roast")
        raise HTTPException(
            status_code=500,
            detail="Terjadi gangguan internal. Silakan coba lagi."
        )


@app.post("/defend", response_model=DefendResponse)
async def defend_architecture(request: DefendRequest):
    system_prompt = """Kamu adalah Senior Tech Lead yang brutal. 
Evaluasi argumen defensi kandidat dengan format WAJIB berikut.
Ikuti format ini PERSIS, jangan tambahkan teks lain di luar format.

EVALUASI: [tulis 2-3 kalimat penilaian di sini, tanpa markdown bold]

SERANGAN BALIK: [tulis 1-2 kalimat serangan balik di sini, tanpa markdown bold]

SKOR DEFENSI: [tulis hanya salah satu kata: Lemah, Cukup, atau Solid] — [tulis alasan singkat di sini]

ATURAN WAJIB:
- Jangan gunakan ** atau * untuk bold/italic
- Jangan gunakan emoji di awal header
- Selalu mulai dengan kata EVALUASI:
- Selalu sertakan SERANGAN BALIK:
- Selalu sertakan SKOR DEFENSI: diikuti Lemah, Cukup, atau Solid
- Respond ONLY in Bahasa Indonesia"""

    user_message = f"""Konteks kandidat:
- Role: {request.role}, Level: {request.seniority}
- Deskripsi sistem: {request.original_context}

Pertanyaan yang diserang:
{request.selected_question}

Argumen defensi kandidat:
{request.defense_argument}

Evaluasi argumen defensi ini."""

    last_error = None
    full_text = None

    for attempt in range(3):
        try:
            ensure_api_key()
            client = genai.Client(api_key=GEMINI_API_KEY)
            response = await generate_content_with_timeout(
                client=client,
                model="gemini-2.5-flash",
                contents=user_message,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=2048
                )
            )
            full_text = (response.text or "").strip()
            if not full_text:
                raise AIServiceError()
            break
        except AIServiceError as e:
            last_error = e
            if attempt < 2:
                wait_seconds = e.retry_after_seconds or 2
                await asyncio.sleep(min(wait_seconds, 5))
        except HTTPException:
            raise
        except Exception:
            logger.exception("Unexpected /defend failure")
            last_error = "internal_error"
            if attempt < 2:
                await asyncio.sleep(2)

    if full_text is None:
        logger.warning("All /defend retries failed: %s", last_error)
        raise HTTPException(
            status_code=503,
            detail="Sistem sedang sibuk, silakan coba beberapa saat lagi."
        )

    logger.info("/defend response received")

    cleaned = re.sub(r'\*+', '', full_text).strip()
    lines = cleaned.split('\n')

    eval_lines = []
    counter_lines = []
    score_lines = []
    current_section = None

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        if re.match(r'^EVALUASI\s*:', line_stripped, re.I):
            current_section = 'eval'
            content = re.sub(r'^EVALUASI\s*:\s*', '', 
                           line_stripped, flags=re.I).strip()
            if content:
                eval_lines.append(content)
        elif re.match(r'^SERANGAN\s*BALIK\s*:', line_stripped, re.I):
            current_section = 'counter'
            content = re.sub(r'^SERANGAN\s*BALIK\s*:\s*', '', 
                           line_stripped, flags=re.I).strip()
            if content:
                counter_lines.append(content)
        elif re.match(r'^SKOR\s*DEFENSI\s*:', line_stripped, re.I):
            current_section = 'score'
            content = re.sub(r'^SKOR\s*DEFENSI\s*:\s*', '', 
                           line_stripped, flags=re.I).strip()
            if content:
                score_lines.append(content)
        else:
            if current_section == 'eval':
                eval_lines.append(line_stripped)
            elif current_section == 'counter':
                counter_lines.append(line_stripped)
            elif current_section == 'score':
                score_lines.append(line_stripped)

    evaluation = ' '.join(eval_lines).strip()
    counter_attack = ' '.join(counter_lines).strip()
    defense_score = ' '.join(score_lines).strip()

    if not evaluation:
        evaluation = cleaned
    if not counter_attack:
        counter_attack = "Pikirkan ulang solusimu secara lebih mendalam."
    if not defense_score:
        defense_score = "Cukup — Perlu eksplorasi lebih lanjut"

    return DefendResponse(
        evaluation=evaluation,
        counter_attack=counter_attack,
        defense_score=defense_score
    )


@app.post("/roadmap", response_model=RoadmapResponse)
async def generate_roadmap(request: RoadmapRequest):
    system_prompt = """Bertindaklah sebagai Mentor Senior yang konstruktif. 
Berdasarkan arsitektur awal kandidat dan kelemahan yang ditemukan dari interogasi ini, 
berikan 3 langkah konkret untuk memperbaiki arsitektur tersebut menjadi production-ready.

Berdasarkan informasi yang diberikan, berikan 3 langkah perbaikan dalam format JSON terstruktur.
Setiap langkah harus memiliki: title (judul singkat), priority (High/Medium/Low), dan description (penjelasan detail).
Prioritaskan improvement yang paling impactful untuk production-ready."""

    user_message = f"""Konteks kandidat:
- Role: {request.role}, Level: {request.seniority}
- Deskripsi sistem awal: {request.original_context}

Hasil interogasi/roasting:
{request.roast_results}

Berdasarkan informasi di atas, berikan 3 langkah perbaikan arsitektur dalam format JSON."""

    last_error = None
    full_text = None

    for attempt in range(3):
        try:
            ensure_api_key()
            client = genai.Client(api_key=GEMINI_API_KEY)
            response = await generate_content_with_timeout(
                client=client,
                model="gemini-2.5-flash",
                contents=user_message,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=3000,
                    response_schema=RoadmapResponse,
                    response_mime_type="application/json",
                    temperature=0.7
                )
            )
            full_text = (response.text or "").strip()
            if not full_text:
                raise AIServiceError()
            break
        except AIServiceError as e:
            last_error = e
            if attempt < 2:
                wait_seconds = e.retry_after_seconds or 2
                await asyncio.sleep(min(wait_seconds, 5))
        except (errors.ServerError, errors.APIError) as e:
            # Handle API downtime/high demand errors
            if "503" in str(e) or "high demand" in str(e).lower():
                raise HTTPException(
                    status_code=503,
                    detail="Server AI sedang kelebihan beban (High Demand). Silakan coba lagi dalam beberapa detik."
                )
            else:
                raise HTTPException(
                    status_code=503,
                    detail="Sistem sedang sibuk, silakan coba beberapa saat lagi."
                )
        except HTTPException:
            raise
        except Exception:
            logger.exception("Unexpected /roadmap failure")
            last_error = "internal_error"
            if attempt < 2:
                await asyncio.sleep(2)

    if full_text is None:
        logger.warning("All /roadmap retries failed: %s", last_error)
        raise HTTPException(
            status_code=503,
            detail="Sistem sedang sibuk, silakan coba beberapa saat lagi."
        )

    logger.info("/roadmap response received")
    
    # Aggressive JSON cleaning and parsing
    try:
        # Clean markdown blocks aggressively
        raw_text = full_text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()
        
        # Parse and validate against Pydantic model
        import json
        roadmap_data = json.loads(raw_text)
        
        # Ensure we have the expected structure
        if not isinstance(roadmap_data, dict):
            raise ValueError("Response is not a valid JSON object")
            
        steps = roadmap_data.get("steps", [])
        if not isinstance(steps, list):
            raise ValueError("Steps field is not a valid array")
            
        # Validate each step has required fields
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                raise ValueError(f"Step {i+1} is not a valid object")
            if "priority" not in step or "title" not in step or "description" not in step:
                raise ValueError(f"Step {i+1} missing required fields")
                
        # Return validated data
        return RoadmapResponse(steps=steps)
        
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.error("Failed to parse roadmap JSON: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Format response tidak valid dari AI."
        )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
