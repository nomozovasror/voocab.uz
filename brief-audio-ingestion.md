# Claude Code Brief — Audio Ingestion Pipeline (listening + dictation umumiy poydevori)

> **Bu brief backend-scoped.** Faqat `backend` va `reviewer` subagentlar ishlatiladi. Frontend (player, consumption UI, correction UI) bu brief'ga KIRMAYDI.
>
> **Muhim:** Quyidagi "Majburiy talablar" va har fazadagi "Acceptance criteria" — bular tavsiya emas, **shart.** Ularni chetlab o'tish yoki o'zgartirish mumkin emas. Har fazani acceptance criteria'si bilan yopib, keyin keyingisiga o'ting.

---

## 1. Kontekst

`voocab` — crowdsourced ingliz tili / IELTS platformasi. Ikki material turi audioga tayanadi: **listening** (hali qurilmagan) va **dictation** (authoring qismi qurilgan). Ikkalasi ham audio yuklaydi va ikkalasiga ham **timed transkripsiya** (word-level timestamp bilan) kerak:

- Dictation: transkript = talaba yozadigan reference matn (majburiy).
- Listening: transkript = subtitle + "javobni qayta eshit" uchun (ixtiyoriy).

Hozirgi dictation authoring modelida `Material` obyektida `audio_url` to'g'ridan-to'g'ri o'tiribdi — audio material bilan 1:1 bog'langan. Bu ikki muammoni keltiradi: (a) bir audioni bir necha material ishlatsa, u qayta yuklanadi/saqlanadi; (b) qimmat transkripsiya har material uchun qayta hisoblanadi.

**Bu brief shu poydevorni to'g'rilaydi:** audioni birinchi darajali, content-addressed entity qiladi, transkripsiyani bir marta (per unique audio) hisoblaydi, va async ASR pipeline'ini quradi. Listening va dictation shu umumiy qatlam ustiga o'tiradi.

**Bu brief listening yoki dictation material TURINI qurmaydi** — faqat ikkalasi tayanadigan audio+transkript poydevorini.

---

## 2. Scope

