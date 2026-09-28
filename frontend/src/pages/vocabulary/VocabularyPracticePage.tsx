import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { toast } from "@/lib/toast";
import { getErrorMessage } from "@/lib/api";
import { localTimeZone, timeUntil } from "@/lib/time";
import { GapField } from "@/features/paper/components/GapField";
import { CefrTag } from "@/features/vocabulary/components/CefrTag";
import { ReportTranslation } from "@/features/vocabulary/components/ReportTranslation";
import { meanings } from "@/features/vocabulary/meaning";
import { pickJoke, type SessionStats } from "@/features/vocabulary/jokes";
import { practiceSummaryKey, vocabularyApi } from "@/features/vocabulary/api";
import { LEECH_LABEL, STATUS_CHIP_LABEL } from "@/features/vocabulary/status";
import type {
  Direction,
  ExerciseType,
  LeechChoice,
  PracticeAnswer,
  PracticeChoicePrompt,
  PracticeItem,
  PracticeLeechContext,
  PracticeOption,
  PracticeProducePrompt,
} from "@/features/vocabulary/types";

/** A queue entry, plus the one fact the server never sends and the client
 *  alone knows: whether this is the SAME item come back after an Again. Set
 *  the moment `advance` pushes it onto the queue's end, and echoed in
 *  `requeued` on the answer that follows — never on an item's first
 *  appearance (the spec's §1: that answer counts normally, the demotion is
 *  felt next time). */
type QueueItem = PracticeItem & { requeued?: boolean };

/** One answered turn, kept for the end screen's stats and joke. A word
 *  answered twice in one session (it came back after an Again) appears here
 *  twice — `sessionStats` below is what collapses that back to "one word,
 *  two attempts" rather than counting it as two words. */
interface Turn {
  item: QueueItem;
  result: PracticeAnswer;
}

/**
 * The practice session, then its end screen — one component, because the
 * queue that drives the first half is also the source of the second half's
 * stats, and splitting them into two routes would mean passing that queue
 * through router state or refetching a session that has already been spent.
 *
 * ## The queue lives here, not on the server
 *
 * `POST /practice/session` is called once, on mount, and its `items` become
 * local state that this page mutates directly: popping the front off on
 * every answer, pushing the same item back onto the END when the server
 * says `returns_this_session`. The server is never asked "what's next" a
 * second time — it doesn't know either, because the queue's own order past
 * the first requeue is a client-side fact, not something FSRS decides.
 *
 * ## Stage 2: three tasks, one turn each
 *
 * `current.exercise_type` picks which of three small components renders —
 * `ChoicePrompt` (recognise, both directions), the inline gap (recall,
 * unchanged from stage 1) or `ProducePrompt` (produce). All three share the
 * same submit/reveal/advance skeleton below; only the middle changes.
 *
 * ## Calm, on purpose
 *
 * One word. No sidebar, no timer visible, no list of what's coming. The
 * brief's word for this screen is "tinch" (calm) and the take screen right
 * next door is the opposite of that by design — a forty-question paper with
 * a navigator strip and a clock. This has neither, because there is nothing
 * here to navigate between; there is one word, and then there is the next
 * one.
 */
