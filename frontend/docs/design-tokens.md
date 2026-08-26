# Dizayn tokenlari — spetsifikatsiya

> Manba: `frontend/docs/design-audit.md` (2026-08-21).
> Bu hujjat tuzilma va qoidalarni belgilaydi. Aniq hex qiymatlar mavjud tema
> qiymatlaridan hosil qilinadi — quyida har bir holat uchun formula berilgan.
>
> Joylashuvi: `frontend/docs/design-tokens.md`

---

## 0. Qabul qilingan qarorlar

| # | Qaror | Tanlov | Sabab |
|---|---|---|---|
| 1 | Tipografika | Tailwind subset g'olib | 3 ta tema faqat rangni o'zgartiradi, shriftni emas — semantik tip tokenlari hozir foyda bermaydi. Lint bilan mexanik bajariladi. |
| 2 | Sirt va alfa | Aralash | Takrorlanadigan rollarga nom, bir martalik holatlarga cheklangan alfa shkalasi. |
| 3 | Domen tokenlari | To'liq semantik qatlam | "To'g'ri javob" va "muvaffaqiyat toasti" bir kuni ajralishi mumkin; alias bepul. |

---

## 0.1 Dizayn printsiplari

Bular tokenlar ustidagi qatlam — token qiymatlari o'zgarganda ham qoladi.

**Zichlik.** Foydali maydondan maksimal foydalanish, shovqindan qochgan
holda. Spacing qadamlarini yaxlitlashda **kichik tomonga** yaxlitlanadi.
Katta bo'shliq faqat mazmunan ajratish kerak bo'lganda.

**Bosh harf.** Interfeys matni odatiy jumla yozuvida: `Public`, `Draft`,
`Processing`. Lowercase uslub qabul qilinmaydi.

*Istisno — eyebrow yorliqlari.* Bo'lim ustidagi mayda, katta harfli
yorliqlar (`--tracking-caps` bilan) alohida tipografik rol va ular
saqlanadi. Bosh harf qoidasi ularga tegmaydi. Farqi: eyebrow — bu
tuzilma belgisi, `Public` esa mazmun. Eyebrow uslubi faqat bo'lim
sarlavhalarida, hech qachon tugma, badge yoki holat belgisida emas.

**O'qilishi.** Shrift o'lchami hozirgidan kattaroq (§1.0). Zichlik bilan
zid emas — bo'shliq nazorat ostida bo'lsa, kattaroq shrift zichlikni buzmaydi.

**Klaviatura.** Asosiy printsip emas, lekin sifat poli: har bir interaktiv
element ko'rinadigan fokus holatiga ega bo'lishi shart.

---

## 0.2 Tailwind v4: joylashuv va nomlash

Tokenning qayerda yashashi tanlov emas — Tailwind namespace'lari belgilaydi.
1-bosqichda amalda tekshirilgan.

| Tur | Joyi | Sabab |
|---|---|---|
| Ranglar | xom token `:root` da, `@theme inline` faqat map qiladi | `@theme inline` `:root` ga hech narsa chiqarmaydi. Wavesurfer ranglarni `getPropertyValue()` bilan o'qiydi — faqat `@theme inline` da yashagan token bo'sh satr qaytaradi. |
| `--ease-*`, `--tracking-*` | `@theme` | Haqiqiy namespace — utility o'zi hosil bo'ladi. |
| `--duration-*`, `--z-*` | `:root` + qo'lda `@utility` | Namespace emas, `@theme` utility yaratmaydi. |

**Nomlash.** `--color-` — Tailwind namespace prefiksi, nomning qismi emas.

```css
/* :root */        --correct: var(--success);
/* @theme inline */ --color-correct: var(--correct);
/* utility */       text-correct  bg-correct  border-correct
```

`text-color-correct` chiqishi uchun token `--color-color-correct` bo'lishi
kerak edi. Shuning uchun xom tokenlar prefikssiz nomlanadi — mavjud
`--success` → `--color-success` naqshiga mos.

**Chegara tokenlari `--line-*` deb nomlanadi**, `--border-*` emas: aks holda
utility `border-border-subtle` bo'lib chiqadi. `--line-subtle` →
`border-line-subtle`, va bo'luvchi chiziqlarda `bg-line-subtle` sifatida ham
ishlatiladi.

