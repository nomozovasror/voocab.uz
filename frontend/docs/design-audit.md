# Frontend dizayn auditi

> **Yo'l haqida eslatma.** Topshiriqda `apps/web/docs/design-audit.md` ko'rsatilgan
> edi; bu repoda `apps/` yo'q — frontend `frontend/` da joylashgan, shuning uchun
> hisobot `frontend/docs/design-audit.md` ga yozildi.
>
> Qamrov: `frontend/src/**` — 116 ta `.ts` / `.tsx` / `.css` fayl.
> Sana: 2026-08-21. Faqat o'qish; hech qanday kod o'zgartirilmadi.

---

## 1. Qisqacha xulosa

Rang bo'yicha drift deyarli yo'q: klass satrlarida **bitta ham** Tailwind palitra
klassi (`text-gray-400` kabi) va **bitta ham** arbitrary hex (`[#e2b714]`) topilmadi.
Barcha rang tokenlar orqali beriladi. Haqiqiy drift boshqa joyda:

1. **Ikkita parallel tipografika shkalasi.** Loyihaning o'z semantik tokenlari
   (`text-h1`, `text-body`, `text-micro`, …) 8 ta va 47 marta ishlatilgan;
   Tailwind'ning standart shkalasi (`text-xs`…`text-5xl`) 9 ta va **278 marta**.
   Ya'ni semantik shkala e'lon qilingan, lekin kodning asosiy qismi undan
   foydalanmaydi.
2. **Alfa qadamlari — rangning yashirin drifti.** 25 ta turli shaffoflik darajasi
   (`/4`, `/5`, `/6`, `/7`, `/8`, `/9`, `/10`, `/12`, `/14`, `/15`, `/18`…).
   `hover:bg-foreground/5`, `/6` va `/8` bir xil "ghost hover" uchun uchta variant.
3. **MCQ va matching variantlarida fokus ko'rsatkichi umuman yo'q.** `<input>`
   `sr-only`, ko'rinadigan `<label>` da esa `peer-focus-visible:` yoki
   `has-[:focus-visible]:` stili yozilmagan — klaviatura bilan javob berayotgan
   o'quvchi qayerda turganini ko'rmaydi. Bu take sahifasining o'zagida.
4. **81 ta xom `<button>` va 30 ta `<Button>`.** `ui/button.tsx` mavjud, lekin uni
   atigi 13 ta fayl import qiladi; listening va studio yuzalari deyarli butunlay
   qo'lda yozilgan. `ui/card.tsx` ham xuddi shunday — 4 ta faylda ishlatilgan,
   `rounded-lg border border-border bg-card` esa 11 marta qo'lda takrorlangan.
5. **Domenga xos holatlar semantik tokensiz.** To'g'ri/xato javob `success` va
   `destructive` ustiga qurilgan, "o'tkazib yuborilgan" holati esa faqat
   `italic` bilan ajratiladi; audio waveform ranglari JS'da o'qiladi va hex
   fallback'ga ega.

---

## 2. Raqamlar

| O'lchov | Qiymat |
|---|---|
| Klass satrlarida arbitrary hex rang | **0** |
| Tailwind palitra klasslari (`gray-400` va h.k.) | **0** |
| Hex literal (barchasi token fallback / tema preview) | 12 ta hit, 6 ta faylda |
| Unikal rang tokeni (`--color-*`) | 24 |
| Unikal alfa qadami | **25** |
| Unikal matn o'lchami (token + Tailwind + arbitrary) | 8 + 9 + 6 = **23** |
| Arbitrary matn o'lchami | 6 ta qiymat, 12 ta hit |
| Unikal standart spacing qadami | **21** |
| Unikal arbitrary spacing/o'lcham qiymati | **20** (31 ta hit) |
| Jami arbitrary Tailwind utility (`.tsx`) | 76 ta hit, **49 ta unikal** |
| Unikal `rounded-*` variant | 11 |
| Unikal `z-index` daraja | 6 (10, 20, 30, 40, 50, 100) |
| `@keyframes` | 22 |
| Xom `<button>` / `<Button>` | 81 / 30 |
| Arbitrary utility saqlaydigan fayllar | **30** |

---

## 3. Inventarlar

### 3a. Ranglar

**Hex literallar** — barchasi `getPropertyValue()` fallback'i yoki tema preview
swatch'i, ya'ni stil emas:

| Qiymat | Joy | Konteksti |
|---|---|---|
| `#323437` `#e2b714` `#d1d0c5` | `theme/themes.ts:27` | serika-dark preview |
| `#e1e1e3` `#e2b714` `#2c2e31` | `theme/themes.ts:33` | serika-light preview |
| `#282a36` `#bd93f9` `#f8f8f2` | `theme/themes.ts:39` | dracula preview |
| `#2c2e31` `#e2b714` | `lib/favicon.ts:15-16` | `--card` / `--primary` fallback |
| `#646669` `#e2b714` | `features/listening/components/AudioEditorPane.tsx:194,198,199` | waveform fallback |
| `#888` | `components/studio/PublishCelebration.tsx:93` | konfetti fallback |
| `#161618` | `components/ShootingStars.tsx:14,18` | faqat izohda |
| `#2c2e31` | `components/ui/skeleton.tsx:8` | faqat izohda |