export default function VocabularyPracticePage() {
  const tz = localTimeZone();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const exit = () => navigate("/vocabulary");

  const { data, isPending, isError } = useQuery({
    queryKey: ["vocabulary", "practice", "session", tz],
    queryFn: () => vocabularyApi.practiceSession(tz),
    // Never served from a previous mount's cache: reloading this page is
    // meant to re-plan, not resume a stale plan from ten minutes ago that
    // may no longer reflect what's due.
    staleTime: 0,
    gcTime: 0,
  });

  // Read only to tell "genuinely nothing to practise" apart from "you asked
  // for one task and nothing is at that rung yet" (F2) — shares the
  // settings page's own cache key.
  const { data: settings } = useQuery({
    queryKey: ["vocabulary", "settings"],
    queryFn: () => vocabularyApi.settings(),
  });

  // `null` while the session hasn't landed yet; `[]` once every item — the
  // ones the server sent, plus every requeue — has been answered. Those are
  // two different reasons to render nothing further, kept as one variable
  // because the render logic already has to ask "do we have a current
  // item?" and null vs. empty both answer "no".
  const [queue, setQueue] = useState<QueueItem[] | null>(null);
  const [totalCount, setTotalCount] = useState(0);
  const [answeredCount, setAnsweredCount] = useState(0);
  const [given, setGiven] = useState("");
  const [selectedOptionId, setSelectedOptionId] = useState<string | null>(null);
  const [result, setResult] = useState<PracticeAnswer | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  // Whether THIS turn is the one attempt "I know this" bought — set the
  // moment the known-check item is swapped in, cleared the moment the
  // answer that follows is sent (see `submit`). `claimedResult` is the
  // same fact held past that clearing, for the Reveal that reads it.
  const [pendingClaim, setPendingClaim] = useState(false);
  const [claimedResult, setClaimedResult] = useState(false);
  // The item on screen has already spent its "I know this" — set once the
  // swap happens so the button cannot be pressed a second time on the same
  // turn while its one attempt is still pending.
  const [usedKnownCheck, setUsedKnownCheck] = useState(false);
  const [leechChoice, setLeechChoice] = useState<LeechChoice | null>(null);
  // Wall-clock, not a React state value: resetting it must never itself
  // cause a render, and reading it happens only once, at submit.
  const shownAt = useRef(Date.now());

  useEffect(() => {
    if (data && queue === null) {
      setQueue(data.items);
      setTotalCount(data.items.length);
      shownAt.current = Date.now();
    }
  }, [data, queue]);

  // Esc exits from anywhere on this page, focus or no focus — the field
  // itself also handles it while typing (see below), but a learner who has
  // clicked the source-material link or is mid-reveal with the field blurred
  // still needs a way out that doesn't depend on where the pointer last was.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        exit();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const ended = queue !== null && queue.length === 0;

  // Once the queue is spent, the numbers this session made stale — due
  // count, totals, next review — are refetched under the SAME key the home
  // screen reads, so going back there shows what just happened rather than
  // what was true when this page opened.
  useEffect(() => {
    if (ended) void qc.invalidateQueries({ queryKey: practiceSummaryKey(tz) });
  }, [ended, tz, qc]);

  const { data: freshSummary } = useQuery({
    queryKey: practiceSummaryKey(tz),
    queryFn: () => vocabularyApi.practiceSummary(tz),
    enabled: ended,
  });

  const answer = useMutation({
    mutationFn: vocabularyApi.practiceAnswer,
    onSuccess: (res) => setResult(res),
    onError: (e) => toast(getErrorMessage(e)),
  });

  const knownCheck = useMutation({
    mutationFn: (wordId: string) => vocabularyApi.knownCheck(wordId),
    onSuccess: (item) => {
      // Swaps the item on screen for the recall check the spec describes —
      // never a second item appended, since this IS the current word's one
      // attempt, not a new turn in the queue.
      setQueue((was) => (was ? [item, ...was.slice(1)] : was));
      setUsedKnownCheck(true);
      setPendingClaim(true);
      setGiven("");
      setSelectedOptionId(null);
      setResult(null);
      shownAt.current = Date.now();
    },
    onError: (e) => toast(getErrorMessage(e)),
  });

  const leech = useMutation({
    mutationFn: ({ wordId, choice }: { wordId: string; choice: LeechChoice }) =>
      vocabularyApi.leech(wordId, choice),
    onSuccess: (_res, { choice }) => {
      setLeechChoice(choice);
      // "See it in context" stays ON this card — `result.leech_context`
      // already carries the sentence, so there is nothing left to fetch and
      // nowhere to navigate to (F5: never leaves the session). Setting
      // `leechChoice` alone is enough to unblock the ordinary Enter-to-
      // advance handler below; the learner reads the sentence and presses
      // Enter same as any other reveal. `set_aside`/`keep` have nothing more
      // to show, so they advance at once.
      if (choice !== "see_context") advance();
    },
    onError: (e) => toast(getErrorMessage(e)),
  });

  const current = queue?.[0] ?? null;

  function submit(givenOverride?: string) {
    if (!current || answer.isPending || result) return;
    const claiming = pendingClaim;
    if (claiming) setPendingClaim(false);
    setClaimedResult(claiming);
    answer.mutate({
      word_id: current.word_id,
      context_id: current.context_id,
      direction: current.direction,
      exercise_type: current.exercise_type,
      // Always echoed — `PracticeItem.planned_exercise` is never absent
      // (it equals `exercise_type` outside a fallback), so there is no
      // "nothing to send" case the way there was when this field was
      // still modelled as nullable.
      planned_exercise: current.planned_exercise,
      given: givenOverride ?? given,
      elapsed_ms: Date.now() - shownAt.current,
      ...(claiming ? { claim_known: true } : {}),
      // Set exactly on the same-session requeue `advance` below produces —
      // never on an item's first appearance, and never on the known-check
      // swap, which is a fresh item rather than an Again come back (§1).
      requeued: Boolean(current.requeued),
    });
  }

  function chooseOption(id: string) {
    if (!current || answer.isPending || result) return;
    setSelectedOptionId(id);
    submit(id);
  }

  function advance() {
    if (!current || !result) return;
    setTurns((was) => [...was, { item: current, result }]);
    setQueue((was) => {
      if (!was) return was;
      const rest = was.slice(1);
      // The wrong-answer requeue, spelled out where the whole session can
      // see it: the client appends, the server has already rescheduled the
      // card either way (see the spec's §4). `returns_this_session` is
      // exactly `rating === Again`, and nothing else moves a word to the
      // back. Marked `requeued` so the answer that follows can say so (§1).
      return result.returns_this_session
        ? [...rest, { ...current, requeued: true }]
        : rest;
    });
    if (result.returns_this_session) setTotalCount((t) => t + 1);
    setAnsweredCount((c) => c + 1);
    setGiven("");
    setSelectedOptionId(null);
    setResult(null);
    setUsedKnownCheck(false);
    setClaimedResult(false);
    setLeechChoice(null);
    shownAt.current = Date.now();
  }

  // Every hotkey this screen owns, in one place: "0" for "I know this" (a
  // digit that can never collide with a `recognise` option, and never
  // fires while a text field has focus, so a `produce` answer starting
  // with a zero types normally). 1–4 pick a `recognise` option directly —
  // one press answers, there is no separate confirm step. Enter advances
  // past a reveal, except while a `became_leech` panel is still waiting
  // for one of its three choices.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const typing =
        e.target instanceof HTMLElement &&
        (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA");

      if (e.key === "Enter" && result) {
        if (result.became_leech && !leechChoice) return;
        e.preventDefault();
        advance();
        return;
      }

      if (typing || !current || result) return;

      if (
        current.direction === "passive" &&
        current.is_new &&
        !usedKnownCheck &&
        !knownCheck.isPending &&
        e.key === "0"
      ) {
        e.preventDefault();
        knownCheck.mutate(current.word_id);
        return;
      }

      if (current.prompt.kind === "choice" && /^[1-4]$/.test(e.key)) {
        const option = current.prompt.options[Number(e.key) - 1];
        if (option) {
          e.preventDefault();
          chooseOption(option.id);
        }
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
    // `advance`, `submit` and `chooseOption` close over this render's state
    // rather than being redeclared as stable refs — cheap to reattach and
    // simpler than a ref dance for a handful of keys.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, result, leechChoice, usedKnownCheck, knownCheck.isPending]);

  if (isPending || queue === null) return <SessionSkeleton />;

  if (isError || !data) {
    return (
      <div className="mx-auto w-full max-w-xl py-16 text-center">
        <p className="text-sm text-destructive">
          Your session couldn&apos;t be built.
        </p>
        <Link
          to="/vocabulary"
          className="mt-3 inline-block text-sm text-primary hover:underline"
        >
          Back to Vocabulary
        </Link>
      </div>
    );
  }

  // A manual exercise type in Settings is what's most likely to leave
  // nothing here — never worded as "you're all caught up", which would be
  // true of nothing left to LEARN rather than of one narrow task (F2).
  const manualEmpty = settings?.exercise_types != null;

  if (ended) {
    return (
      <EndScreen
        turns={turns}
        nextDueAt={freshSummary?.next_due_at ?? null}
        manualEmpty={manualEmpty}
        onExit={exit}
      />
    );
  }

  // Not reachable via the home screen, which hides Start once nothing is
  // due — but the URL is typeable, and the budget can also run out between
  // opening the home screen and pressing Start.
  if (!current) {
    return (
      <div className="mx-auto w-full max-w-xl py-16 text-center">
        <p className="text-sm text-muted-foreground">
          {manualEmpty
            ? "No words are ready for this yet."
            : "Nothing to practise right now."}
        </p>
        <Link
          to="/vocabulary"
          className="mt-3 inline-block text-sm text-primary hover:underline"
        >
          Back to Vocabulary
        </Link>
      </div>
    );
  }

  const position = Math.min(answeredCount + 1, totalCount);
  const prompt = current.prompt;
  const tone = !result
    ? "border-border"
    : result.verdict === "correct"
      ? "border-correct text-correct"
      : result.verdict === "close"
        ? "border-warning text-warning"
        : "border-incorrect text-incorrect";

  const showKnownCheck =
    current.direction === "passive" &&
    current.is_new &&
    !usedKnownCheck &&
    !result;

  // An if/else statement rather than a nested ternary: TypeScript narrows a
  // discriminated union reliably across `if`/`else if`/`else`, and less
  // reliably through the falsy branch of a ternary chained inside another
  // ternary — `prompt` came back typed as still possibly `sentence` in the
  // final branch when this was one expression.
  function renderPrompt() {
    // `current` is already guaranteed non-null at this point in the render
    // (the early return above), but a nested function closes over the
    // OUTER type rather than this render's narrowed one, so TypeScript
    // needs telling again.
    if (!current) return null;
    if (prompt.kind === "sentence" || prompt.kind === "definition") {
      return (
        <RecallPrompt
          before={prompt.before}
          after={prompt.after}
          cue={prompt.cue}
          // Both `sentence` and `definition` prompts may carry one now
          // (§B) — a masked cue above the gap, dimmer than the sentence
          // itself, so `kind` no longer decides whether it is read.
          definition={prompt.definition}
          value={given}
          onChange={setGiven}
          onSubmit={() => submit()}
          onExit={exit}
          disabled={answer.isPending || Boolean(result)}
          tone={tone}
          turnKey={`${current.word_id}-${answeredCount}`}
        />
      );
    }
    if (prompt.kind === "choice") {
      return (
        <ChoicePrompt
          prompt={prompt}
          selectedId={selectedOptionId}
          correctText={result?.answer ?? null}
          disabled={answer.isPending || Boolean(result)}
          onChoose={chooseOption}
        />
      );
    }
    return (
      <ProducePrompt
        prompt={prompt}
        value={given}
        onChange={setGiven}
        onSubmit={() => submit()}
        onExit={exit}
        disabled={answer.isPending || Boolean(result)}
        tone={tone}
        turnKey={`${current.word_id}-${answeredCount}`}
      />
    );
  }

  return (
    <div className="mx-auto flex min-h-[70vh] w-full max-w-xl flex-col justify-center py-10">
      {showKnownCheck && (
        <div className="mb-6 flex justify-center">
          <button
            type="button"
            disabled={knownCheck.isPending}
            onClick={() => knownCheck.mutate(current.word_id)}
            className="flex items-center gap-1.5 rounded-full border border-border px-3 py-1 text-xs text-muted-foreground transition-colors duration-fast hover:border-primary/50 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50"
          >
            <Kbd>0</Kbd>
            I know this
          </button>
        </div>
      )}

      <div className="flex-1">{renderPrompt()}</div>

      {result && (
        <>
          <Reveal
            result={result}
            exerciseType={current.exercise_type}
            direction={current.direction}
            claimed={claimedResult}
          />
          {result.became_leech && (
            <>
              <LeechPanel
                resolved={leechChoice}
                busy={leech.isPending}
                onChoose={(choice) => leech.mutate({ wordId: current.word_id, choice })}
              />
              {leechChoice === "see_context" && result.leech_context && (
                <LeechContextPanel context={result.leech_context} />
              )}
            </>
          )}
        </>
      )}

      <p className="mt-10 text-center text-xs tabular-nums text-muted-foreground">
        {position} / {totalCount}
      </p>
    </div>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded border border-border bg-surface-sunken px-1 py-px font-mono text-[0.65rem] text-foreground">
      {children}
    </kbd>
  );
}

/** `recall`'s prompt, unchanged from stage 1: the sentence with the gap
 *  inline, or — the `definition` fallback — the word's own meaning
 *  standing in for a sentence that doesn't exist. */
function RecallPrompt({
  before,
  after,
  cue,
  definition,
  value,
  onChange,
  onSubmit,
  onExit,
  disabled,
  tone,
  turnKey,
}: {
  before: string;
  after: string;
  cue: string;
  definition: string | null;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onExit: () => void;
  disabled: boolean;
  tone: string;
  turnKey: string;
}) {
  return (
    <>
      {definition && (
        <p className="text-center text-sm text-muted-foreground italic">
          {definition}
        </p>
      )}
      <p
        className={cn(
          "text-xl leading-relaxed text-foreground",
          definition ? "mt-4 text-center" : "text-center sm:text-left",
        )}
      >
        {before}
        <GapField
          // A fresh key per turn — including a requeued repeat of the same
          // word — so the input remounts and `autoFocus` fires again
          // rather than the browser leaving focus wherever it landed on
          // the previous item.
          key={turnKey}
          autoFocus
          // What the learner actually typed, kept on screen after
          // grading rather than overwritten with the right answer — the
          // take screen's own completion gap does the same (see
          // `FormCompletionGroup`): the field says what you wrote, its
          // colour says whether that was right, and the correct answer
          // is printed in the reveal panel below rather than substituted
          // into the box you typed in.
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              // Submitting only — advancing past a reveal is the
              // document-level handler's job, so the same Enter press
              // is never handled twice.
              e.preventDefault();
              onSubmit();
            } else if (e.key === "Escape") {
              // Stopped here, or the document listener exits a second
              // time and Back has to be pressed twice to leave.
              e.preventDefault();
              e.stopPropagation();
              onExit();
            }
          }}
          disabled={disabled}
          // Only when `needs_letter_hint` (§B) put a real character in
          // `cue` — an empty cue is the server's own "no hint earned",
          // never a placeholder that happens to render as nothing.
          placeholder={cue || undefined}
          aria-label={
            cue
              ? `Type the missing word. It starts with ${cue}.`
              : "Type the missing word."
          }
          tone={tone}
          className="mx-1 w-40"
        />
        {after}
      </p>
    </>
  );
}