**Docs skanerlanadi.** Tailwind `frontend/docs/*.md` ni ham o'qiydi — shu
faylning jadvallaridagi klass nomlari production CSS'ga tushdi. `@source not
"../docs"` bilan chiqarib tashlanadi. Bu muhim, chunki §6 dagi *taqiqlangan*
klasslar ham aks holda generatsiya qilinadi.

---

## 1. Tipografika

### 1.0 Shkala qiymatlarini ko'tarish

Hozirgi holat: `text-xs` 139 marta, `text-sm` 82, `text-base` atigi 21 —
ya'ni interfeysning asosiy o'lchami 12px. Savol o'qib javob yoziladigan
mahsulot uchun kichik.

Klasslarni ko'chirish o'rniga shkalaning o'zi ko'tariladi
(`globals.css` / Tailwind theme):

```css
--text-xs:   0.8125rem;  /* 12px → 13px */
--text-sm:   0.9375rem;  /* 14px → 15px */
--text-base: 1.0625rem;  /* 16px → 17px */
--text-lg:   1.1875rem;  /* 18px → 19px */
```

`text-2xl` va `text-4xl` tegilmaydi — ular allaqachon yetarlicha katta.

Bu 200+ klass o'zgarishini bir necha qatorga aylantiradi va qaytarish oson.
`/dev/ui` tayyor bo'lgach, alohida joylarni kerak bo'lsa qo'lda
aniqlashtiramiz.

### 1.1 Ruxsat etilgan o'lchamlar

Faqat oltita qadam. Boshqa hech qanday matn o'lchami ishlatilmaydi.

| Klass | Rol |
|---|---|
| `text-xs` | mayda yorliq, meta, badge, jadval izohi |
| `text-sm` | interfeys matni — sukut bo'yicha eng ko'p ishlatiladigan |
| `text-base` | o'qish uchun matn (savol matni, transkript, tavsif) |
| `text-lg` | bo'lim sarlavhasi, plitka sarlavhasi |
| `text-2xl` | sahifa sarlavhasi, KPI raqami |
| `text-4xl` | hero / natija balli |

**Taqiq:** `text-xl`, `text-3xl`, `text-5xl`, va barcha `text-[…]` arbitrary
qiymatlari.

### 1.2 Migratsiya jadvali

Semantik tokenlar (`text-h1`, `text-kpi`, `text-body`, `text-panel`,
`text-label`, `text-micro`, `text-tile`, `text-stat`) `globals.css:51-67`
dan **o'chiriladi**. Har birining hozirgi `font-size` va `font-weight`
qiymatini o'qib, quyidagicha almashtir:

- `font-size` → eng yaqin ruxsat etilgan qadam
- `font-weight` → alohida `font-*` klassi sifatida saqlanadi
- `letter-spacing` → agar 0 dan farq qilsa, alohida `tracking-*` klassi

Arbitrary o'lchamlar:

| Hozir | Ko'chiriladi |
|---|---|
| `text-[15px]` | `text-sm` |
| `text-[1.25rem]` | `text-lg` |
| `text-[11px]`, `text-[10px]`, `text-[9px]` | `text-xs` |
| `text-[0.8rem]` (`ui/button.tsx:27`) | `text-sm` |

`text-[9px]` va `text-[10px]` o'qish uchun juda mayda edi — `text-xs` ga
o'tish ularni kattalashtiradi va bu maqsadli o'zgarish, regressiya emas.

Standart qadamlar:

| Hozir | Ko'chiriladi |
|---|---|
| `text-xl` (2 ta) | `text-lg` |
| `text-3xl` (4 ta) | `text-2xl`, ballar uchun `text-4xl` |
| `text-5xl` (1 ta) | `text-4xl` |

### 1.3 Og'irlik, tracking, leading

**font-weight:** `font-normal`, `font-medium`, `font-semibold`, `font-bold`.
`font-bold` faqat raqamli ko'rsatkichlar uchun (ball, KPI).
Arbitrary `font-[NNN]` taqiqlanadi.

**tracking:** `tracking-normal`, `tracking-wide`, va bitta token:

```
--tracking-caps: 0.14em;   /* eyebrow yorliqlari — faqat uppercase bilan */
```

`tracking-[0.14em]` (4 ta hit) → `tracking-caps` utility'siga.
Bu token har doim `uppercase` va `text-xs` bilan birga ishlatiladi —
uchtasi bitta tipografik rolni tashkil qiladi (§0.1 eyebrow istisnosi).
`tracking-tight` taqiqlanadi.

**leading:** `leading-none`, `leading-tight`, `leading-normal`,
`leading-relaxed`. Raqamli variantlar (`leading-7`, `leading-8`) →
`leading-relaxed`. `leading-snug`, `leading-loose` taqiqlanadi.

---

## 2. Sirt, chegara, alfa

### 2.1 Nomlangan rollar

Bular `globals.css` da har bir tema uchun `color-mix()` orqali e'lon
qilinadi — shunda uchta temada qo'lda sozlash kerak bo'lmaydi va
tema qo'shilganda avtomatik ishlaydi.

```css
--surface-hover:  color-mix(in srgb, var(--foreground) 8%,  transparent);
--surface-sunken: color-mix(in srgb, var(--foreground) 4%,  transparent);
--line-subtle:    color-mix(in srgb, var(--foreground) 10%, transparent);
--line-strong:    color-mix(in srgb, var(--foreground) 25%, transparent);
```

Uchala temada o'lchandi — har biri o'z temasining `--foreground` sidan
hisoblanadi, bitta e'lon yetarli. To'rtinchi tema qo'shilsa tekin ishlaydi.

**Nima almashtiriladi:**

| Hozirgi naqsh | Soni | Yangi |
|---|---|---|
| `hover:bg-foreground/8` | 27 | `hover:bg-surface-hover` |
| `hover:bg-foreground/6` | 5 | `hover:bg-surface-hover` |
| `hover:bg-foreground/5` | 5 | `hover:bg-surface-hover` |
| `border-foreground/10` (studio karta) | — | `border-line-subtle` |
| `hover:border-foreground/30` (MCQ hover) | — | `border-line-strong` |

Ghost hover'ning uchta varianti bitta qiymatga keladi. Vizual farq
sezilmaydi (5% va 8% orasidagi farq amalda ko'rinmaydi), lekin drift
manbai yo'qoladi.

### 2.2 Cheklangan alfa shkalasi

Nomlangan rolga tushmaydigan holatlar uchun faqat oltita qadam:

```
/5   /10   /20   /40   /60   /80
```

Qolgan 19 ta qadam (`/4`, `/6`, `/7`, `/8`, `/9`, `/12`, `/14`, `/15`,
`/18`, `/25`, `/30`, `/35`, `/45`, `/50`, `/55`, `/70`, `/85`, `/90`, `/95`)
eng yaqin ruxsat etilgan qadamga yaxlitlanadi.

`opacity-*` uchun ham shu shkala: `opacity-40`, `opacity-45`, `opacity-50`
→ `opacity-40`.

### 2.3 Spacing

21 ta unikal qadam sakkiztaga qisqaradi:
`0`, `0.5`, `1`, `1.5`, `2`, `3`, `4`, `6`.

Yuqoridagi qadamlar (`8`, `10`, `12`, `14`, `16`, `20`, `24`, `52`) faqat
sahifa darajasidagi bo'shliqda qoladi va `PageContainer` ichida
markazlashtiriladi.

**Yaxlitlash yo'nalishi: kichik tomonga** (§0.1 zichlik printsipi).
`gap-5` → `gap-4`, `p-7` → `p-6`, `mt-3.5` → `mt-3`.

20 ta arbitrary qiymat (`w-[19rem]`, `h-[5.3rem]`, `size-[520px]` va h.k.)
eng yaqin standart qadamga o'tadi. Istisno: `calc()`, `min()`, `svh`
talab qiladiganlar — izoh bilan qoladi.

---

## 3. Domen tokenlari

12 ta token. Xom token `:root` da prefikssiz, `@theme inline` da
`--color-*` sifatida map qilinadi (§0.2).

| Token (`:root`) | Utility | Boshlang'ich qiymat | Ishlatilishi |
|---|---|---|---|
| `--correct` | `text-correct` | `var(--success)` | to'g'ri javob: form gap, MCQ, matching, natija |
| `--incorrect` | `text-incorrect` | `var(--destructive)` | xato javob |
| `--skipped` | `text-skipped` | ⚠ §8 ga qara | javobsiz qoldirilgan savol |
| `--caret` | `caret-caret` | `var(--primary)` | typing-target karetkasi |
| `--attention` | `text-attention` | `var(--warning)` | tugallanmagan part, publish taqiqlari |
| `--published` | `text-published` | `var(--success)` | material holati |
| `--draft` | `text-draft` | `var(--muted-foreground)` | material holati |
| `--stub` | `border-stub` | `color-mix(in srgb, var(--foreground) 15%, transparent)` | null-stub chegarasi, "SOON", bo'sh avatar |
| `--wave` | — (JS) | `var(--muted-foreground)` | waveform to'lqini |
| `--wave-progress` | — (JS) | `var(--primary)` | waveform progressi va kursori |
| `--region` | — (JS) | `color-mix(in srgb, var(--primary) 18%, transparent)` | segment regioni |
| `--audio-marker` | `bg-audio-marker` | `color-mix(in srgb, var(--foreground) 25%, transparent)` | take pleyerida part chegarasi |

`--wave*` va `--region` JS orqali o'qiladi, shuning uchun ular `:root` da
bo'lishi **shart** (§0.2).

### 3.1 Hal qilinadigan nomuvofiqliklar

**Karetka.** Hozir `caret-*` klassi hech qayerda ishlatilmagan — native
karetka matn rangini oladi. Bo'shliqni to'ldirayotgan foydalanuvchining
ko'zi aynan karetkada bo'ladi, shuning uchun uni matndan ajratish asosli:
`caret-[--color-caret]` form completion maydonlariga qo'shiladi.

*Agar karetka matn rangidan farq qilmasligi kerak deb qaror qilinsa, bu
token ro'yxatdan chiqariladi — qolgan hech narsa o'zgarmaydi.*

**Holat belgisi ikki lug'atda.** `StudioListeningListPage` `public`/`draft`/
`processing` deydi, `StudioDashboardPage` esa `Public`/`Private`.
Bitta lug'at qabul qilinadi: **`Public` / `Draft` / `Processing`**,
bosh harf bilan (§0.1), `--color-published` / `--color-draft` /
`--color-primary` ranglari bilan. Bitta `StatusPill` komponenti (§5).

`Private` atamasi ishlatilmaydi — `Draft` bilan bir xil holatni ikki nom
bilan ataydi.

Ranglar hozir faqat `/8` va `/5` alfa bilan farqlanadi — deyarli
ko'rinmaydi. Yangi tokenlar ularni haqiqatan ajratadi.

**"O'tkazib yuborilgan" holati.** Hozir faqat `italic`. `--color-skipped`
qo'shilgandan keyin ham `italic` qoladi — rang va uslub birga ishlaydi,
chunki faqat rang bilan ma'no berish accessibility talabiga zid.

**Waveform.** Wavesurfer CSS klass qabul qilmaydi, JS orqali
`getPropertyValue()` bilan o'qish qoladi. Lekin hex fallback'lar
(`#646669`, `#e2b714`) **olib tashlanadi** — token doim mavjud, fallback
faqat drift manbai. Tema o'zgarganda qayta o'qish mantiqi (`:765-767`,
`:818-820`) o'z joyida qoladi.