`rgba()` — 3 ta hit, hammasi `ShootingStars.tsx:160,178,179`, canvas gradienti
uchun (CSS emas).

**Yaqin ranglar guruhi.** Bir-biriga yaqin, alohida yozilgan juftliklar:
`#646669` (AudioEditorPane fallback) va `#6b6e74` (globals.css'dagi
serika-light `--muted-foreground`) — bitta rol, ikki qiymat;
`#e2b714` / `#e0a83c` / `#d99a2b` — primary va uning ikki tema varianti;
`#5fb87a` / `#4caf72` / `#50fa7b` — success uch temada.

**Alfa qadamlari** (`token/NN`) — chastota bo'yicha:

| Qadam | Soni | | Qadam | Soni |
|---|---|---|---|---|
| /10 | 42 | | /30 | 11 |
| /8 | 36 | | /20 | 11 |
| /50 | 29 | | /70 | 10 |
| /15 | 20 | | /6 | 9 |
| /60 | 18 | | /80 | 7 |
| /40 | 17 | | /14 | 6 |
| /5 | 14 | | /90 | 6 |
| /12 | 8 | | /25, /45, /7 | 2 har biri |
| | | | /4, /9, /18, /35, /55, /85, /95 | 1 har biri |

**Eng ko'p ishlatilgan rang klasslari:** `text-muted*` 260, `text-foreground` 177,
`border-border` 100, `text-primary` 89, `text-destructive` 45, `bg-foreground/8` 35,
`ring-ring` 34, `border-primary` 32, `bg-card` 29, `text-success` 20, `text-warning` 16.

**`var(--…)` arbitrary qiymatlar ichida** — 12 ta hit:
`components/layout/Layout.tsx:89` (2×`var(--primary)` soyada),
`components/ui/button.tsx:16,26,27,31,33`, `components/ui/magic-bento.tsx:177`,
`features/listening/components/TakeAudio.tsx:339` (`var(--primary)` + `var(--foreground)`
progress gradientida), `features/listening/components/AudioEditorPane.tsx:102`
(`color-mix(in srgb, var(--primary) 18%, transparent)`).

### 3b. Tipografika

**Arbitrary o'lchamlar** — 6 ta qiymat, 12 ta hit:

| Qiymat | Soni | Fayllar |
|---|---|---|
| `text-[11px]` | 6 | `StudioListeningListPage.tsx:166,177`, `FormCompletionGroup.tsx:201`, `ChoiceGroup.tsx:192`, `QuestionPaper.tsx:87`, `MatchingGroup.tsx:72` |
| `text-[10px]` | 2 | `PublishBar.tsx:99`, `QuestionPaper.tsx:165` |
| `text-[9px]` | 1 | `AudioEditorPane.tsx:2407` |
| `text-[15px]` | 1 | `AudioEditorPane.tsx:1958` |
| `text-[1.25rem]` | 1 | `StudioDashboardPage.tsx:387` |
| `text-[0.8rem]` | 1 | `components/ui/button.tsx:27` |

**Ikkita shkala yonma-yon:**

| Loyiha tokeni | Soni | | Tailwind standart | Soni |
|---|---|---|---|---|
| `text-micro` | 15 | | `text-xs` | 139 |
| `text-kpi` | 7 | | `text-sm` | 82 |
| `text-body` | 7 | | `text-base` | 21 |
| `text-panel` | 5 | | `text-lg` | 12 |
| `text-label` | 5 | | `text-2xl` | 11 |
| `text-h1` | 5 | | `text-3xl` | 4 |
| `text-tile` | 4 | | `text-4xl` | 3 |
| `text-stat` | 4 | | `text-xl` | 2 |
| **Jami 47** | | | `text-5xl` | 1 |
| | | | **Jami 275** | |

**font-family:** `font-mono` 34, `font-sans` 3. `.tsx` da bitta ham `font-family`
e'loni yo'q; barchasi `globals.css` dagi `--font-sans` / `--font-mono` orqali.

**font-weight:** `font-semibold` 46, `font-medium` 37, `font-normal` 5, `font-bold` 5.
Arbitrary `font-[NNN]` yo'q; `globals.css:51-67` da 5 ta `font-weight` matn
tokenlari ta'rifi ichida.

**tracking:** `tracking-wide` 9, `tracking-[0.14em]` **4**, `tracking-tight` 2,
`tracking-normal` 2.

**leading:** `leading-relaxed` 9, `leading-none` 5, `leading-7` 4, `leading-8` 3,
`leading-tight` / `leading-snug` / `leading-loose` 1 har biri.

### 3c. Spacing va o'lcham

**Standart qadamlar** (`p|m|gap|space`), chastota bo'yicha:

| Qadam | Soni | Qadam | Soni | Qadam | Soni |
|---|---|---|---|---|---|
| 2 | 156 | 4 | 76 | 8 | 11 |
| 1 | 130 | 0.5 | 70 | 7 | 9 |
| 1.5 | 126 | 2.5 | 49 | 0 | 8 |
| 3 | 102 | 5 | 19 | 16 | 7 |
| | | 6 | 37 | 10, 12, 14, 20, 24, 52, 3.5, 9 | ≤6 har biri |