/** `produce`'s prompt: the Uzbek meaning to write FROM, and the same gap
 *  field `recall` uses — this direction is still "fill the gap", the gap
 *  just has no sentence around it. */
function ProducePrompt({
  prompt,
  value,
  onChange,
  onSubmit,
  onExit,
  disabled,
  tone,
  turnKey,
}: {
  prompt: PracticeProducePrompt;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onExit: () => void;
  disabled: boolean;
  tone: string;
  turnKey: string;
}) {
  return (
    <div className="text-center">
      {prompt.pos && (
        <p className="text-xs text-muted-foreground italic">{prompt.pos}</p>
      )}
      <p className="mt-1 text-2xl font-semibold text-foreground">
        {prompt.meaning_uz}
      </p>
      <div className="mt-6 flex justify-center">
        <GapField
          key={turnKey}
          autoFocus
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              onSubmit();
            } else if (e.key === "Escape") {
              e.preventDefault();
              e.stopPropagation();
              onExit();
            }
          }}
          disabled={disabled}
          placeholder={prompt.cue}
          aria-label={`Write the word in English. It starts with ${prompt.cue}.`}
          tone={tone}
          className="w-48 text-center"
        />
      </div>
    </div>
  );
}

/** `recognise`'s prompt, both directions. Passive shows the English word
 *  alone when there is no sentence to mark it inside (F3: `before`/`after`
 *  empty, `target` the lemma) and offers English definitions; active shows
 *  the Uzbek meaning to translate and offers English lemmas. One component
 *  either way, because the split is which fields the server filled in, not
 *  a different task. */