---

## 4. Motion, radius, z-index

### 4.1 Motion

```css
--duration-fast: 100ms;   /* rang o'zgarishi, hover */
--duration-base: 200ms;   /* sukut bo'yicha o'tish */
--duration-slow: 300ms;   /* panel ochilishi, layout siljishi */

--ease-out:    cubic-bezier(0, 0, 0.2, 1);
--ease-in-out: cubic-bezier(0.4, 0, 0.2, 1);
--ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);  /* faqat nishonlash/pop */
```

`duration-100/150/200/300` klasslari → uchta tokendan biriga
(`duration-150` → `--duration-base`).

Oltita mavjud `cubic-bezier()` uchtaga keladi. Istisno: `--ease-spring`
allaqachon `(0.34,1.56,0.64,1)` — o'zgarmaydi.

**22 ta `@keyframes` tegilmaydi** — ularning davomiyliklari (1.15s logo
chizilishi, 2.8s shooting star) animatsiyaga xos, o'tish tokeni emas.
Lekin ular ishlatadigan easing qiymatlari yuqoridagi uchtaga
xaritalanadi.

`transition-all` (5 ta hit) taqiqlanadi — aniq property ro'yxati yoziladi.

### 4.2 Radius

Beshta qadam: `rounded-sm`, `rounded-md`, `rounded-lg`, `rounded-xl`,
`rounded-full`.