21 ta unikal qadam.

**Arbitrary qiymatlar** — 20 ta unikal, 31 ta hit:

| Qiymat | Soni | Asosiy joyi |
|---|---|---|
| `top-[3.75rem]` | 4 | Take/Results sticky audio bandi |
| `h-[0.9em]` | 3 | skeleton matn paneli |
| `h-[0.85em]` | 3 | skeleton sarlavha paneli |
| `h-[0.8em]` | 3 | skeleton qator paneli |
| `max-w-[1500px]` | 2 | `StudioLayout.tsx` |
| `h-[2.65rem]` | 2 | `StudioDashboardPage.tsx` |
| `w-[19rem]`, `size-[520px]`, `size-[5.3rem]`, `mt-[2.65rem]`, `min-w-[96px]`, `min-h-[65svh]`, `max-w-[calc(100%-2rem)]`, `max-w-[85rem]`, `max-w-[75rem]`, `max-w-[56.25rem]`, `h-[min(58vh,540px)]`, `h-[5.5rem]`, `h-[5.3rem]`, `h-[3px]` | 1 har biri | — |

Fayllar bo'yicha: `StudioDashboardPage.tsx` 7, `ListeningTakePage.tsx` 4,
`ListeningResultsPage.tsx` 4, `ListeningPage.tsx` 2, `AudioEditorPane.tsx` 2,
`StudioLayout.tsx` 2, qolgan 10 ta faylda 1 tadan.

### 3d. Radius, soya, chegara

| `rounded-*` | Soni |
|---|---|
| `rounded-md` | 78 |
| `rounded-full` | 49 |
| `rounded-lg` | 41 |
| `rounded` (bare) | **34** |
| `rounded-xl` | 7 |
| `rounded-b-xl` | 3 |
| `rounded-2xl` | 3 |
| `rounded-t-xl` | 2 |
| `rounded-t-lg` | 2 |
| `rounded-sm` | 2 |
| `rounded-b-lg` | 1 |

11 ta variant. Bare `rounded` (34 ta) `--radius` tokeniga bog'lanmagan —
`rounded-sm/md/lg/xl` esa `globals.css:40-43` dagi `--radius` dan hosil qilinadi.

**Soyalar:** `shadow-lg` 7, `shadow-sm` 5, `shadow-md` 1, `shadow-2xl` 1.
Qo'lda yozilgan: `shadow-[0_0_24px_-6px_var(--primary)]` va
`shadow-[0_0_28px_-4px_var(--primary)]` — ikkalasi ham `components/layout/Layout.tsx:89`;
`globals.css:309` da bitta `box-shadow` e'loni (`magic-*`).

**Chegara kengliklari:** deyarli faqat standart 1px. Istisnolar:
`border-l-2` (`ListeningResultsPage.tsx`, transkript chizig'i), `border-t-0`, `border-0`.

### 3e. Animatsiya

**Klasslar:** `transition-colors` 103, `transition-opacity` 20, `transition` 10,
`transition-all` 5, `transition-none` 2, `transition-shadow` 1, plus 4 ta
arbitrary property ro'yxati (`transition-[width,left]`, `transition-[max-width]`,
`transition-[opacity,translate,border-color,color]`,
`transition-[background-color,border-color,box-shadow,backdrop-filter]`).

**Duration:** `duration-300` 9, `duration-200` 7, `duration-150` 4, `duration-100` 3.
`globals.css` da 15 ta turli davomiylik: `1.15s`×4, `0.2s`×3, `2.8s`×2, `2.2s`×2,
`0.3s`×2, `0.01s`×2, va `3s`, `10s`, `1.9s`, `0.9s`, `0.6s`, `0.5s`, `0.42s`,
`0.32s`, `0.24s` bittadan.

**Easing:** `ease-out` 19, `ease-in` 8, plus 6 ta turli `cubic-bezier()`:
`(0.22,1,0.36,1)`×2, `(0.65,0,0.35,1)`, `(0.4,0,1,1)`, `(0.34,1.56,0.64,1)`,
`(0.2,0.9,0.3,1.3)`, `(0,0.7,0.2,1)`.

**22 ta `@keyframes`** (`globals.css`): `celebrate`, `line-flash`, `loader-appear`,
`logo-draw-fill`, `logo-draw-line`, `logo-key`, `logo-sdraw`, `logo-sfill`,
`logo-shine`, `logo-wipe`, `magic-particle`, `magic-ripple`, `modal-item-in`,
`route-progress`, `setup-fade-in`, `setup-lift-out`, `setup-rise`, `setup-settle`,
`tr-fade-in`, `tr-pop`, `tr-rise`, `tr-wave`.

### 3f. z-index