function ChoicePrompt({
  prompt,
  selectedId,
  correctText,
  disabled,
  onChoose,
}: {
  prompt: PracticeChoicePrompt;
  selectedId: string | null;
  /** `result.answer` once graded — the right option's own text, used only
   *  to highlight it. `null` before an answer exists. */
  correctText: string | null;
  disabled: boolean;
  onChoose: (id: string) => void;
}) {
  const active = prompt.shown_meaning_uz !== null;
  const hasSentence = Boolean(prompt.before || prompt.after);
  return (
    <div>
      {active ? (
        <div className="text-center">
          <p className="mt-1 text-2xl font-semibold text-foreground">
            {prompt.shown_meaning_uz}
          </p>
        </div>
      ) : hasSentence ? (
        <p className="text-center text-xl leading-relaxed text-foreground sm:text-left">
          {prompt.before}
          <mark className="rounded bg-primary/15 px-1 text-foreground">
            {prompt.target}
          </mark>
          {prompt.after}
        </p>
      ) : (
        // Passive `recognise`, per the spec's addendum: the English word
        // alone, no sentence around it — shown the same prominent way
        // active's Uzbek meaning is, rather than as a lone `<mark>` sitting
        // in an otherwise empty sentence.
        <div className="text-center">
          <p className="mt-1 text-2xl font-semibold text-foreground">
            {prompt.target}
          </p>
        </div>
      )}
      <div
        role="radiogroup"
        aria-label="Choose the right answer"
        className="mt-6 grid grid-cols-1 gap-2 sm:grid-cols-2"
      >
        {prompt.options.map((option, i) => (
          <OptionButton
            key={option.id}
            index={i}
            option={option}
            selected={option.id === selectedId}
            correct={correctText != null && option.text === correctText}
            graded={correctText != null}
            disabled={disabled}
            onChoose={onChoose}
          />
        ))}
      </div>
    </div>
  );
}