| Hozir | Ko'chiriladi |
|---|---|
| bare `rounded` (34 ta) | `rounded-md` |
| `rounded-2xl` (3 ta) | `rounded-xl` |

Bare `rounded` `--radius` tokeniga bog'lanmagan — bu 34 ta joyda tema
radiusidan uzilgan degani. `ui/button.tsx` dagi `var(--radius-md)`
arbitrary qiymatlari (4 ta) `rounded-md` klassiga qaytariladi.

Yo'nalishli variantlar (`rounded-t-lg`, `rounded-b-xl`) shu beshtadan
hosil qilinadi.

### 4.3 z-index

Darajalar toza, faqat nomsiz. Nomlanadi:

```css
--z-raised:   10;   /* karta ichidagi ustki qatlam, dekorativ fon */
--z-sticky:   20;   /* sticky audio bandi, muharrir paneli */
--z-header:   30;   /* Layout / StudioLayout sarlavhasi */
--z-progress: 40;   /* route progress */
--z-overlay:  50;   /* dialog, dropdown, toast, connection gate */
--z-splash:  100;   /* splash screen */
```

Yangi daraja qo'shish taqiqlanadi. Arbitrary `z-[…]` taqiqlanadi.

---

## 5. Komponent primitivlari

Auditda topilgan takrorlanishlar — har biri komponentga aylantiriladi.