### KIRADI
- Yangi data model: `AudioBlob` (content-addressed), `AudioAsset` (per-owner), `AudioSegment` (ASR-derived), va `Material` refactori (`audio_url` → `audio_asset_id`).
- Alembic migration.
- Hash bilan kalitlanadigan storage abstraksiyasi (dev: local, prod: R2).
- Upload endpoint: yuklash → hash → dedup → blob saqlash → asset yaratish → yangi blob bo'lsa ASR job navbatga.
- ASR provider interfeysi + Groq implementatsiyasi (produkatsiya).
- Postgres-backed async worker (transkripsiya jobi) + holatlar mashinasi + retry/xato boshqaruvi.
- Asset read endpoint (transkript holatini poll qilish + tayyor bo'lganda segmentlar).
- Seed skript (offline, faster-whisper, RTX 3060 uchun) — o'z materiallaringni bulk kiritish.

### KIRMAYDI (bularni QURMA)
- Listening material turi (savollar, javoblar, replay range).
- Dictation consumption / player / word-diff.
- Talaba grouping (word → jumla → paragraf) — bu consumption qatlami; data modeli buni **quvvatlashi** kerak (word-level timing saqlanadi), lekin grouping logikasi bu brief'da emas.
- Qo'lda transkript tuzatish oynasi (correction UI). Segmentlar hozircha faqat ASR canonical.
- ASR fallback zanjiri (OpenAI, self-host provider). Faqat Groq. (Interfeys kelajakda qo'shishga tayyor bo'lsin — pastga qara.)
- Speaker diarization ("kim gapiryapti"). ASR faqat matn + word-level timestamp beradi.
- Perceptual audio fingerprinting / trim-dedup. (Faqat `fingerprint` maydoni nullable qilib qo'yiladi — kelajak uchun eshik.)
- Long-audio chunking. Bitta fayl Groq limitidan kichik deb faraz qilinadi.

---

## 3. Majburiy texnik talablar (butun brief bo'ylab, buzilmaydi)

1. **Paket menejeri: `uv`.** `pip` ISHLATILMAYDI. Barcha dependency qo'shishlar `uv add ...` orqali. `pyproject.toml` + `uv.lock` yangilanadi.
2. **Stack: FastAPI + SQLModel (async) + PostgreSQL 18.** Barcha DB kirishlar async (`AsyncSession`). Sync DB kod yozilmaydi.
3. **Migratsiya: Alembic.** Sxema o'zgarishlari faqat migration orqali. Qo'lda `create_all` ishlatilmaydi.
4. **Content-addressed blob:** har audio fayl **SHA-256** hash'i bilan bir marta saqlanadi. Storage kaliti hash'dan kelib chiqadi. Bir xil baytlar ikki marta saqlanmaydi.
5. **Til qulflangan: `en`.** ASR chaqiruvida til aniq `"en"` deb beriladi. Auto-detect ISHLATILMAYDI.
6. **Word-level timestamp majburiy.** ASR har so'z uchun `start_ms`/`end_ms` qaytarishi shart. Faqat segment-level timing yetarli EMAS.
7. **Async ASR.** Transkripsiya HTTP request ichida sinxron kutilmaydi. Upload darrov qaytadi, transkript fonda ishlanadi.
8. **Provider almashtiriladigan interfeys.** ASR bitta interfeys ortida (`ASRProvider`). Bugun faqat `GroqASR` faol; interfeys kelajakda boshqa implementatsiya qo'shishga ochiq bo'lishi kerak (kod o'zgarishisiz yangi provider ulanadi).
9. **Egalik/kontent ortogonalligi.** `AudioBlob` = shared, content-addressed (egasi yo'q). `AudioAsset` = per-owner. Ikki foydalanuvchi bir xil faylni yuklasa: ikkita asset, bitta blob, bitta transkript.

---

## 4. Data model

Barcha jadvallar SQLModel async model sifatida. UUID primary key. `created_at` timestamp (server default).

### 4.1 `AudioBlob` — shared, content-addressed (qimmat qatlam)
| Maydon | Tur | Izoh |
|---|---|---|
| `id` | UUID PK | |
| `sha256` | str, **unique**, indexed | kontent manzili; dedup shu bo'yicha |
| `storage_key` | str | R2/local kaliti (sha256'dan kelib chiqadi) |
| `size_bytes` | int | |
| `mime_type` | str | |
| `duration_ms` | int, nullable | ASR/probe aniqlagach to'ldiriladi |
| `fingerprint` | str, nullable | **kelajak uchun**, hozir doim NULL. Perceptual dedup shu ustunga quriladi. |
| `transcript_status` | enum: `pending` \| `processing` \| `ready` \| `failed` | ASR job holati |
| `transcript_attempts` | int, default 0 | retry hisoblagichi |
| `transcript_error` | str, nullable | `failed` sababi (avtorga ko'rsatish uchun) |
| `created_at` | timestamp | |

### 4.2 `AudioSegment` — blob'ga tegishli, ASR canonical
Har blob uchun ASR o'z segment chegaralarini beradi (verbose_json). **Custom segmentatsiya algoritmi YOZILMAYDI** — ASR'ning native segmentlari ishlatiladi.

| Maydon | Tur | Izoh |
|---|---|---|
| `id` | UUID PK | |
| `blob_id` | UUID FK → AudioBlob, indexed | |
| `order_index` | int | 0'dan, ketma-ket |
| `start_ms` | int | |
| `end_ms` | int | |
| `text` | str | segment matni |
| `words` | JSON | `[{"word": str, "start_ms": int, "end_ms": int}, ...]` — word-level timing shu yerda |
| `created_at` | timestamp | |

Unique constraint: `(blob_id, order_index)`.

> `words` JSON'i talaba grouping'ini (word → jumla → paragraf) quvvatlaydi. Grouping logikasi bu brief'da emas, lekin data mavjud bo'lishi shart.

### 4.3 `AudioAsset` — per-owner claim (egalik qatlami)
| Maydon | Tur | Izoh |
|---|---|---|
| `id` | UUID PK | |
| `owner_id` | UUID FK → User, indexed | |
| `blob_id` | UUID FK → AudioBlob, indexed | |
| `title` | str, nullable | egasi bergan nom (ixtiyoriy) |
| `created_at` | timestamp | |

Unique constraint: `(owner_id, blob_id)` — bitta egaga bitta blob uchun bitta asset. Bir egaga tegishli asset bir necha materialda ishlatilishi mumkin (listening + dictation bitta audiodan).

### 4.4 `Material` refactori
- `audio_url` ustunini **olib tashla**.
- `audio_asset_id` (UUID FK → AudioAsset, **nullable**) qo'sh. Nullable, chunki audiosiz materiallar (grammar/vocab/reading) ham bo'ladi.
- Qolgan maydonlar (`title`, `type`, `visibility`, `case_sensitive`, `punctuation_sensitive`) o'zgarmaydi.

> **Material holati (ready/processing) bu brief'da ALOHIDA ustun sifatida SAQLANMAYDI.** Audio materialning "tayyorligi" uning asset → blob → `transcript_status`'idan DERIVE qilinadi (read paytida). Ustun dublikat qilinsa drift chiqadi — qilma.

---

## 5. Migration (Alembic)

- Yangi jadvallar: `audio_blob`, `audio_segment`, `audio_asset`.
- `material`: `audio_url` drop, `audio_asset_id` FK add.
- **Mavjud dev data throwaway** (pre-launch, faqat lokal). `audio_url` uchun data backfill / migratsiya QURMA — bu vaqt isrofi. Migration `audio_url`'ni drop qiladi; mavjud dev materiallar audio referensini yo'qotadi (qabul qilinadi, keyin qayta yaratiladi).

**Acceptance criteria:**
- `alembic upgrade head` toza DB'da xatosiz o'tadi.
- `alembic downgrade -1` keyin `upgrade head` qayta o'tadi (migration reversible).
- Migration'dan keyin `material` jadvalida `audio_url` yo'q, `audio_asset_id` bor.

---

## 6. Storage abstraksiyasi (hash bilan kalitlanadi)

Interfeys (masalan `AudioStorage` protokoli), ikki implementatsiya:
- **LocalStorage** (dev): fayllar `/media` (yoki config'dagi yo'l) ostida, kalit = sha256.
- **R2Storage** (prod): Cloudflare R2, kalit = sha256.

Metodlar (barchasi async): `put(key: str, data: bytes, mime_type: str)`, `exists(key: str) -> bool`, `get(key: str) -> bytes`, `url(key: str) -> str`.

Qaysi implementatsiya — config bilan tanlanadi (mavjud config patterniga mos).

> Agar hozirgi kodda storage servisi bor bo'lsa (dev local / R2), uni shu interfeysga moslashtir va kalitni **hash bo'yicha** qil (avvalgi tasodifiy/UUID kalit emas).

**Acceptance criteria:**
- Bir xil `key` bilan `put` ikki marta chaqirilsa, fayl ikki marta saqlanmaydi (`exists` tekshiruvi bilan yoki idempotent yozish).
- Dev'da `put` → `/media`'da hash nomли fayl paydo bo'ladi.

---

## 7. Upload endpoint

`POST /api/uploads/audio` (mavjud endpointni shu mantiqqa yangilash):

Oqim:
1. Faylni qabul qil. **Validatsiya (mavjud):** hajm ≤ 25MB, format `mp3/m4a/wav/ogg/webm`. Buzilса `422`.
2. Fayl baytlaridan **SHA-256** hisobla.
3. **Dedup lookup:** shu `sha256`'li blob bor-yo'qligini tekshir.
   - **Mavjud (dedup-hit):** blobни qayta saqlama, ASR job'ni **navbatga qo'yma**. Mavjud blobни ishlat.
   - **Yangi:** baytlarni storage'ga saqla (kalit = sha256), yangi `AudioBlob` yarat (`transcript_status = pending`), ASR job navbatga qo'yiladi (§8).
4. Chaqiruvchi user uchun `AudioAsset` yarat/top (`get_or_create` on `(owner_id, blob_id)`).
5. Javob: `{ asset_id, blob_id, sha256, transcript_status }`.

**Acceptance criteria:**
- Yangi audio yuklansa: blob `pending`, storage'da fayl, asset yaratildi, javobда `transcript_status = pending`.
- Aynan bir xil faylni ikkinchi marta (hatto boshqa user bilan) yuklansa: yangi blob YARATILMAYDI, storage'ga qayta YOZILMAYDI, javobда mavjud blob'ning `sha256` va joriy `transcript_status`'i qaytadi. Ikkinchi user uchun alohida asset yaratiladi.
- 25MB'dan katta yoki noto'g'ri format: `422`, blob/asset yaratilmaydi.

---

## 8. ASR provider interfeysi + Groq implementatsiyasi

### 8.1 Interfeys
```
class ASRProvider(Protocol):
    async def transcribe(self, audio: bytes, mime_type: str, language: str = "en") -> TranscriptResult: ...
```
`TranscriptResult` = normalized natija: `duration_ms` + segmentlar ro'yxati, har segment `start_ms`, `end_ms`, `text`, va `words: [{word, start_ms, end_ms}]`.

> Interfeys shu forma bilan qulflansin, chunki §11 seed skript ham, kelajakdagi provayderlar ham shu `TranscriptResult`'ni chiqaradi. Turli provayderlarning xom javobi shu normalized formaga o'giriladi.

### 8.2 GroqASR (yagona faol implementatsiya)
- Groq'ning OpenAI-compatible transcription endpointini ishlat, model **`whisper-large-v3`**.
- **Word-level timestamp majburiy.** Groq/OpenAI Whisper API'da bu `response_format=verbose_json` + `timestamp_granularities` orqali olinadi. **Aniq parametr nomlarini Context7 / Groq rasmiy docs orqali tekshirib ol** (versiyaga qarab o'zgarishi mumkin) — lekin natija so'z darajасидаги timing berishi SHART.
- Til: `language="en"` aniq beriladi.
- Groq API kaliti env/config'dan (hardcode qilinmaydi).
- Xom Groq javobini `TranscriptResult`'ga normalize qil (segmentlar + words + duration).

**Acceptance criteria:**
- Qisqa test audiosi (fixture) berilsa, `GroqASR.transcribe` segmentlar VA har segmentda word-level `words` qaytaradi (bo'sh emas).
- Til aniq `"en"` uzatiladi (auto-detect emas) — test bilan tasdiqlanadi.
- API kaliti kodda emas, config'da.

---

## 9. Async worker + holatlar mashinasi + xato boshqaruvi

### 9.1 Queue mexanizmi — Postgres-backed (Redis QO'SHILMAYDI)
`blob.transcript_status`'ning o'zi navbat sifatida ishlatiladi. **Redis yoki tashqi queue infra qo'shilmaydi** — hajm kichik (oyiga ~200-500), Postgres 18 yetarli va restart-safe.

- Alohida **worker process** (docker-compose'да yangi service, bir xil codebase, alohida entrypoint, masalan `python -m app.worker`).
- Worker loop: `transcript_status = pending` (yoki retry-eligible) bloblarni **`SELECT ... FOR UPDATE SKIP LOCKED`** bilan claim qiladi (bir vaqtda ko'p worker xavfsiz, double-processing yo'q).
- Claim qilingach: `processing`'ga o'tkaz → `ASRProvider.transcribe` chaqir → natijani yoz.

### 9.2 Holatlar mashinasi
```
pending ──claim──▶ processing ──ok────▶ ready
                        │
                        ├──retryable xato──▶ pending (attempts++, backoff)
                        │                     └─(attempts ≥ MAX)──▶ failed
                        └──non-retryable xato──▶ failed
```
- **Success:** `AudioSegment` qatorlari yoziladi (order_index bo'yicha), `duration_ms` to'ldiriladi, `transcript_status = ready`.
- **Dedup-hit:** upload'da blob allaqachon `ready` bo'lsa — worker'ga umuman bormaydi (§7).

### 9.3 Xato klassifikatsiyasi (majburiy)
- **Retryable:** network timeout, HTTP `408/429/500/502/503/504`. → `attempts++`, exponential backoff bilan qayta urin, `MAX_ATTEMPTS` (masalan 3) gacha. Undan keyin `failed`.
- **Non-retryable:** HTTP `400/413/415/422`, buzuq/o'qib bo'lmaydigan audio, bo'sh transkript. → darrov `failed`, `transcript_error` to'ldiriladi (avtorga "audioni tuzatib qayta yukla" xabari uchun). Fallback CHAQIRILMAYDI.

> Non-retryable holatда boshqa provayderга o'tilmaydi — bir xil buzuq audio ikkinchi provayderда ham xato beradi, keraksiz.

**Acceptance criteria:**
- Yangi blob yuklangач, worker uni avtomatik oladi va (fixture ASR bilan) `ready`'ga o'tkazadi, `AudioSegment` qatorlari va `duration_ms` to'ldiriladi.
- Ikki worker instansi bir vaqtda ishlaganда bitta blob ikki marta ishlanmaydi (`SKIP LOCKED` bilan) — test/mock bilan tasdiqlanadi.
- Retryable xato (mock 503) → blob `pending`'ga qaytadi, `attempts` oshadi; `MAX_ATTEMPTS`'дан keyin `failed`.
- Non-retryable xato (mock 422 yoki bo'sh transkript) → blob darrov `failed`, `transcript_error` to'lган, retry BO'LMAYDI.
- Worker process restart bo'lsa, `pending`/yarim qolgan bloblar qayta olinadi (yo'qolmaydi).

---

## 10. Asset read endpoint

`GET /api/audio-assets/{asset_id}`:
- Egasi yoki (kelajakda) ruxsatli userга asset + uning blob'ining `transcript_status`, `duration_ms`ni qaytaradi.
- `transcript_status = ready` bo'lsa: `AudioSegment`lar (order_index bo'yicha, `words` bilan) ham qaytadi.
- `pending`/`processing`: segmentsiz, faqat holat (frontend poll qiladi).
- `failed`: holat + `transcript_error`.
- Begona asset: `404` (mavjud authz patterniga mos — ko'rinmas → 404, begona → 403 qoidasi).

**Acceptance criteria:**
- `ready` assetда segmentlar to'liq (order, start/end, text, words) qaytadi.
- `pending`/`processing`'да segmentsiz holat qaytadi.
- Begona/mavjud emas asset: to'g'ri status kod.

---

## 11. Seed skript (offline, RTX 3060, faster-whisper)

Alohida offline Python skript (API/worker'ning bir qismi EMAS). Maqsad: egasi (Asror) o'z ko'p materialini bulk kiritishi — GPU'да tekin, tez, aniq.

- `faster-whisper` (`large-v3`) ishlatadi, GPU'да. `uv` bilan dependency (masalan alohida optional group).
- Kirish: lokal audio fayllar papkasi + egasi (owner) user id.
- Har fayl uchun: SHA-256 hisobla → blob mavjudmi tekshir (§4 dedup) → yangi bo'lsa: storage'ga saqla (target env storage, prod uchun R2), faster-whisper bilan transkript (word-level), `AudioBlob` (`ready`) + `AudioSegment`lar yoz, `duration_ms` to'ldir → egaga `AudioAsset` yarat.
- **Bir xil `TranscriptResult` formasini chiqaradi** (§8.1) — produkatsiya bilan bir xil normalize, bir xil jadvallar. Groq'ning o'rniga faster-whisper, natija bir joyga quyiladi.
- Dedup tufayli: seed'да transkript qilingan audio, keyin foydalanuvchi o'sha faylni yuklasa — `pending`'ga tushmaydi, darrov `ready` (blob allaqachon bor).

**Acceptance criteria:**
- Skript bir papka audioни o'tkazadi: har biri uchun blob + segmentlar + asset yaratiladi, `transcript_status = ready`.
- Word-level `words` to'ldiriladi (produkatsiya bilan bir xil forma).
- Ikkinchi marta bir xil faylда: yangi blob yaratilmaydi (dedup).

---

## 12. Umumiy acceptance (butun brief)

- Barcha yangi kod async (sync DB kirish yo'q).
- `uv` bilan dependency'lar, `pyproject.toml` + `uv.lock` yangilangan.
- Backend integratsiya testlari (real DB): upload+dedup, worker success, worker retry, worker failed, asset read — o'tadi.
- `reviewer` subagent (read-only) bilan review: majburiy talablar (§3) buzilmagani tekshiriladi.
- Docker Compose'да API + worker + Postgres ko'tariladi, end-to-end: upload → worker → ready → asset read ishlaydi.

---

## 13. Implementatsiya tartibi (fazama-faza, har birини acceptance bilan yop)

1. **Faza 0** — Data model (§4) + Alembic migration (§5).
2. **Faza 1** — Storage abstraksiyasi, hash bilan kalitlash (§6).
3. **Faza 2** — Upload endpoint: hash + dedup + asset (§7).
4. **Faza 3** — ASR interfeys + GroqASR (§8).
5. **Faza 4** — Postgres-backed worker + holatlar mashinasi + retry/xato (§9).
6. **Faza 5** — Asset read endpoint (§10).
7. **Faza 6** — Seed skript (§11).

Har fazani o'zining acceptance criteria'si bilan yakunlab, keyin keyingisiga o'ting. Faza oxirida `reviewer` bilan tekshiring.
