# The listening feature — invariants

## The take screen is one scroll and one strip

`pages/listening/ListeningTakePage.tsx` is the page a learner works in; its
shape is taken from computer-delivered IELTS rather than invented.

- **No tabs per part.** In the real test parts are separated by pauses in the
  recording, not by screens. Here they are section headings in one continuous
  scroll — the point of practising is going back over what you missed, and a
  tab makes that a navigation.
- **The strip along the bottom is the navigation** (`QuestionNav.tsx`): every
  question at once, answered green, current ringed, flagged dotted. Fixed,
  never sticky — a forty-question paper is four screens long and a submit
  button at the bottom of it is a button nobody finds.
- **One button per NUMBER, not per question.** A "choose TWO letters" is two
  boxes carrying two marks; with one letter picked the first is answered and
  the second is not — the same arithmetic `answeredIn` gives the header.
- **The button is called `Check answers`**, and the name lives in
  `TakeConfig` (`submitLabel`). Practice is somewhere you check and then go
  back and work; "Submit" and "Finish" promise a door closing, which is the
  exam's promise and not this page's.
- **The paper is walked once**, in `take-paper.ts`. Header count, navigator
  and submit all read that walk — three walks are three chances to contradict
  each other about what question 24 is.
- **Where the reader is comes from the DOM**, via `data-q-anchor`
  (`take-focus.ts`) — never a register of refs threaded up out of three group
  components, which would be wrong the first time somebody wrote a fourth.
- **Tab moves between questions, not between fields**, which is what the real
  test does. Intercepted only in the MIDDLE of the paper: Tab off the last
  question and Shift+Tab off the first are let through, or the paper is a
  trap with the navigator outside it.
- Flags are part of the **draft**, not the submit — a note somebody made to
  themselves about a paper in progress.
- **Every control is drawn only if its rule permits it.** The exam page is
  this engine with a different `TakeConfig`; no rule is written into a button.

## A finished paper has a way back into its review

`GET /materials/{id}/take` carries `last_attempt` — the caller's most recent
SUBMITTED attempt, or nothing — and the take screen turns it into one row
above the player: *You have sat this · 7 / 10 · 2 weeks ago · See what you
got wrong*.

The only route to a review used to be through a fresh attempt, which is
exactly what somebody coming back to study their mistakes does not want:
**sitting it again writes a second attempt, and every ability figure on the
platform counts first attempts.** Going back to analyse what you got wrong
would quietly have cost you the measurement of it.

- **Most recent, not best or first.** "What happened last time" is the
  question a page asks when somebody opens a material they have done.
- **An id and a score, never the record.** The whole attempt is one fetch
  away at `/api/attempts/{id}`; putting it in the take payload would mean the
  take payload carrying the answer key, which §3.4 forbids outright.
- The whole row is the link. A line of facts with a "review" beside it is two
  things to aim at where there is one thing to do.

## The recording is state, and the picture is derived

`use-audio-engine.ts` owns the `<audio>` element — made with `new Audio()`
and never mounted, so no view can be the one that must stay rendered.

**A clip stops on the audio's clock, never on a timer.** `playRange` used to
arm a `setTimeout` for the clip's duration; the timer started when the call
was made, while the sound started whenever the browser had finished seeking
and buffering — on a six-minute file, not the same moment. The whole gap came
off the END, so the further into a recording an answer was, the more of its
last word went missing. `stopAtMs` is a position now, read on `timeupdate`
(~4×/s, so it can overshoot slightly). That is the right direction to be
wrong in: a moment of the next sentence is nothing, half the answer is the
bug. It is also rate-independent by construction.

### One player, and it travels

Scrolled past, it shrinks into a strip in the header under its own
`position: sticky`. Nothing is re-parented and nothing is duplicated: a copy
appearing where another disappears is a cut, and a cut reads as two players
swapping. So every difference between the two sizes is a NUMBER on the same
element (`BIG` and `DOCK` in `TakeAudio.tsx`) and every number is
transitioned.

- **The two states are different arrangements, so every piece has a
  coordinate in both.** Everything inside the card is absolutely positioned:
  full size the recording is across the top with its parts under it and the
  controls below; docked it is one row — transport, waveform, clock, speed.
  Pieces genuinely change places, and the only way for that to be a MOVEMENT
  rather than one layout dissolving into another is for each to travel
  between two numbers. Coordinates are given from whichever edge does not
  depend on the card's width; the clock, which crosses from one side to the
  other, is placed with a `calc()` off the far edge.
