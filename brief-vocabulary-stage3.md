# Vocabulary 3-bosqich — audio

Uchta narsa quriladi: **`listen` mashqi**, **"On the go" rejimi** va **gapirib tekshirish**. Uchalasi ham bitta audio qatlamiga tayanadi, shuning uchun u birinchi.

Qarorlar allaqachon qabul qilingan — bu brief ularni yozib qo'yadi, qayta ochmaydi.

---

## 0. Avval aniqlang

1. **Word-level timestamp qayerda saqlangan?** ASR quvuri ularni qaytaradi; qaysi jadvalda va qanday shaklda turibdi.
2. **R2 kalit sxemasi qanday?** Audio ingestion briefida content-hash ishlatilgan — shu naqsh TTS uchun ham qo'llanadi.
3. **Async worker job turlari qanday qo'shiladi?** TTS yangi tur bo'ladi, yangi infratuzilma emas.

---

## 1. Audio manbai — jonli ovoz birinchi, TTS zaxira

**Bu briefning asosiy qoidasi.**

So'z bizning listening materiallarimizda uchrasa — **audio o'sha yerdan kesiladi**, generatsiya qilinmaydi. Bizda word-level timestamp bor, ya'ni bu bepul.

Nega: talaba sintetik, izolyatsiya qilingan talaffuzni emas, **real nutqdagi so'zni** eshitadi. Imtihonda ham, hayotda ham so'z shunday keladi.

### Qaysi kesik tanlanadi

1. Talaba so'zni **listening materialidan** saqlagan bo'lsa — o'sha material
2. Aks holda — so'z uchragan har qanday material
3. **So'z segment boshida yoki oxirida bo'lsa, undan qochiladi** — kesilib qolish ehtimoli yuqori

### Kesik chegaralari

So'zning birinchi va oxirgi timestampidan **har ikki tomonga ~150 ms**. Chegaraga aniq kesilgan so'z sun'iy eshitiladi, chunki real nutqda tovushlar bir-biriga o'tib ketadi.

**Ikkinchi bosish — kontekst bilan:** o'sha so'z atrofidagi 3–4 so'z. Izolyatsiya qilingan so'z tushunarsiz bo'lganda kerak bo'ladi, va fonetik kontekst — bu aldov emas, real tinglash ko'nikmasi.

---

## 2. TTS generatsiyasi

Materialда uchramagan so'zlar uchun.

**Model: Kokoro-82M**, Apache-2.0, ~350MB. Ovoz: **`b` — britan ingliz**.

### Omograflar

`lead`, `record`, `present`, `close`, `live`, `wind`, `bow`, `tear` — turkumga qarab ikki xil talaffuz. Bizda har ma'noning turkumi bor.

Kokoro `misaki` G2P orqali **IPA kiritishni qabul qiladi** — `[word](/ipa/)` ko'rinishida. Omograf so'zlarga turkumga mos IPA berilsin, qolganlariga oddiy matn.

⚠️ Bu jimgina o'tib ketadigan nuqson turi: noto'g'ri talaffuz bilan generatsiya qilingan audio hech qanday xato bermaydi, shunchaki **talabaga noto'g'ri narsa o'rgatadi.**

### Qayerda ishlaydi

| | Qayerda | Nima |
|---|---|---|
| **Seed** | 3060 | Partiyalab, barcha so'zlar |
| **Produktsiya** | Backend CPU | Bittalab, async worker orqali |

Bitta so'z ≈ 1 soniya audio. CPU'da eng yomon holatda ~1 soniya hisob — async navbat uchun muammo emas.

**Bir xil model, bir xil ovoz, ikki joyda.** Ovoz mos kelmasligi darhol sezilади.

### Tartib

```
So'z audio talab qildi
  → material kesigi bormi? → bor: tayyor
  → R2'da hash bo'yicha bormi? → bor: tayyor
  → yo'q → navbatga → Kokoro → R2
```

R2 kaliti: `(matn, ovoz, model)` hashi. Bitta so'z butun tizimda bir marta generatsiya qilinadi.

### Hajm

Hozircha **faqat so'zlar** — ~0.75M belgi. Ta'riflar "On the go" qurilganda qo'shiladi.

---

## 3. `listen` mashqi

Eshit → yoz. **Passiv zinapoyaning oxiriga** qo'shiladi:

```
recognise → recall → listen
```

### Ekran

Ovoz tugmasi, yozish maydoni, boshqa hech narsa. **Yozilgan so'z ko'rinmaydi** — bu butun mashqning ma'nosi.