| Daraja | Soni | Joylari |
|---|---|---|
| `z-10` | 11 | `ShootingStars`, `magic-bento`, `AudioEditorPane:1494`, `FormHelpCard:61`, `HomePage:75,77`, `StudioDashboardPage:134,138,141,154,376` |
| `z-20` | 7 | `AudioEditorPane:1472,1496,1508`, `ListeningResultsPage:130,323`, `ListeningTakePage:301,438` |
| `z-30` | 3 | `Layout.tsx:35`, `StudioLayout.tsx:48`, `FormBuilder.tsx:1451` |
| `z-40` | 1 | `route-progress.tsx:36` |
| `z-50` | 6 | `dialog.tsx:40,62`, `dropdown-menu.tsx:44,245`, `toaster.tsx:112`, `ConnectionGateScreen.tsx:21` |
| `z-100` | 1 | `SplashScreen.tsx:48` |

CSS'da bitta ham `z-index` e'loni yo'q. Arbitrary `z-[…]` ham yo'q.
Darajalar hujjatlashtirilmagan — `route-progress.tsx:33-35` dagi izoh yagona
yozma tartib ta'rifi.

---

## 4. Domenga xos vizual holatlar

### 4.1 Form completion bo'shlig'i (gap)

`features/listening/components/FormCompletionGroup.tsx`, take va review sahifalarida.

| Holat | Hozirgi stil | Manba |
|---|---|---|
| bo'sh / to'ldirilgan | `border-border bg-background text-foreground` | :147 |
| fokusda | `focus-visible:ring-2 focus-visible:ring-ring` | :147 |
| to'g'ri | `border-success text-success` | :102 |
| xato | `border-destructive text-destructive` | :103 |
| qabul qilingan javob izohi | `text-xs text-muted-foreground` | :158 |
| o'tkazib yuborilgan | **alohida stil yo'q** — natijada `text-muted-foreground italic` (`ListeningResultsPage.tsx:252`) |

Sariq caret **yo'q** — caret native, `caret-*` klassi hech qayerda ishlatilmagan.

**Token bahosi:** to'g'ri/xato uchun mavjud `success` / `destructive` yetarli.
O'tkazib yuborilgan holat hozir faqat `italic` bilan farqlanadi va rang tokeni
yo'q — `--color-skipped` (yoki `muted-foreground` ni rasmiylashtirish) talab qiladi.
Caret uchun `--color-caret` hozircha ishlatilmaydi.

### 4.2 MCQ varianti

`features/listening/components/ChoiceGroup.tsx:159-200`.