/** All four the SAME height, whatever the length of the text behind them
 *  (F3) — a `min-h` sized to comfortably fit two lines plus the row's own
 *  padding, and `line-clamp-2` so a definition longer than that is clipped
 *  rather than stretching its own row and giving the answer away by being
 *  visibly the odd one out. */
function OptionButton({
  index,
  option,
  selected,
  correct,
  graded,
  disabled,
  onChoose,
}: {
  index: number;
  option: PracticeOption;
  selected: boolean;
  correct: boolean;
  graded: boolean;
  disabled: boolean;
  onChoose: (id: string) => void;
}) {
  const tone = !graded
    ? "border-border hover:border-primary/50 hover:bg-surface-hover"
    : correct
      ? "border-correct bg-correct/10 text-correct"
      : selected
        ? "border-incorrect bg-incorrect/10 text-incorrect"
        : "border-border text-muted-foreground";
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      disabled={disabled}
      onClick={() => onChoose(option.id)}
      className={cn(
        "flex min-h-16 items-center gap-2.5 rounded-xl border px-3.5 py-2.5 text-left text-sm transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:cursor-default",
        tone,
      )}
      // The same number the "1–4" hotkey uses, so a learner who has
      // noticed the keys can also see which digit each button answers to.
      aria-label={`${index + 1}. ${option.text}`}
    >
      <span className="flex size-5 shrink-0 items-center justify-center rounded-full border border-current/40 font-mono text-[0.7rem] tabular-nums">
        {index + 1}
      </span>
      <span className="line-clamp-2">{option.text}</span>
    </button>
  );
}

