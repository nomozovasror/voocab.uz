# Claude Code Brief — Listening Part 1: Form Completion (vertical slice)

> **Full-stack brief.** `backend`, `frontend`, va `reviewer` subagentlar ishlatiladi.
>
> **Muhim:** "Majburiy talablar" (§3) va har fazadagi "Acceptance criteria" — bular shart, tavsiya emas. Har fazani acceptance'i bilan yopib, `reviewer` bilan tekshirib, keyin keyingisiga o'ting.

---

## 1. Kontekst

`voocab` — crowdsourced IELTS platformasi. Audio ingestion pipeline (blob content-addressed, per-owner asset, async ASR, word-level transkript) allaqachon qurildi va tekshirildi. Dictation authoring ham qurilgan.

Bu brief **listening'ning birinchi vertical slice'ini** quradi: **Part 1 form completion** — uchidan-uchigacha (authoring → consumption → grading → attempt event). Bu butun listening loop'ini eng sodda, eng ko'p uchraydigan tur bilan sinaydi va eng og'ir editorni (map) tabiiy ravishda chetlab o'tadi (Part 1'da map kelmaydi).

**Form completion mexanikası** = "shablon matn + raqamli bo'shliqlar". Har bo'shliq = bitta savol, talaba eshitib to'ldiradi. Bu bitta mexanika kelajakda note/sentence/summary completion'ni ham qamraydi (bu brief faqat `form_completion` type qiymati bilan cheklanadi, lekin model kengaytiriladigan).

---

## 2. Scope

### KIRADI
- Data model: `Part`, `QuestionGroup`, `Question`, `Attempt`, `QuestionAttempt` (+ mavjud attempt jadvallari bilan reconciliation).
- Alembic migration.
- Authoring backend: material ostida Part + QuestionGroup(`form_completion`) + Questions yaratish/tahrirlash (nested), authz, validatsiya.
- Authoring UI: **Studio** makonida (`/studio/*`) form completion editori.
- Consumption backend: test olish endpoint (javoblar sizib chiqmaydi), submit + server-side grading + attempt persistence.
- Consumption UI: shablonni input'lar bilan render, audio playback, submit, natija.
- Grading: normallashgan string-match (case-insensitive, whitespace, imlo aniq, variant massiv).

### KIRMAYDI (QURMA)
- Boshqa savol turlari: MCQ, matching, map/plan/diagram labelling, short-answer, **table/flow-chart completion** (grid — keyin).
- Word-limit'ni grading qoidasi sifatida majburlash. `word_limit` **saqlanadi va ko'rsatiladi**, lekin grading'да tekshirilmaydi (keyin).
- Transkript-quvvatли subtitle/review, per-savol replay range (erkin time-range). `replay_start_ms/end_ms` maydonlari nullable qo'yiladi (kelajak uchun eshik), lekin ishlatilmaydi.
- Difficulty rating hisoblash/aggregatsiya. `QuestionAttempt` event'lari **saqlanadi**, lekin difficulty derivation bu brief'da emas (toza write path, dictation persistence'да qilganimizdek).
- XP / achievements / social hook'lar attempt ustida (keyin).
- Exam-mode (bir marta eshitish, countdown). MVP faqat **practice mode** — talaba erkin qayta eshitadi.
- Mavjud dictation authoring'ini Studio'ga ko'chirish (Studio makoni shu brief'da tug'iladi; dictation'ni keyin konsolidatsiya qilamiz).

---

## 3. Majburiy texnik talablar (butun brief bo'ylab, buzilmaydi)

1. **Paket menejeri: `uv`.** `pip` ISHLATILMAYDI (`uv add ...`, `pyproject.toml` + `uv.lock`).
2. **Backend: FastAPI + SQLModel async + PostgreSQL 18.** Barcha DB kirish async. Migratsiya faqat Alembic (`create_all` yo'q).
3. **Frontend: React + TS + Vite + shadcn/ui + Tailwind.** Mavjud **Serika Dark token theme** (CSS-variable token tizimi) ishlatiladi — yangi rang hardcode qilinmaydi. Komponentlar a11y (klaviatura, ARIA, label'lar).
4. **XAVFSIZLIK — kritik: `correct_answers` mijozга HECH QACHON yuborilmaydi.** Grading faqat server tomonда. Consumption "take" endpoint'i to'g'ri javoblarni qaytarmaydi; natija faqat submit'dan keyin server javobida keladi. Bu buzilса — butun test qiymati yo'qoladi.
5. **Grading normalizatsiyasi (aniq qoida):** solishtirishда — whitespace trim + ichki bo'shliqlarni bitta probelга collapse + case-insensitive (kичик harfга). **Imlo AYNAN** (xato imlo to'g'ri emas). Raqam/so'z ("10"/"ten") yoki imlo varianti **avtomatik o'girilmaydi** — avtor `correct_answers` massivida variantlarni o'zi beradi. Grading "ahmoq" va avtor-boshqaruvli.
6. **Polymorphism:** `QuestionGroup.config` = **JSONB** (prezentatsiya/resurs: shablon). `Question` = **normallashgan qatorlar** (grade qilinadi, event-sourced). Savollar JSON ichига ko'milmaydi.
7. **Event-sourcing atomi:** har savol javobi `QuestionAttempt` qatori sifatida saqlanadi. **Mavjud attempt jadvallari bilan reconciliation** (pastda §4.5) — dublikat qilinmaydi.
8. **Core loop ASR/transkriptга bog'liq EMAS.** Grading avtor bergan `correct_answers`га nisbatan; audio playback blob URL'дан; transkript `ready` bo'lishini KUTMAYDI. Listening'да transkript ixtiyoriy — bu slice unsiz ishlaydi.
9. **Faqat `form_completion` / Part 1.** `QuestionGroup.type` enum va `config` JSONB kelajакда boshqa turларга kengayadigan bo'lsin, lekin bu brief faqat `form_completion` implementatsiya qiladi.
10. **Studio ajratmasi:** authoring UI `/studio/*` route'lar ostида, alohида layout/navigatsiya, lekин bir codebase + bir auth. Consumption UI asosий app route'ларида.

---

## 4. Data model

UUID PK, `created_at` (server default), barcha jadval SQLModel async.

### 4.1 `Part`
| Maydon | Tur | Izoh |
|---|---|---|
| `id` | UUID PK | |
| `material_id` | UUID FK → Material, indexed | |
| `order_index` | int | 0'dan |
| `title` | str | masalan "Part 1" |
| `audio_start_ms` | int, nullable | shu part'ning material audiosidagi oralig'i; NULL = butun audio shu part |
| `audio_end_ms` | int, nullable | |

Unique: `(material_id, order_index)`. **Material 1..N part** — aynan 4 majbur EMAS. Bitta Part 1'дан iborat material to'liq, publish qilса bo'ladi.

### 4.2 `QuestionGroup`
| Maydon | Tur | Izoh |
|---|---|---|
| `id` | UUID PK | |
| `part_id` | UUID FK → Part, indexed | |
| `order_index` | int | |
| `type` | enum | bu brief: faqat `form_completion` (enum kengaytiriladigan) |
| `instructions` | str | "Complete the form below. Write NO MORE THAN THREE WORDS AND/OR A NUMBER for each answer." |
| `word_limit` | int, nullable | strukturali (kelajak grading uchun); bu brief'da **saqlanadi, tekshirilmaydi** |
| `config` | JSONB | `form_completion` uchun: `{"template": "..."}` |

Unique: `(part_id, order_index)`.

**Shablon (`config.template`) formati — majburiy:** matn ичида bo'shliqlar `{{N}}` token'lari bilan (N — 1'dan boshlanadigan bo'shliq raqami). Misol:
```
Name:              {{1}}
Delivery address:  17 {{2}} Street, Chester
Phone number:      {{3}}
Number of items:   {{4}}
```
Token'lar `{{1}}..{{N}}` uzluksiz (1'dan N gacha, sakrash yo'q).

### 4.3 `Question`
| Maydon | Tur | Izoh |
|---|---|---|
| `id` | UUID PK | |
| `group_id` | UUID FK → QuestionGroup, indexed | |
| `number` | int | 1'dan; shablondagi `{{N}}` token'iga mos, talaba ko'radigan raqam |
| `correct_answers` | JSONB (str massiv) | qabul qilinadigan javoblar, masalan `["colour", "color"]`, `["12 September", "September 12"]` |
| `replay_start_ms` | int, nullable | **kelajak uchun**, hozir NULL, ishlatilmaydi |
| `replay_end_ms` | int, nullable | **kelajak uchun** |

Unique: `(group_id, number)`.

### 4.4 `Attempt` (material-daraja urinish)
| Maydon | Tur | Izoh |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → User, indexed | |
| `material_id` | UUID FK → Material, indexed | |
| `status` | enum: `in_progress` \| `submitted` | |
| `score` | int, nullable | to'g'ri javoblar soni (submit'да) |
| `total_questions` | int, nullable | |
| `started_at` | timestamp | |
| `submitted_at` | timestamp, nullable | |

### 4.5 `QuestionAttempt` (per-savol event — event-sourcing atomi)
| Maydon | Tur | Izoh |
|---|---|---|
| `id` | UUID PK | |
| `attempt_id` | UUID FK → Attempt, indexed | |
| `question_id` | UUID FK → Question, indexed | |
| `given_answer` | str | talaba kiritgani (xom) |
| `is_correct` | bool | grading natijasi |

**RECONCILIATION (majburiy):** yangi jadval yaratishдан oldин mavjud sxema/migration'ларни tekshir — `attempts` / `segment_attempts` kabi attempt jadvallари bormi. Agar generik material-daraja `attempts` jadvali bor bo'lsa (user_id, material_id), uni **qayta ishlat/kengaytir**, dublikat qilma. `QuestionAttempt` — dictation'даги segment_attempts'ning listening analogı. Reconciliation qaroringni migration izohida hujjatlaштир.

**Migration acceptance:** `upgrade head` toza DB'да o'tadi; `downgrade -1` → `upgrade head` reversible; barcha unique constraint va indeksлар mavjud.

---

## 5. Faza 1 — Authoring backend

QuestionGroup **o'z savollari bilan bir butun** yaratiladi/yangilanadi (shablon + bo'shliqlar + javoblar bir birlik sifatida authored — alohida per-gap endpoint QILINMAYDI).

Endpointlar (authz: faqat material egasi; begona → 403, ko'rinmas → 404, mavjud patternга mos):
- `POST /api/materials/{material_id}/parts` — Part yaratish (title, order_index, audio range).
- `POST /api/parts/{part_id}/question-groups` — body: `{ type: "form_completion", instructions, word_limit?, config: {template}, questions: [{number, correct_answers}] }` → group + questions **atomik** yaratiladi.
- `PATCH /api/question-groups/{id}` — shablon + savollarni to'liq almashtirish (atomik).
- `DELETE /api/parts/{id}`, `DELETE /api/question-groups/{id}`.
- `GET /api/materials/{id}` — автор ko'rinishi: parts + groups + questions (**correct_answers bilan** — bu автор o'z materiali, egaga ko'rsatish mumkin).

**Validatsiya (422):**
- `config.template`даги `{{N}}` token'lari `1..N` uzluksiz.
- Har token uchun aynan bitta Question (number mos); ortiqcha/kam savol → xato.
- Har `correct_answers` bo'sh emас, har element trim'дан keyin bo'sh emас.
- Bo'sh instructions/template → xato.

**Acceptance:**
- Shablon + 4 bo'shliq + har biriга javoblar bilan group yaratilса: group + 4 Question atomik saqlanadi.
- Token soni ≠ savol soni → 422, hech narsa saqlanmaydi.
- Begona user material'ига group qo'shса → 403.
- PATCH shablon+savollarni to'liq almashtiradi (eski savollar qolib ketмaydi).

---

## 6. Faza 2 — Authoring UI (Studio)

`/studio/*` route'lar, alohида layout/navigatsiya. Form completion editori (`/studio/materials/:id/edit` yoki shунга o'xshash):
- **Part** boshqaruvи: qo'shish, title, audio oralig'ини **player'дан "set start/end"** bilan belgилаш (mavjуd dictation editoridagi pattern'ни qayta ishlat).
- **Group editori:**
  - Shablon uchún textarea (`{{N}}` token'lар bilan). Bo'shliq qo'shиш uchún yordamчи tugma (keyingi `{{N}}`ни kiritadi) foydali.
  - Shablondan token'лар **avtomatик aniqланади**; har token uchún qator: bo'shliq raqami + **accepted answers** (bir necha qiymatли input, masalan tag/chip) + (ixtiyorий) izoh.
  - Instructions maydoni + ixtiyorий word-limit.
  - Client-side validatsiya: har token'га mos savol; bo'sh javоб yo'q. Server 422'ни ham to'g'ri ko'rсаtади.
- Studio navigatsiyаsига "My materials" / "New listening" havolaлари.

**Talablar:** shadcn/ui + Serika Dark token theme; a11y (label'lар, klaviatura bilan bo'shliq qo'shиш/o'chиriш, ARIA).

**Acceptance:**
- Avtор shablon yozади, bo'shliqлар avtomatик qatoрларга aylanади, har biriга bir necha javоб kiritа oladi, saqлайди.
- Token bilan savol mos kelмаса, save'дан oldин ogohlantiriladi (client) va server 422'ни ko'рсаtади.
- Editor build + TS strict xatosiz; token theme ishlatilган (hardcode rang yo'q).

---

## 7. Faza 3 — Consumption backend

- `GET /api/materials/{id}/take` — test olish uchún render data: material meta, parts (audio blob URL + audio range), groups (type, instructions, template), questions (**faqat `number`** — `correct_answers` YO'Q). Visibility tekshiruvи (public yoки egasi).
- `POST /api/materials/{id}/attempts` — body: `{ answers: [{question_id, given_answer}] }`:
  1. `Attempt` yaratiladi (yoки davом ettiriladi), `status`, `started_at`.
  2. Har javob **server tomonда** normallaшtirilib (§3.5) `correct_answers`га solishtiriladi → `QuestionAttempt` (given_answer, is_correct).
  3. `score` = to'g'риlар soni, `total_questions`, `submitted_at`, `status=submitted`.
  4. Javob: per-savol `{question_id, is_correct, correct_answers}` (natijани **submit'дан keyin** ko'rsatish mumkin) + umumiy score.

**Xavfsizlik (majburiy):** `take` endpoint javobида `correct_answers` YO'Q. Grading faqat serverда. Client hech qачон submit'дан oldin to'g'ri javобни ko'ra olмайди.

**Acceptance:**
- `take` javobида hech qайси savolда `correct_answers` yo'q (test bilan tasdiqlanadi).
- To'g'ри/xato/variant/case/whitespace kombinatsiyалари to'g'ри baholanади (`"Colour "` → `["colour","color"]` = to'g'ри; `"color"` = to'g'ри; `"collour"` = xato).
- Submit → `Attempt` + har savol uchún `QuestionAttempt` saqlanади, score to'g'ри.
- Imlo aniq: `correct_answers=["photography"]`, javоб `"photography course"` = **xato** (§3.5 bo'yicha exact, word-limit tekшirилмaydi lekin ortiqcha so'з mos kelмaydi).

---

## 8. Faza 4 — Consumption UI (asosий app)

- **Audio player:** play/pause, seek; part-daraja playback (part audio oralig'и bo'yicha). Practice mode — erkin qayta eshitish. (Dictation'даги segment-loop shart EMAS; oddiy player yetади.)
- **Render:** har group — instructions + shablon, `{{N}}` token'лар **raqамли input maydonлари** bilan almaшtirilади (talaba ko'radigan `number` bilan).
- **Submit** → server javobидан per-bo'shliq natija (to'g'ри/xato) + score ko'рсаtилади. To'g'ри javоб faqat submit'дан keyin, server javобидан.
- `correct_answers` client kodида/state'ида submit'дан oldин HECH QACHON bo'lмайди.

**Talablar:** shadcn/ui + Serika Dark token theme; a11y (input label'лар, natija ARIA-live bilan e'lон).

**Acceptance:**
- Talaba shablonни input'лар bilan ko'ради, audioни eshitади, to'ldиради, submit qilади, natijani (score + har bo'shliq to'g'ри/xato) ko'ради.
- Network payload'да (take) `correct_answers` yo'q — brauzer devtools bilan tekширилса ko'рinмайди.
- Build + TS strict xatosiz; token theme.

---

## 9. Faza 5 — Testlar + reviewer gate + e2e

- Backend integratsiya testlari (real DB): authoring create/validate/authz, grading (to'g'ри/xato/variant/case/whitespace/exact-imlo), take-answer-leak yo'qligi, attempt persistence.
- Frontend build + TS strict.
- `reviewer` (read-only): §3 majбурий talablар buzилмaganини tekшир — ayniqsa **#4 (correct_answers leak yo'q)**, uv-only, async, JSONB config / normalized questions, Studio ajratmasi.
- Docker Compose e2e: автор Studio'да Part 1 form completion yaratади → talaba take → submit → grade → attempt event DB'да.

---

## 10. Implementatsiya tartibi

1. **Faza 0** — Data model (§4) + migration + attempt reconciliation.
2. **Faza 1** — Authoring backend (§5).
3. **Faza 2** — Studio authoring UI (§6).
4. **Faza 3** — Consumption backend + grading (§7).
5. **Faza 4** — Consumption UI (§8).
6. **Faza 5** — Testlar + reviewer + e2e (§9).

Har fazани acceptance criteria'си bilan yakunlab, `reviewer` bilan tekшiriб, keyin keyingисiга o'ting. **Faza 3 (grading + javоб leak)** — eng xavfsizлик-kritik joyi, alohида diqqат.