| Komponent | O'rnini bosadi | Hozirgi hajm |
|---|---|---|
| `Button` (mavjud, majburiy qilinadi) | xom `<button>` | 81 ta |
| `Card` (mavjud, majburiy qilinadi) | qo'lda `rounded-lg border border-border bg-card` | 11 ta |
| `GhostIconButton` | ghost hover idiomasi | 37 ta |
| `StatusPill` | ikki lug'atdagi holat belgisi | 2 ta ta'rif |
| `StickyAudioBar` | `sticky top-[3.75rem] z-20 …` | 4 ta |
| `PageContainer` | `mx-auto max-w-3xl` / `max-w-md` | 11 ta |

**Studio karta variantlari.** `StudioDashboardPage.tsx:41-44` dagi `glass`
va `deep` faqat `bg-card/60` vs `bg-card/90` bilan farq qiladi — ular
`Card` ning `variant` prop'iga o'tadi, alohida ta'rif sifatida qolmaydi.

**Avatar skeleton'i.** `Layout.tsx:80` dagi qo'lda yozilgan
`animate-pulse rounded-full bg-foreground/10` → `ui/skeleton.tsx`.

---

## 6. Taqiqlar ro'yxati (lint uchun)

Bular `reviewer` subagent uchun tekshiruv ro'yxati, imkon qadar
`eslint-plugin-tailwindcss` yoki oddiy regex qoidasi bilan avtomatlashtiriladi.