| Tugma | Amal |
|---|---|
| `Tab` yoki tugma | Qayta eshittirish |
| Ikkinchi bosish | Kontekst bilan (kesik bo'lsa) |
| `0.75×` | Sekinlashtirish |
| `Enter` | Tasdiqlash |

Avtomatik takrorlash yo'q — talaba o'zi bosadi.

### Baholash

`recall` bilan bir xil: aynan to'g'ri → `Good`, imlo xatosi (edit distance 1–2) → `Hard`, qolgani → `Again`.

### Audio yo'q bo'lsa

Karta **`recall` ga tushadi**, so'z o'tkazib yuborilmaydi. Chalg'ituvchi fallback bilan bir xil naqsh.

Generatsiya kutilayotgan bo'lsa ham shunday — talaba kutmaydi.

---

## 4. "On the go" rejimi

Ekransiz, qo'lsiz. Yo'lda, yurganda, idish yuvayotganda.

**Nomi:** `On the go`. `Blinkers` ishlatilmasin — ingliz tilida bu otning ko'z shori, audio rejimni umuman anglatmaydi. `Listen` ham ishlatilmasin — u mashq turi bilan to'qnashadi.

### Nima eshitiladi

```
inglizcha ta'rif  →  [pauza ~3 soniya]  →  so'z  →  keyingisi
```

**Hammasi inglizcha.** O'zbek TTS kerak emas — passiv yo'nalish qoidasi "savol inglizcha, javob inglizcha".

Pauza muhim: talaba shu paytda so'zni eslashga urinadi. Pauzasiz bu shunchaki o'qish bo'lib qoladi.

### Qaysi so'zlar

Aylanmadagi so'zlar (`learning` + `review`), eng yaqinda qo'shilgani birinchi. **Kunlik navbatdan mustaqil.**

### FSRS'ga ta'siri — yo'q

**Eshitish esga tushirish emas.** FSRS esga tushirishni modellashtiradi; eshitganni takrorlash deb yozsak, barqarorlik dalilsiz o'sadi va jadval yolg'on gapira boshlaydi.

Alohida ta'sirlanish logi yozilsin, jadvalga tegmasin.

### Boshqaruv

Ekran yo'q, ya'ni faqat quloqchin tugmalari: o'ynatish / to'xtatish / keyingisi / oldingisi. Media kalitlar ishlasin.

### Nima kerak bo'ladi

Ta'riflar uchun TTS — ~5M belgi. Bu rejim qurilganda generatsiya qilinadi, oldin emas.

---

## 5. Gapirib tekshirish (`speak`)

Ta'rif eshittiriladi, talaba **inglizcha so'zni ovoz chiqarib aytadi**, tizim tekshiradi.

### Brauzer qiladi — server yo'q

**Web Speech API** (`SpeechRecognition`). Telefon klaviaturasidagi diktovka bilan bir xil dvigatel.

```
lang = 'en-GB'
maxAlternatives = 5
```

Brauzer 5 ta variant qaytaradi. **Birortasi to'g'ri so'zga mos kelsa — qabul.**

Server yo'q, model yo'q, navbat yo'q, narx yo'q.

### Qabul qilish qoidasi

- 5 ta alternativdan birortasi mos kelsa → qabul
- O'zbek tiliga xos almashtirishlar hisobga olinsin: /θ/→/t,s/, /ð/→/d,z/, /w/→/v/, /æ/→/a/, so'z boshidagi undoshlar to'plamini unli bilan ajratish
- **Birinchi urinishda hech qachon "xato" chiqmasin** — *"I didn't catch that"*, 3 tagacha urinish
- Uchtasi ham o'tmasa: so'z va talaffuzi ko'rsatiladi, **xato deb yozilmaydi**, log'ga tushadi

### Talaffuz bahosi qo'yilmaydi

Ball yo'q, rang yo'q, fonema tahlili yo'q.

Sabab: so'z darajasidagi talaffuz bahosi hal qilinmagan masala — ochiq tadqiqotda inson bahosi bilan eng yaxshi korrelyatsiya **0.549**, Azure ham **>0.5** da'vo qiladi. Zaif signal uchun pul to'lash ma'nosiz, va noto'g'ri baho — noto'g'ri rad etishning yashirin ko'rinishi.

Mashq o'z qiymatini baribir beradi: **ma'nodan so'zni ovoz chiqarib eslash**.

### "I don't know"

Bitta tugma, halol yorliq. `Next` degan alohida tugma bo'lmasin — oqibatsiz o'tkazish qochish yo'liga aylanadi va jadvalni buzadi.

Bosilganda: `Again` → so'z ko'rsatiladi, talaffuzi eshittiriladi, keyingisiga o'tiladi.

### Ikki natijani aralashtirmang

| Holat | Natija |
|---|---|
| Talaba `I don't know` bosdi | `Again` — jadvalga yoziladi |
| STT 3 marta tanimadi | **Hech narsa yozilmaydi** — so'z navbatda qoladi, log'ga tushadi |

Ikkinchisi talabaning xatosi emas, bizniki. `Again` deb yozilsa — bu noto'g'ri rad etish, faqat yashirin ko'rinishda.

Interfeysda ham farq ko'rinsin: *"I didn't catch that"* — kulrang, neytral, qayta urinish tugmasi bilan. *"I don't know"* — talabaning o'z tanlovi, javob ochiladi.

### ⚠️ Real qurilmada sinang

iOS Safari'da `SpeechRecognition` qo'llab-quvvatlashi to'liq emas. Hujjatdagi "partial" nimani anglatishini **faqat haqiqiy iPhone** aytadi.

Ishlamasa: mashq ko'rsatilmaydi yoki yozish varianti taklif qilinadi. Sessiya buzilmaydi.

Grammatika (`SpeechGrammarList`) o'lgan — spetsifikatsiyada qolgan, lekin **hech qanday ta'sir qilmaydi**. Unga tayanmang.

---

## 6. Sozlamalar

- **Talaffuz** tugmasi endi ko'rinadi (2-bosqichgacha yashirin edi)
- `listen` va `speak` qo'lda tanlash ro'yxatiga qo'shiladi — lekin **pog'onani chetlab o'tmaydi**: faqat o'sha pog'onaga yetgan so'zlar. Bo'sh bo'lsa: *"No words are ready for this yet."*

---

## 7. Bu briefda QURILMAYDI

- **O'zbek TTS** — hech bir joyda kerak emas. Kerak bo'lganda Azure `uz-UZ` ~$22 ga qo'shiladi
- **Talaffuz bahosi** — yuqoridagi sabab
- Dictation moduli — alohida brief
- 4-bosqich (ikkinchi uchrashuv signali, tizim tavsiyalari)
- Foydalanuvchi o'z ro'yxatini yaratishi