- **The waveform never changes parent.** It rides up out of its own row on a
  negative margin until it sits on the line above — identical-looking to
  moving, and a real movement rather than a dissolve. Its docked padding is
  computed from the control widths beside it, which is why those widths are
  fixed numbers rather than whatever the text comes out as.
- **The geometry is written down, not measured.** Measuring means reading
  boxes that are themselves mid-transition.
- **Two beats, not one.** First what has no smaller version goes (part
  labels, forward-3s, total duration); then the box collapses and the
  waveform slides up. Reversed coming back out. Both at once read as a fold.
  **The two beats overlap** — run strictly in sequence the player sat still
  for a sixth of a second mid-movement.
- **The card is out of the flow, and that is what makes it smooth.** Height
  and width are layout properties: animating them in the flow re-lays-out
  everything after it sixty times a second, and after this comes a
  forty-question paper. So the component is two boxes — an outer shell
  holding a constant `PLAYER_H` (it is what sticks), and the card absolutely
  positioned inside it. Constant outer height is a constant document, so the
  paper below cannot slide.
- **The morph eases in and out**, because it starts from rest; `ease-out`
  alone leaves at full speed from a standing start, which reads as a flinch.
  The fading group keeps `ease-out` — opacity has no momentum.
- **Docked, it is the one piece of glass in the header.** That only means
  anything because `HeaderGround` holds a window open behind it — frosted
  glass over an opaque colour is an opaque colour. `useDockOpening` gives the
  ground that window on the same clock as the width it is making room for.
- **The shrunken player keeps its waveform** — somebody four screens down can
  still see how much recording is left. The part labels go: a name over a
  strip eighty pixels wide names nothing.
- **Whatever can stay still, stays still.** The speed group never moves, and
  the bars are memoised on a string rather than an array, so playback does
  not re-render a hundred nodes four times a second.

### The waveform

- **Coloured to the playhead**, and this was got wrong once. It coloured what
  had actually been HEARD, on the argument that filling to the playhead
  claims somebody who dragged to the end had listened to all of it — true,
  and beside the point. Nudge forward three seconds and the bars you passed
  stayed grey; click back and the ones ahead stayed lit. Both correct under
  "heard", both read as the picture being broken. A coloured bar in a player
  means position. The spans are still collected — they go to the server after
  grading, where they can be read carefully rather than glanced at.
- **The bars are elements, not an SVG.** They were an SVG on the theory that
  two `<path>` nodes beat a hundred boxes while the player animates — the
  wrong problem, since the expensive reflow was the document's and is fixed
  by the card being out of the flow. And it cost round ends:
  `preserveAspectRatio="none"` scales x and y differently, so a corner radius
  comes out an ellipse. Widths are percentages so the count never changes as
  the player shrinks.
- **Count, thickness and height are one decision, in a narrow window**
  (`BARS`, `BAR`, `AMP` in `Waveform.tsx`). Two hundred hair-thin bars is a
  wall; sixty fat ones with gaps as wide again is a bar chart; bars edge to
  edge is a hedge. What reads as a recording is a slim rounded bar, a
  slightly tighter gap, and a fifth of the row left as air.
- **The contrast is exaggerated** (`CONTRAST` in `use-waveform.ts`). Speech
  sits in a narrow band, so a normalised recording draws as a flat fence;
  raising each value to a power above one holds the peaks and pulls the rest
  down, turning the fence back into sentences and breaths. A lie about the
  amplitude and an honest picture of the structure — nothing measures
  anything off it. Silence is a short stub rather than nothing, so a pause
  reads as a pause and not a rendering fault.
- **Peaks are decoded in the browser** (`use-waveform.ts`), from the same URL
  the element streams. Two requests for one file on purpose: decoding from a
  single fetch means the whole recording must arrive before anything can
  play. A failed decode is swallowed and the waveform rests flat — which is
  also what happens when the audio is on a bucket with no CORS. When peaks
  come down with the material, this hook keeps its signature and stops
  fetching.
- Runs are **reported one at a time and never merged** — the same stretch
  played twice is two spans, and that repetition is the whole signal. `heard`
  merges only for the picture.

### Controls

