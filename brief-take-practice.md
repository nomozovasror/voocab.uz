# Take sahifasi — listening practice

Talaba listening materialini ishlaydigan sahifa. Hozir mavjud, lekin shunchaki qurilgan — qayta ishlanadi.

Bu brief **practice mode**ni quradi. Exam mode va natija sahifasi keyin qo'shiladi, lekin ular oson ulanishi uchun bu brief ularga joy tashlaydi (pastda "Kelajakka tayyorgarlik" bo'limi).

---

## Rejim tushunchasi

Take sahifasi = **practice**. Rejim tanlash so'ralmaydi, toggle yo'q, ogohlantirish dialogi yo'q. Talaba materialni ochadi va ishlaydi.

Exam alohida sahifa bo'ladi (keyin quriladi) — talaba u yerga o'zi boradi va material tanlaydi, shu bilan exam qoidalariga rozi bo'lgan hisoblanadi.

**Muhim arxitektura talabi:** take komponentlari qoidalarni **tashqaridan** olsin, ichiga qattiq yozilmasin. Ya'ni "audio boshqaruvi bormi", "qayta eshitish mumkinmi", "timer ko'rinadimi" — bular prop/config orqali kelsin. Shunda exam sahifasi va keyinchalik IELTS uslubidagi skin bir xil komponentlarni qayta ishlatadi, uchta alohida ekran qurilmaydi.

---

## Practice qoidalari

- Audio erkin boshqariladi: play/pause, seek, orqaga/oldinga, tezlik
- Cheklovsiz qayta eshitish
- Vaqt cheklovi yo'q, countdown ko'rsatilmaydi
- Javoblar oxirida bir marta topshiriladi (har savolni alohida tekshirish yo'q)
- Talaba istagan tartibda javob beradi, savollar orasida erkin harakatlanadi

---

## Sahifa tuzilishi

Studio editoridagi ikki panelli tuzilish emas — bu talaba ekrani, e'tibor savollarga qaratilgan.

**Yuqorida:** material nomi, part ko'rsatkichi, javob berilgan savollar soni ("3 of 10 answered"). Chiqish yo'li (orqaga).

**Audio bloki:** ekranning yuqori qismida, scroll qilinganda ham ko'rinib turadi (sticky). Ichida: play/pause, progress bar (bosilib seek qilinadi), joriy vaqt / umumiy vaqt, −3s / +3s, tezlik tanlovi.

**Savollar:** instructions matni, keyin savol guruhlari ketma-ket. Har guruh o'z instruksiyasi bilan. Form completion — shablon input'lar bilan; MCQ — savol + variantlar (radio yoki checkbox, guruh turiga qarab).

**Pastda:** submit tugmasi. Javob berilmagan savollar bo'lsa tasdiqlash so'raladi ("3 savol javobsiz — baribir topshirasizmi?").

---

## Javob kiritish

- Form completion bo'shliqlari — gap-input komponenti (Studio editoridagi bilan bir xil uslub)
- MCQ — variantlar bosiladi, tanlangan holat aniq ko'rinadi
- `tab` bilan savollar orasida harakat, `space` play/pause (matn maydonida fokus bo'lmaganda)
- Javoblar mahalliy holatda saqlanadi, sahifa yangilansa yo'qolmasin (localStorage yoki server-side draft)

**Xavfsizlik:** to'g'ri javoblar mijozga yuborilmaydi. `take` endpointi faqat savol matni va variantlarni qaytaradi. Grading server tomonda, submit'dan keyin.

---

## Timing eventlari (hozirdan yozilsin)

Statistika va difficulty hisoblash uchun kerak. Keyin qo'shilsa eski attempt'larda ma'lumot bo'lmaydi, shuning uchun **hozirdan** yig'iladi:

- Har savolga qancha vaqt sarflandi (fokus vaqti)
- Butun materialga qancha vaqt ketdi
- Audio necha marta qayta eshitildi, qaysi qismlar takrorlandi
- Sessiya boshlangan va topshirilgan vaqt

Bular `QuestionAttempt` va `Attempt` yozuvlariga qo'shiladi. Talabaga ko'rsatilmaydi (practice'da timer yo'q), faqat fonda yig'iladi.

---

## Submit oqimi

1. Talaba submit bosadi
2. Server javoblarni baholaydi, `Attempt` va `QuestionAttempt` yozuvlarini saqlaydi
3. Server javobi **to'liq natijani** qaytaradi: har savol uchun to'g'ri/xato, to'g'ri javob(lar), va o'sha javob audioda qayerda aytilganini ko'rsatuvchi transkript segmenti (`start_ms`, `end_ms`, matn)
4. Talaba natija sahifasiga o'tadi

**Muhim:** server javobi to'liq bo'lsin, garchi natija sahifasi hozir minimal bo'lsa ham. Natija sahifasi qurilganda backend qayta yozilmasin.

---

## Kelajakka tayyorgarlik (joy tashlash)

Bu brief quyidagilarni **qurmaydi**, lekin ularni oson qo'shish uchun joy qoldiradi:

**Natija sahifasi** — route mavjud bo'lsin (`/take/:attemptId/results` kabi), hozircha minimal: score va savollar ro'yxati to'g'ri/xato belgisi bilan. Server allaqachon to'liq ma'lumot qaytaradi (to'g'ri javoblar, transkript segmentlari), keyin shu ma'lumot ustiga to'liq review ekrani quriladi — har savol uchun to'g'ri javob, transkriptdagi joyi, va o'sha qismni qayta eshittirish.

**Exam mode** — komponentlar config orqali qoidalarni olsin:
- `allowSeek` — orqaga qaytarish mumkinmi
- `allowPause` — pauza mumkinmi
- `allowReplay` — qayta eshitish mumkinmi
- `showTimer` — countdown ko'rinadimi

Practice'da hammasi erkin. Exam sahifasi shu komponentlarni boshqa config bilan chaqiradi.

**Exam sessiyasi** (keyin) server tomonda kuzatiladi — talaba sahifani yangilab audioni qaytadan boshlay olmasligi uchun. Hozir practice'da bu shart emas, lekin `Attempt` modelida sessiya holati uchun joy bo'lsin.

---

## Holatlar

- **Yuklanmoqda:** skeleton, layout siljimasin
- **Audio yuklanmadi:** aniq xabar + qayta urinish
- **Transkript hali tayyor emas:** practice'da muammo emas, savollar baribir ishlaydi (transkript faqat natija sahifasida kerak)
- **Javob berilmagan savollar bilan submit:** tasdiqlash so'raladi
- **Tarmoq uzilishi submit paytida:** javoblar yo'qolmasin, qayta urinish imkoni

---

## Dizayn

Mavjud Serika Dark tokenlari va Monkeytype uslubi — Studio ekranlaridagi bilan bir xil til. Flat sirtlar, mono tipografiya, sariq faqat active/focus va submit tugmasida, lowercase, keng bo'shliq.

Talaba ekrani bo'lgani uchun chrome minimal bo'lsin — e'tibor audio va savollarda. Studio'dagi asboblar zichligi bu yerda kerak emas.