/** What one answer reveals — never sent with the prompt, always after.
 *  Order follows the spec exactly for a passive `recognise` turn: the
 *  right English definition first, the Uzbek meaning under it — the
 *  opposite of `recall`/`produce`'s order, where the Uzbek leads because
 *  it is the thing being written FROM. */
function Reveal({
  result,
  exerciseType,
  direction,
  claimed,
}: {
  result: PracticeAnswer;
  exerciseType: ExerciseType;
  direction: Direction;
  /** Whether THIS turn was the one attempt "I know this" bought — see the
   *  spec's §4. Adds a headline the ordinary reveal doesn't have; nothing
   *  else about the reveal changes. */
  claimed: boolean;
}) {
  const sense = meanings(result.word);
  const passiveRecognise = exerciseType === "recognise" && direction === "passive";
  const verdictLabel =
    result.verdict === "correct"
      ? "Correct"
      : result.verdict === "close"
        ? "Close"
        : "Not quite";
  const verdictTone =
    result.verdict === "correct"
      ? "text-correct"
      : result.verdict === "close"
        ? "text-warning"
        : "text-incorrect";

  return (
    <div className="mt-6 rounded-xl border border-border bg-card px-5 py-4">
      {/* Only on success (F4): a failed "I know this" check says nothing at
       *  all and just continues as an ordinary item — no "In rotation"
       *  line, which used to read as a small verdict on a guess that was
       *  never meant to be graded out loud. A state, not a verb, when it
       *  does show — this line says what the word IS now, the same way
       *  `STATUS_CHIP_LABEL` does everywhere else; "Marked as known" is the
       *  button that asked for this, not the outcome of asking. */}
      {claimed && result.known && (
        <p className="text-sm font-semibold text-foreground">
          {STATUS_CHIP_LABEL.known}
        </p>
      )}
      <p className={cn("text-sm font-semibold", verdictTone)}>
        {verdictLabel}
        <span className="ml-1.5 font-normal text-muted-foreground">
          — {result.answer}
        </span>
      </p>
      <p className="mt-2.5 flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
        <span className="text-base font-semibold text-foreground">
          {result.word.lemma}
        </span>
        {result.word.pos && (
          <span className="text-xs text-muted-foreground italic">
            {result.word.pos}
          </span>
        )}
        <CefrTag level={result.word.cefr_level} />
      </p>
      {passiveRecognise ? (
        <>
          <p className="mt-1 text-sm text-foreground">{sense.en}</p>
          <p className="text-xs text-muted-foreground">{sense.uz}</p>
        </>
      ) : (
        <>
          <p className="mt-1 text-sm text-foreground">{sense.uz}</p>
          <p className="text-xs text-muted-foreground">{sense.en}</p>
        </>
      )}
      {sense.here && (
        <p className="mt-1.5 border-l-2 border-border pl-2">
          <span className="block text-sm text-foreground">
            <span className="text-muted-foreground">Here: </span>
            {sense.here.uz}
          </span>
          <span className="block text-xs text-muted-foreground">
            {sense.here.en}
          </span>
        </p>
      )}
      {result.word.material_id && result.word.material_title && (
        <Link
          to={`/reading/${result.word.material_id}`}
          className="mt-2 inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <BookOpen className="size-3" aria-hidden />
          {result.word.material_title}
        </Link>
      )}
      {result.word.sense_id && (
        <ReportTranslation
          senseId={result.word.sense_id}
          where="practice"
          className="mt-2"
        />
      )}
      <p className="mt-3 text-xs text-muted-foreground">
        Enter for the next word · Esc to stop
      </p>
    </div>
  );
}