- **Play is in the middle** — the arrangement every music player has, because
  it is the one a hand reaches into without looking. Which is why the control
  row is a grid: with a clock on one side and switches on the other, a flex
  row would put play wherever the difference between them landed.
- **The parts are named under the waveform, each over the middle of its own
  stretch**, and each is a button. A label at the boundary belongs to
  whichever side you look at first. Nothing is drawn for a single-part
  material, and nothing unless the author marked EVERY boundary — a name over
  the wrong stretch is worse than none, because a learner uses it to decide
  where to listen. **With nothing to name the card is shorter by exactly what
  the strip would have taken.**
- **Skip-silence replaced Loop, and it asks to be used.** A listening paper
  is largely dead air — the twenty and thirty second stretches where a
  candidate reads ahead — and on a second pass that is time spent watching a
  playhead. Nobody goes looking for a control to fix that, so the switch
  catches the light a few seconds before the quiet arrives (`.shine` in
  `globals.css`) and **stays lit for the whole of it**: going dark the moment
  the silence started took the light off the control at the one moment it had
  a job. The gloss crosses twice and stops — a sweep still going thirty
  seconds later has stopped being an offer and become a thing on the screen
  that moves. What stays is the accent on the type.
  - **The button is an ACTION; skipping every silence is a SETTING.**
    Pressing it steps over the silence happening or about to; it does not put
    the player into a mode. "Skip all of them" lives in
    `PREFERENCES.skipSilence` (default off) rather than as a second control
    on a player that is already full.
  - Silences come out of the same decode as the peaks (`use-waveform.ts`) — a
    second decode would double the only expensive thing on the page.
  - `MIN_SILENCE_MS` is five seconds and that constant IS the feature. Speech
    is full of pauses; skipping those turns a recording into a stutter.
  - A skip lands slightly BEFORE the sound comes back, which keeps the first
    syllable and puts the playhead outside the window that triggers a skip —
    that is what stops the automatic one firing again on the next tick.
  - `engine.skippable` is the single source of both the light and the press,
    so the button can never light up for something a press would not reach —
    and it is genuinely `disabled` between times, because a control that
    answers a press by doing nothing is worse than one that says it cannot.
  - It is the control that survives into the shrunken player, and the speed
    is the one that goes: skipping dead air is what a learner reaches for
    WHILE working, and the speed is set once at the top and left alone.

## A collection's cover is derived, never uploaded

`cover.ts` turns one string into a stock colour and a printed pattern. Nobody
uploads anything, and the same collection is the same book on every device —
which is why a shelf of them is scannable: the reader finds the course they
were working through by recognising it.

**That string is `coverKeyOf(collection)`, never a bare id.** It is the id
until the author asks for a different book, and then it is `cover_seed` — a
column on `collections`, null for everything that existed before it, so no
cover has ever changed by itself. Anywhere still hashing `collection.id`
directly draws the book the author rejected, which is why `CollectionCover`
takes a `coverKey` and not an `id`. The seed is on the LEARNER's read too:
a re-roll only the studio could see would be two different books with one
name.

- **The palette is deliberately outside the token system**, and is the one
  place in the app that is. These are not interface colours — nothing about
  them means anything — and a cover that changed with the theme would stop
  being the same book. A small closed set, not free hex, so the shelf stays
  coherent however many collections there are.
- Type on a cover is white with fixed alpha, applied inline rather than in a
  class string, because the stock underneath is always dark whatever the
  theme is doing.
- Stock, pattern and cut come from **three different parts of the hash**, so
  11 × 8 × 3 really is 264 covers and not eleven with decoration.
- A `variant` moves an anchor, a spacing or an angle — it never adds a shape.
  That is what lets the count multiply without multiplying the number of ways
  a cover can come out wrong.
- A hash, not `collections.length % 7`: an index re-covers every book on the
  shelf the day somebody publishes another one.
- **Re-rolling is a deliberate act, not a preference.** The studio's `↻
  Cover` writes a new seed and the book changes everywhere at once. What it
  does not do is change on its own — the guarantee was never "this cover is
  permanent", it was "nothing but its author moves it".
- When uploads arrive, generation stays the default. A shelf where some books
  have art and the rest have a grey rectangle looks broken.

**Progress bars are green, never the accent.** Yellow means "this is the
action" everywhere here, and a progress bar is a report.