1. Klass satrida hex, `rgb()`, `rgba()`, `hsl()` — **taqiq**
   (istisno: `theme/themes.ts` preview swatch'lari, `lib/favicon.ts`)
2. Tailwind palitra klasslari (`text-gray-*`, `bg-zinc-*`, …) — **taqiq**
3. `text-[…]`, `p-[…]`, `gap-[…]`, `w-[…]`, `h-[…]` arbitrary qiymatlar — **taqiq**
   (istisno: `calc()`, `min()`, `svh` talab qiladigan holatlar — izoh bilan)
4. Ruxsat etilmagan matn o'lchamlari (`text-xl`, `text-3xl`, `text-5xl`) — **taqiq**
5. Ruxsat etilmagan alfa qadamlari — **taqiq**
6. `rounded` (bare), `rounded-2xl` — **taqiq**
7. `z-[…]` va ro'yxatdan tashqari `z-*` — **taqiq**
8. `transition-all` — **taqiq**
9. Sof `focus:` — **taqiq**, `focus-visible:` ishlatiladi
   (istisno: Radix `data-[highlighted]` ishlatadigan komponentlar)
10. Xom `<button>` — **taqiq**, `Button` yoki `GhostIconButton`
11. Interaktiv element `focus-visible` stilisiz — **taqiq**

---

## 7. Migratsiya tartibi

Har bosqich alohida commit, orasida vizual tekshiruv.

**0-bosqich.** ✅ MCQ/Matching fokus bug'i — bajarildi.

**1-bosqich.** ✅ Token e'lonlari (`cd97109`) + shrift shkalasi (`1b545be`).

**2-bosqich. Tipografika migratsiyasi.** §1.2 va §1.3 — semantik matn
tokenlarini o'chirish, arbitrary o'lchamlarni yig'ish, og'irlik/tracking/
leading qoidalari.

*Nega tartib o'zgardi:* 1-bosqich hisoboti `StudioDashboardPage` da 59 ta
semantik token va atigi 2 ta `text-xs` borligini ko'rsatdi — ya'ni yangi
shrift shkalasi u sahifaga hali yetib bormagan. Shu sabab:

- Shrift o'lchami qaroriga baho berib bo'lmaydi, chunki ilovaning katta
  qismi hali eski shkalada
- `text-[9/10/11px]` literal qiymatlar ko'tarilmadi, natijada nisbatlar
  buzildi (chip yorlig'i hisoblagichdan 1.30x katta bo'lib qoldi)
- Komponent primitivlarini yakuniy shkalada yozgan ma'qul, keyin qayta
  ishlagandan ko'ra

**3-bosqich. Sirt, alfa, motion, radius, z-index migratsiyasi.**
§2, §4 — mexanik almashtirishlar.

**4-bosqich. Komponent primitivlari.** §5. `GhostIconButton`, `StatusPill`,
`StickyAudioBar`, `PageContainer`; `Card` ga `variant` prop.

**5-bosqich. `/dev/ui` sahifasi.** Barcha tokenlar va komponentlar uchala
tema bo'ylab.

**6-bosqich. Qolgan fayllar.** Audit reytingi tartibida.
Birinchi oltilik: `StudioDashboardPage` (11) → `AudioEditorPane` (6) →
`ui/button` (6) → `Layout` (6) → `ListeningResultsPage` (5) →
`ListeningTakePage` (4).

**7-bosqich. Lint qoidalari.** §6 + `@source not "../docs"`.

**Alohida vazifalar** (bosqichlarga bog'liq emas):
- §8 kontrast tuzatishi
- Studio form-completion preview'da yorliq kesilishi (quyida)

### 7.1 Ma'lum muammo: studio preview yorliqlari

1-bosqich B commitidan keyin form-completion preview'da kesilgan yorliqlar
4 tadan 6 taga chiqdi (256px ustundagi `<input>`, o'ralmaydi). Faqat
muallif tomonida — o'quvchi sahifasida bu yorliqlar oddiy matn va toza
o'raladi.

Bu token muammosi emas, layout muammosi: sobit 256px ustun.
`minmax()` bilan moslashuvchan qilinadi yoki o'raladigan maydonga
o'tkaziladi. 6-bosqichda `FormBuilder` navbatiga kelganda hal qilinadi.

**Tor ekran tekshirilmagan** — 1-bosqichda viewport 1440px da qotib qoldi.
Mobil kenglikda shrift shkalasi 5-bosqichdagi `/dev/ui` orqali tekshiriladi.

---

## 8. Kontrast tekshiruvi (1-bosqich bilan birga)

Auditda o'lchanmagan, lekin tekshirilishi shart:

- Har bir tema uchun `--muted-foreground` fonda 4.5:1 beradimi
  (serika-dark'da `#646669` / `#323437` ≈ 2.8:1 — **yiqiladi**)
- `--line-strong` UI elementi sifatida 3:1
- `--published` / `--draft` badge fonida

**`--skipped` alohida holat.** U hozir `--muted-foreground` ga alias, ya'ni
o'sha 2.8:1 muammosini meros oladi. Lekin `--skipped` matn rangi sifatida
ishlatiladi — 4.5:1 talab qilinadi. Ikki yo'l:

- `--muted-foreground` ning o'zi tuzatiladi (260 ta ishlatilish bir yo'la
  hal bo'ladi), `--skipped` alias bo'lib qoladi
- `--skipped` alias bo'lishdan chiqadi va o'z, kontrastdan o'tadigan
  qiymatini oladi

Birinchisi afzal: `--muted-foreground` eng ko'p ishlatiladigan matn rangi
va u hozir o'qish uchun qiyin. Uni tuzatish "polished" hissiga
tokenlardan ko'ra ko'proq ta'sir qiladi.

Yiqilgan qiymatlar tuzatiladi. Bu did masalasi emas, o'lchanadigan raqam.