| Holat | Stil |
|---|---|
| tanlanmagan | `border-border text-foreground` |
| hover | `hover:border-foreground/30` |
| tanlangan (baholashgacha) | `border-primary bg-primary/10 text-foreground` |
| to'g'ri (baholashdan keyin) | `border-success bg-success/10 text-success` |
| xato tanlov | `border-destructive bg-destructive/10 text-destructive` |
| "spent" (limit to'lgan, tanlanmagan) | `opacity-45 hover:border-border` |
| **focus-visible** | **yo'q** — `<input className="sr-only">` (:187), `<label>` da fokus stili yozilmagan |

**Token bahosi:** mavjud `primary` / `success` / `destructive` yetarli.
"spent" holati semantik emas, faqat `opacity-45` — token talab qilmaydi, lekin
qiymat hech qayerda takrorlanmaydi.

### 4.3 Matching varianti

`features/listening/components/MatchingGroup.tsx:159-164` — MCQ bilan bir xil
to'rt holat, bir xil klass satrlari. Fokus stili shu yerda ham **yo'q** (:175 `sr-only`).

### 4.4 Audio pleyer (take)

`features/listening/components/TakeAudio.tsx`.

| Element | Stil |
|---|---|
| play/pause tugmasi | `bg-primary text-primary-foreground rounded-full size-9` |
| qoida taqiqlagan holat | `pointer-events-none opacity-40` (:252) |
| progress trek | `linear-gradient(var(--primary) … color-mix(--foreground 15%))` (:339) |
| thumb | `bg-primary`, `size-3` |
| seek taqiqlangan | thumb `opacity-0`, `cursor-default` |
| part chegarasi belgisi | `bg-foreground/25`, `h-2 w-px` (:313) |

**Token bahosi:** part chegarasi belgisi hozir `foreground/25` — semantik emas.
`--color-audio-marker` nomzod. Progress uchun `primary` yetarli.

### 4.5 Audio muharriri waveform (studio)

`features/listening/components/AudioEditorPane.tsx`.

| Element | Qiymat | Manba |
|---|---|---|
| wave | `--muted-foreground`, fallback `#646669` | :198 |
| progress / cursor | `--primary`, fallback `#e2b714` | :199 |
| region (segment) | `color-mix(in srgb, var(--primary) 18%, transparent)` | :102 |
| tema o'zgarganda | JS qayta o'qiydi (:765-767, :818-820) | |

**Token bahosi:** wavesurfer CSS klass qabul qilmaydi, shuning uchun JS orqali
o'qish majburiy. Hozir uchta rol (wave / progress / region) umumiy tokenlarga
xaritalanган — `--color-wave`, `--color-wave-progress`, `--color-region`
alohida token bo'lsa, tema muallifi waveform'ni matn rangidan mustaqil sozlay oladi.

### 4.6 Diktant diff

**Mavjud emas.** `features/dictation` o'chirilgan (39-commit),
`features/typing-rescue/TypingRescue.tsx` esa boshqa mexanika — unda `"wrong"`
faqat ovoz effekti uchun (:108-109), vizual diff yo'q.

### 4.7 Studio statistika kartalari

`pages/studio/StudioDashboardPage.tsx`.

| Holat | Stil | Manba |
|---|---|---|
| haqiqiy qiymat | `text-foreground` | :83 |
| null-stub (`DASH` = `—`) | `text-muted-foreground` | :83, `DASH` :46 |
| hali qurilmagan plitka ("SOON") | `border-dashed border-foreground/15`, `opacity-50` | :171, :175 |
| bo'sh avatar/badge doirasi | `border-dashed border-foreground/18 bg-foreground/7` | :454 |
| kartaning pastki chegarasi | `border-dashed border-foreground/12` | :463 |

**Token bahosi:** "ma'lumot manbai hali yo'q" holati uchta turli alfa bilan
(`/15`, `/18`, `/12`) va `DASH` konstantasi bilan ifodalanadi.
`--color-stub` (yoki `--color-placeholder-border`) bitta qiymatga keltiradi.

### 4.8 Material holati belgisi

`pages/studio/listening/StudioListeningListPage.tsx:83-96`.

| Holat | Stil |
|---|---|
| `processing` (ASR ketyapti) | `bg-primary/15 text-primary` |
| `public` | `bg-foreground/8 text-foreground/80` |
| `draft` | `bg-foreground/5 text-muted-foreground` |

**Token bahosi:** `public` va `draft` faqat ikkita yaqin alfa (`/8` va `/5`) bilan
farqlanadi — bu semantik farq emas, deyarli ko'rinmas. `--color-published` /
`--color-draft` nomzod. `processing` uchun `primary` mos.

Eslatma: dashboard'dagi recent-work qatorida boshqa lug'at ishlatiladi —
`text-success` / `text-muted-foreground` va `Public` / `Private` yozuvlari
(`StudioDashboardPage.tsx:246-249`), ya'ni bir tushuncha ikki joyda ikki xil.

### 4.9 Natija / ball ko'rsatkichlari

| Element | Stil | Manba |
|---|---|---|
| ball raqami | `font-mono text-3xl font-bold text-primary tabular-nums` | `ListeningResultsPage.tsx:118` |
| maxraj va foiz | `text-muted-foreground` | :120-122 |
| to'g'ri belgi | `bg-success/15 text-success` | :237 |
| xato belgi | `bg-destructive/15 text-destructive` | :238 |
| javobsiz | `text-muted-foreground italic` | :252 |
| katalogdagi ball | `text-primary` + `text-muted-foreground` maxraj | `ListeningPage.tsx:157-160` |
| katalogdagi "bajarilgan" doira | `border-primary/40 bg-primary/10 text-primary` | :121 |
| part chip: tugallanmagan | `text-warning` | `QuestionPaper.tsx:165` |
| part chip: tugallangan | `opacity-40` | :165 |

**Token bahosi:** mavjud tokenlar qoplaydi. `text-warning` faqat shu bitta
joyda va `PublishBar` da ishlatiladi (16 ta hit) — semantik roli
"tugallanmagan / e'tibor talab qiladi", nomi esa umumiy.

---

## 5. Komponent holatlari matritsasi

`ui/` papkasidan tashqaridagi komponentlar. `✓` = kodda mavjud, `—` = topilmadi,
`n/a` = bu komponent uchun ma'nosiz.

| Komponent | default | hover | focus-visible | active | disabled | loading | error | empty |
|---|---|---|---|---|---|---|---|---|
| `ChoiceGroup` | ✓ | ✓ | **—** | — | ✓ | n/a | ✓ | — |
| `MatchingGroup` | ✓ | ✓ | **—** | — | ✓ | n/a | ✓ | — |
| `FormCompletionGroup` | ✓ | ✓ | ✓ | — | ✓ | n/a | ✓ | — |
| `QuestionPaper` | ✓ | ✓ | **—** | ✓ | ✓ | n/a | — | — |
| `TakeAudio` | ✓ | ✓ | ✓ | — | ✓ | — | ✓ | n/a |
| `PaperSkeleton` | ✓ | n/a | n/a | n/a | n/a | ✓ | n/a | n/a |
| `TaskPicture` | ✓ | — | — | — | — | — | — | — |
| `GroupPicture` | ✓ | ✓ | **—** | — | ✓ | ✓ | ✓ | ✓ |
| `MediaDropzone` | ✓ | — | **—** | — | ✓ | ✓ | — | ✓ |
| `AudioEditorPane` | ✓ | ✓ | ✓ | — | ✓ | ✓ | ✓ | ✓ |
| `FormBuilder` | ✓ | ✓ | ✓ | ✓ | ✓ | — | ✓ | ✓ |
| `ValueField` | ✓ | — | **—** | — | — | — | ✓ | ✓ |
| `ChoiceBuilder` | ✓ | ✓ | ✓ | — | — | — | ✓ | ✓ |
| `MatchingBuilder` | ✓ | ✓ | ✓ | — | — | — | ✓ | ✓ |
| `OptionsBox` | ✓ | ✓ | ✓ | — | — | — | ✓ | ✓ |
| `QuestionFormEditor` | ✓ | ✓ | ✓ | — | ✓ | — | ✓ | ✓ |
| `GroupHeader` | ✓ | ✓ | ✓ | — | ✓ | — | ✓ | ✓ |
| `GroupTypeChooser` | ✓ | ✓ | ✓ | — | ✓ | — | ✓ | ✓ |
| `QuestionTypeChoices` | ✓ | ✓ | ✓ | — | — | — | — | — |
| `PartsPicker` | ✓ | ✓ | ✓ | — | — | — | — | ✓ |
| `BuilderTools` | ✓ | ✓ | ✓ | — | — | — | — | ✓ |
| `FormHelpCard` | ✓ | ✓ | **—** | — | — | — | ✓ | ✓ |
| `FormLayout` | ✓ | — | — | — | — | — | — | ✓ |
| `PublishBar` | ✓ | — | **—** | — | ✓ | ✓ | — | ✓ |
| `PublishControl` | ✓ | — | **—** | — | ✓ | ✓ | ✓ | — |
| `PublishCelebration` | ✓ | ✓ | **—** | — | — | — | — | ✓ |
| `DeleteMaterialDialog` | ✓ | — | — | — | ✓ | ✓ | ✓ | ✓ |
| `StudioLayout` | ✓ | ✓ | ✓ | — | — | ✓ | — | ✓ |
| `breadcrumbs` | ✓ | ✓ | ✓ | — | — | — | — | ✓ |
| `Layout` | ✓ | ✓ | ✓ | — | — | ✓ | — | ✓ |
| `UserMenu` | ✓ | ✓ | ✓ | — | — | — | ✓ | — |
| `RouteProgress` | ✓ | n/a | n/a | n/a | n/a | ✓ | n/a | n/a |
| `ConnectionGateScreen` | ✓ | ✓ | ✓ | — | — | — | ✓ | ✓ |
| `TypingRescue` | ✓ | ✓ | ✓ | — | — | — | ✓ | ✓ |
| `ThemeSwitcher` | ✓ | (ui/Button) | (ui/Button) | — | — | — | — | n/a |
| `Logo` / `UserAvatar` / `ShootingStars` | ✓ | — | — | — | — | — | — | — |
| `PagePlaceholder` | ✓ | — | — | — | — | — | — | n/a |
| **Sahifalar** | | | | | | | | |
| `ListeningPage` | ✓ | ✓ | **—** | — | — | ✓ | ✓ | ✓ |
| `ListeningTakePage` | ✓ | ✓ | **—** | — | ✓ | ✓ | ✓ | ✓ |
| `ListeningResultsPage` | ✓ | ✓ | **—** | — | ✓ | ✓ | ✓ | ✓ |
| `StudioListeningListPage` | ✓ | ✓ | ✓ | — | — | ✓ | ✓ | ✓ |
| `StudioListeningEditorPage` | ✓ | ✓ | ✓ | — | ✓ | ✓ | ✓ | ✓ |
| `StudioDashboardPage` | ✓ | ✓ | ✓ | — | ✓ | ✓ | ✓ | ✓ |
| `HomePage` | ✓ | ✓ | **—** | — | — | — | ✓ | — |
| `NotFoundPage` | ✓ | ✓ | **—** | — | — | — | n/a | n/a |
| `LoginPage` | ✓ | (ui/Button) | (ui/Button) | — | — | ✓ | ✓ | n/a |
| `ProfilePage` | ✓ | — | — | — | — | — | — | — |
| `Reading` / `Vocabulary` / `Dictation` | ✓ | — | — | — | — | — | — | n/a |

### Aniqlangan bo'shliqlar

**focus-visible yo'q, lekin element interaktiv** (13 ta):
`ChoiceGroup`, `MatchingGroup`, `QuestionPaper` (part chiplari va "play this part"),
`GroupPicture`, `MediaDropzone`, `ValueField`, `FormHelpCard`, `PublishBar`,
`PublishControl`, `PublishCelebration`, `ListeningPage`, `ListeningTakePage`,
`ListeningResultsPage`, `HomePage`, `NotFoundPage`.
Ulardan **eng jiddiylari** `ChoiceGroup` va `MatchingGroup`: fokus `sr-only`
`<input>` ga tushadi va ko'rinadigan `<label>` da hech qanday
`peer-focus-visible:` / `has-[:focus-visible]:` qoidasi yo'q.

**`focus:` va `focus-visible:` aralashmasi.** `focus-visible:` — 143 ta hit.
Sof `focus:` — 37 ta hit, **9 ta faylda** (qator soni bilan):
`FormBuilder.tsx` 5, `ui/dropdown-menu.tsx` 4, `AudioEditorPane.tsx` 3,
`MatchingBuilder.tsx` 2, `ChoiceBuilder.tsx` 2, `StudioListeningEditorPage.tsx` 1,
`ValueField.tsx` 1, `OptionsBox.tsx` 1, `UserMenu.tsx` 1.

`ui/dropdown-menu.tsx` va `UserMenu.tsx` da bu Radix konvensiyasi — fokus
dasturiy ko'chiriladi, shuning uchun `focus:` to'g'ri. Qolgan 7 ta fayl
muharrir yuzasiga tegishli va ikkala variantni aralashtirib ishlatadi
(masalan `StudioListeningEditorPage.tsx:2428` da `focus:border-ring
focus:outline-none`, o'sha faylning boshqa joyida esa `focus-visible:`).

**empty state yo'q ro'yxat/jadval komponentlari:**
`FormLayout` (bo'sh shablon uchun holat yo'q — `parseTemplateLayout` bo'sh
massiv qaytarsa hech narsa chizilmaydi), `ChoiceGroup` / `MatchingGroup`
(savolsiz guruh — publishing taqiqlaydi, lekin UI holati yo'q).

**loading state yo'q async amallar:**
`TakeAudio` — audio metadata yuklanayotganda holat yo'q (faqat `onError` bor,
:216); `ValueField` — autosave ketayotganini bildirmaydi;
`QuestionPaper` — n/a (ota sahifa qamraydi).

**error state yo'q:** `TaskPicture` (rasm yuklanmasa — `onError` yo'q),
`MediaDropzone` (xato `GroupPicture` ga uzatiladi, o'zida ko'rsatilmaydi),
`PublishBar` (xato `StudioListeningEditorPage` da).

**active state:** butun kodda atigi 2 ta joyda (`FormBuilder`, `QuestionPaper`) —
`active:` klassi deyarli ishlatilmaydi.

---

## 6. Takrorlanish

### 6.1 Xom `<button>` vs `ui/button.tsx`

81 ta xom `<button>`, 30 ta `<Button>`. `ui/button.tsx` ni atigi 13 ta fayl
import qiladi: `LoginPage`, `ProfilePage`, `StudioListeningListPage`, `HomePage`,
`ThemeSwitcher`, `DeleteMaterialDialog`, `ConnectionGateScreen`,
`PublishCelebration`, `PublishControl`, `ui/dialog`, `TypingRescue`,
`ui/toaster`, `PublishBar`.

`features/listening/components/**` va take/results sahifalari **butunlay** xom
`<button>` ishlatadi.

### 6.2 "Ghost icon button" idiomasi — 3 xil alfa bilan 37 marta

Bir xil vizual rol (matn rangidagi tugma, hover'da yengil fon), uchta variant:

| Variant | Soni |
|---|---|
| `hover:bg-foreground/8 hover:text-foreground` | 27 |
| `hover:bg-foreground/6 …` | 5 |
| `hover:bg-foreground/5 …` | 5 |

### 6.3 Karta idiomasi

`rounded-lg border border-border bg-card` — **11 marta** qo'lda yozilgan
(`TakeAudio`, `PaperSkeleton`, `ListeningResultsPage`, `ListeningPage`,
`GroupPicture` va h.k.), holbuki `ui/card.tsx` mavjud va faqat 4 ta faylda
ishlatiladi (`LoginPage`, `ProfilePage`, `HomePage`, `PagePlaceholder`) —
ya'ni Card faqat eski/placeholder sahifalarda qolgan.

Studio'da yana ikkita alohida karta ta'rifi bor:
`glass` va `deep` (`StudioDashboardPage.tsx:41-44`), ikkalasi ham
`magic-card relative flex flex-col rounded-xl border border-foreground/10
shadow-lg backdrop-blur-md backdrop-saturate-150`, farqi faqat
`bg-card/60` vs `bg-card/90`.

### 6.4 Sticky audio bandi — 4 marta

`sticky top-[3.75rem] z-20 -mx-1 bg-background/90 px-1 py-2 backdrop-blur-md`
to'liq holda 4 marta yozilgan: `ListeningTakePage.tsx:301,438` va
`ListeningResultsPage.tsx:130,323` (har bir faylda haqiqiy va skeleton nusxasi).

### 6.5 Sahifa konteyneri

`mx-auto max-w-3xl` — 8 marta, `mx-auto max-w-md` — 3 marta. Umumiy layout
komponenti yo'q.

### 6.6 Holat belgisi (status pill) ikki lug'atda

`StudioListeningListPage.tsx:83-96` → `public` / `draft` / `processing`,
kichik harf, `rounded-full px-2.5 py-0.5 text-xs`.
`StudioDashboardPage.tsx:246-249` → `Public` / `Private`, bosh harf,
`font-bold tracking-wide uppercase text-micro`.
Bir tushuncha, ikki nom va ikki stil.

### 6.7 Skeleton panellari

`ui/skeleton.tsx` yaratilgandan keyin (38-commit) `RowSkeleton`
(`StudioListeningListPage.tsx:194`) primitivга o'tkazildi, lekin
`components/layout/Layout.tsx:80` dagi avatar placeholder hamon qo'lda:
`size-7 animate-pulse rounded-full bg-foreground/10`.

---

## 7. `ui/` papkasi (shadcn generatsiyasi) — alohida

10 ta fayl. Ulardan 4 tasi shadcn'dan kelgan (`button`, `card`, `dialog`,
`dropdown-menu`), 6 tasi loyihada yozilgan (`logo-loader`, `magic-bento`,
`route-progress`, `skeleton`, `spinner`, `toaster`).

| Fayl | focus-visible | hover | disabled | arbitrary utility |
|---|---|---|---|---|
| `button.tsx` | 2 | 6 | 1 | 6 (`text-[0.8rem]`, 4×`var(--radius-md)`) |
| `card.tsx` | 0 | 0 | 0 | 2 |
| `dialog.tsx` | 0 | 1 | 0 | 2 |
| `dropdown-menu.tsx` | 0 | 0 | 3 | 1 |
| `logo-loader.tsx` | 0 | 0 | 0 | 1 (`min-h-[65svh]`) |
| `magic-bento.tsx` | 0 | 0 | 0 | 1 |
| `route-progress.tsx` | 0 | 0 | 0 | 0 |
| `skeleton.tsx` | 0 | 0 | 0 | 1 |
| `spinner.tsx` | 0 | 0 | 0 | 0 |
| `toaster.tsx` | 1 | 1 | 0 | 0 |

`dialog.tsx` va `dropdown-menu.tsx` da `focus-visible:` yo'q — ular Radix'ning
`data-[highlighted]` / `data-[state]` atributlariga tayanadi.

`button.tsx` `var(--radius-md)` ni arbitrary qiymat sifatida 4 marta ishlatadi
(:26,27,31,33) — `rounded-md` klassi o'rniga.

---

## 8. Migratsiya murakkabligi bo'yicha fayllar reytingi

Tartib: arbitrary Tailwind utility soni (asosiy), keyin arbitrary matn
o'lchami va qo'lda yozilgan idiomalar.

| # | Fayl | Arbitrary utility | Qo'shimcha |
|---|---|---|---|
| 1 | `pages/studio/StudioDashboardPage.tsx` | 11 | `text-[1.25rem]`, `glass`/`deep` karta ta'riflari, `DASH` stub'lari, 5×`z-10`, 3 xil `border-dashed` alfasi |
| 2 | `features/listening/components/AudioEditorPane.tsx` | 6 | `text-[15px]`, `text-[9px]`, 2 ta hex fallback, `color-mix` region rangi, 3×`z-20` |
| 3 | `components/ui/button.tsx` | 6 | `text-[0.8rem]`, 4×`var(--radius-md)` |
| 4 | `components/layout/Layout.tsx` | 6 | 2 ta qo'lda `shadow-[…]`, avatar skeleton'i qo'lda |
| 5 | `pages/listening/ListeningResultsPage.tsx` | 5 | 2× sticky band takrori, 3 ta skeleton `h-[0.Xem]` |
| 6 | `pages/listening/ListeningTakePage.tsx` | 4 | 2× sticky band takrori, focus-visible yo'q |
| 7 | `pages/studio/listening/StudioListeningListPage.tsx` | 3 | 2×`text-[11px]`, status pill lug'ati |
| 8 | `features/listening/components/QuestionPaper.tsx` | 3 | `text-[11px]`, `text-[10px]`, focus-visible yo'q |
| 9 | `pages/studio/listening/StudioListeningEditorPage.tsx` | 2 | 2850 qator; 25 ta error, 76 ta empty hit |
| 10 | `features/listening/components/ChoiceGroup.tsx` | 2 | `text-[11px]`, **focus-visible yo'q** |
| 11 | `features/listening/components/ChoiceBuilder.tsx` | 2 | — |
| 12 | `pages/listening/ListeningPage.tsx` | 2 | focus-visible yo'q |
| 13 | `features/typing-rescue/TypingRescue.tsx` | 2 | 4 ta `tr-*` keyframe inline `style` orqali |
| 14 | `features/listening/components/PaperSkeleton.tsx` | 2 | `h-[0.9em]`, `h-6` trek balandligi |
| 15 | `components/ui/dialog.tsx` | 2 | focus-visible yo'q |
| 16 | `components/ui/card.tsx` | 2 | 4 ta faylda ishlatiladi |
| 17 | `components/studio/StudioLayout.tsx` | 2 | 2×`max-w-[1500px]` |
| 18 | `components/studio/PublishCelebration.tsx` | 2 | `#888` fallback |
| 19–30 | `NotFoundPage`, `QuestionFormEditor`, `PublishBar`, `MatchingGroupEditor`, `MatchingGroup`, `GroupPicture`, `FormHelpCard`, `FormCompletionGroup`, `ui/skeleton`, `ui/magic-bento`, `ui/logo-loader`, `ui/dropdown-menu` | 1 har biri | `MatchingGroup` va `GroupPicture` da focus-visible yo'q |

**Arbitrary utility yo'q, lekin migratsiya tegadigan fayllar:**
`theme/themes.ts` (9 ta hex preview), `lib/favicon.ts` (2 ta hex fallback),
`components/ShootingStars.tsx` (3 ta `rgba()`), `styles/globals.css`
(24 rang tokeni × 3 tema, 8 matn tokeni, 22 keyframe, 15 davomiylik qiymati).

**Jami migratsiya talab qiladigan fayl: 30 ta** (arbitrary utility saqlaydiganlar)
**+ 4 ta** (hex/rgba saqlaydiganlar) **+ 1 ta** (`globals.css`) = **35**.