/** The three choices a `became_leech` reveal offers, in place of the card
 *  rather than a modal (F5) — `resolved` gates the Enter-to-advance handler
 *  above so a learner cannot fall through to the next word without picking
 *  one, since a leech is a deliberate fork the app is asking them to take,
 *  not a reflex. Labels are `LEECH_LABEL`'s, exactly as the fixes brief
 *  words them — the same three on the word page. */
function LeechPanel({
  resolved,
  busy,
  onChoose,
}: {
  resolved: LeechChoice | null;
  busy: boolean;
  onChoose: (choice: LeechChoice) => void;
}) {
  return (
    <div className="mt-3 rounded-xl border border-attention/40 bg-attention/10 px-5 py-4">
      <p className="text-sm text-foreground">
        This word keeps coming back wrong. What now?
      </p>
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={busy || resolved !== null}
          onClick={() => onChoose("set_aside")}
        >
          {LEECH_LABEL.set_aside}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={busy || resolved !== null}
          onClick={() => onChoose("see_context")}
        >
          {LEECH_LABEL.see_context}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={busy || resolved !== null}
          onClick={() => onChoose("keep")}
        >
          {LEECH_LABEL.keep}
        </Button>
      </div>
    </div>
  );
}

/** What "See it in context" shows, in the card rather than sending the
 *  learner away (F5) — the word's newest sentence, marked, with the way to
 *  the material it came from. Reuses the `<mark>` styling `ChoicePrompt`'s
 *  sentence already wears, so a marked word reads the same wherever this
 *  session shows one. */
function LeechContextPanel({ context }: { context: PracticeLeechContext }) {
  return (
    <div className="mt-3 rounded-xl border border-border bg-card px-5 py-4">
      <p className="text-sm leading-relaxed text-foreground">
        {context.before}
        <mark className="rounded bg-primary/15 px-1 text-foreground">
          {context.target}
        </mark>
        {context.after}
      </p>
      {context.material_title && (
        <Link
          to={`/reading/${context.material_id}`}
          className="mt-2 inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <BookOpen className="size-3" aria-hidden />
          {context.material_title}
        </Link>
      )}
    </div>
  );
}

/** Distinct words this session touched, and the shape `jokes.ts` and the end
 *  screen's stat line both need — collapsed from `turns`, where a word that
 *  came back after an Again appears twice. */
function summarise(turns: Turn[]): SessionStats & {
  newCount: number;
  reviewedCount: number;
} {
  const firstSeenNew = new Map<string, boolean>();
  const wrongCounts = new Map<string, number>();

  for (const { item, result } of turns) {
    if (!firstSeenNew.has(item.word_id)) {
      firstSeenNew.set(item.word_id, item.is_new);
    }
    if (result.verdict === "wrong") {
      wrongCounts.set(item.lemma, (wrongCounts.get(item.lemma) ?? 0) + 1);
    }
  }

  let newCount = 0;
  let reviewedCount = 0;
  for (const isNew of firstSeenNew.values()) {
    if (isNew) newCount += 1;
    else reviewedCount += 1;
  }

  let hardest: string | null = null;
  let hardestCount = 0;
  for (const [lemma, count] of wrongCounts) {
    if (count > hardestCount) {
      hardest = lemma;
      hardestCount = count;
    }
  }

  return {
    total: firstSeenNew.size,
    struggled: wrongCounts.size,
    hardest,
    newCount,
    reviewedCount,
  };
}

/**
 * The end screen: one dry joke, then the small numbers.
 *
 * The brief is explicit about the joke's target — never the learner, only
 * the words or the app itself — which is why `jokes.ts` takes session
 * shapes (how many struggled, which one struggled most) rather than
 * anything that could read as a verdict on the person who just sat here.
 */
function EndScreen({
  turns,
  nextDueAt,
  manualEmpty,
  onExit,
}: {
  turns: Turn[];
  nextDueAt: string | null;
  /** Whether a manual exercise type in Settings is why there was nothing
   *  here — see the same flag at the call site (F2). */
  manualEmpty: boolean;
  onExit: () => void;
}) {
  const stats = useMemo(() => summarise(turns), [turns]);
  // Picked once per visit to this screen, not once per render — `pickJoke`
  // draws from a pool at random, and re-rolling it on an unrelated re-render
  // (the summary query landing a moment later) would change the joke under
  // a reader mid-sentence.
  const joke = useMemo(
    () => pickJoke(stats),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [stats.total, stats.struggled, stats.hardest],
  );

  if (stats.total === 0) {
    return (
      <div className="mx-auto w-full max-w-xl py-20 text-center">
        <p className="text-sm text-muted-foreground">
          {manualEmpty
            ? "No words are ready for this yet."
            : "Nothing to practise right now."}
        </p>
        <Button type="button" onClick={onExit} className="mt-4">
          Back to Vocabulary
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-xl py-20 text-center">
      <p className="text-xl leading-relaxed text-foreground">{joke}</p>

      <dl className="mt-8 flex items-center justify-center gap-8">
        <EndStat label="new" value={stats.newCount} />
        <EndStat label="reviewed" value={stats.reviewedCount} />
      </dl>

      <p className="mt-6 text-sm text-muted-foreground">
        Next session {timeUntil(nextDueAt)}.
      </p>

      <Button type="button" onClick={onExit} className="mt-8">
        Done
      </Button>
    </div>
  );
}

function EndStat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <p className="text-2xl font-semibold tabular-nums text-foreground">
        {value}
      </p>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  );
}

/** Held open while the session builds. One centred bar for the sentence,
 *  one for the progress line — the shape of a screen that has almost
 *  nothing on it to begin with. */
function SessionSkeleton() {
  return (
    <SkeletonBlock
      label="Building your session"
      className="mx-auto flex min-h-[70vh] w-full max-w-xl flex-col justify-center py-10"
    >
      <div className="flex-1 text-center">
        <p className="text-xl">
          <Skeleton className="mx-auto inline-block h-[0.8em] w-64 max-w-full" />
        </p>
      </div>
      <p className="mt-10 text-center text-xs">
        <Skeleton className="mx-auto inline-block h-[0.8em] w-10" />
      </p>
    </SkeletonBlock>
  );
}
