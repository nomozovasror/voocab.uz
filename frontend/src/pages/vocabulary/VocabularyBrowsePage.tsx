import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, X } from "lucide-react";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { CefrTag } from "@/features/vocabulary/components/CefrTag";
import { wordMeaning } from "@/features/vocabulary/savedWordMeaning";
import { paramsToFilter, filterWords } from "@/features/vocabulary/wordsFilter";
import { vocabularyApi, vocabularyWordsKey } from "@/features/vocabulary/api";
import type { SavedContext, SavedWord } from "@/features/vocabulary/types";

/**
 * `/vocabulary/browse` — reading the saved list, not practising it.
 *
 * See `features/vocabulary/CLAUDE.md`'s "Browse is not practice" for the
 * whole argument; the short version lives in every choice below. Browse
 * writes exactly one thing anywhere — `saved_words.browsed_at`, when a card
 * is shown — and nothing about FSRS, a review log or the daily time budget
 * ever hears that this page was open.
 *
 * ## The deck is the words list, filtered — never a second query
 *
 * `GET /vocabulary/words` is already the words list's own fetch, and Browse
 * reads the SAME cached response and narrows it with the SAME four filters
 * (`filterWords`, shared with `VocabularyPage`) rather than asking the
 * server for a purpose-built "browse" list. Two implementations of "which
 * words match these filters" is how the deck and the list disagree about
 * what counts, and the whole promise of the "Browse" button on either entry
 * point is that it never does.
 *
 * No shuffle, ever — the spec is explicit, and the reason is the two entry
 * points: opened from the words list, the order is whatever a learner was
 * just looking at; opened from a material's saved-words panel, it is that
 * panel's own (materialId-scoped) order. Either way, reordering it would be
 * Browse making its own decision about something the caller already decided.
 */

const SWIPE_PX = 50;
const TAP_PX = 10;

/** Button, link, form field or anything `contenteditable` — the shortcuts
 *  below are withheld from all of them, per `isInteractiveElement`'s only
 *  caller: a Tab landing on "Close Browse" and a Space meant to press it
 *  must not also flip the card the button sits above. The card's own
 *  `role="button"` face is deliberately not in this list — Space there is
 *  documented (below it, "Space flip") as flipping the card, so the
 *  document handler has to keep acting while THAT element is focused. */
function isInteractiveElement(el: Element | null): boolean {
  if (!el) return false;
  const tag = el.tagName;
  if (
    tag === "BUTTON" ||
    tag === "A" ||
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT"
  ) {
    return true;
  }
  return el.hasAttribute("contenteditable") && el.getAttribute("contenteditable") !== "false";
}

function newestContext(word: SavedWord): SavedContext | null {
  if (word.contexts.length === 0) return null;
  return word.contexts.reduce((newest, ctx) =>
    new Date(ctx.created_at) > new Date(newest.created_at) ? ctx : newest,
  );
}

/** Which context a card shows: the material it was opened FROM, when the
 *  filter names one — the spec's "that material's context when opened from
 *  a material page" — otherwise the newest meeting. Reads off the same
 *  `material` filter field the words-list entry point can also set (its own
 *  "Source" dropdown), so a learner who narrowed to one material there sees
 *  exactly what they would from that material's own review page. */
function contextFor(word: SavedWord, materialId: string | null): SavedContext | null {
  if (materialId) {
    const matched = word.contexts.find((c) => c.material_id === materialId);
    if (matched) return matched;
  }
  return newestContext(word);
}

/** Only a same-app relative path is a safe exit target — a `from` this page
 *  reads off its own URL is, in the end, attacker-controlled input (a
 *  crafted link somebody was sent), and handing it straight to `navigate`
 *  would turn "close Browse" into an open redirect. `/\` and `//…` are both
 *  rejected alongside a full URL: browsers treat a leading `//` (and some,
 *  a leading `/\`) as protocol-relative, i.e. "same scheme, different
 *  host". */
function isSafeInternalPath(path: string | null): path is string {
  if (!path) return false;
  if (!path.startsWith("/")) return false;
  if (path.startsWith("//") || path.startsWith("/\\")) return false;
  return true;
}

export default function VocabularyBrowsePage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const materialParam = params.get("material");
  const fromParam = params.get("from");
  const exitTo = isSafeInternalPath(fromParam) ? fromParam : "/vocabulary/words";
  const filter = useMemo(() => paramsToFilter(params), [params]);

  const { data, isPending, isError } = useQuery({
    queryKey: vocabularyWordsKey,
    queryFn: () => vocabularyApi.words(),
  });

  const deck = useMemo(() => {
    if (!data) return [];
    return filterWords(data.words, filter);
  }, [data, filter]);

  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const current = deck[index] ?? null;

  // Only a genuine filter change (the back button, an edited URL) starts
  // over at the first card — a background refetch of the SAME filters
  // (a window refocus, another tab saving a word) must not throw a learner
  // mid-deck back to card one.
  useEffect(() => {
    setIndex(0);
    setFlipped(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter.status, filter.cefr, filter.material, filter.direction]);

  // A separate, narrower clamp for the deck shrinking under the current
  // index (a word deleted elsewhere while this tab was open) — moves back
  // exactly as far as it has to, never all the way to the start.
  useEffect(() => {
    if (deck.length > 0 && index >= deck.length) {
      setIndex(deck.length - 1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deck.length]);

  function exit() {
    // Back to wherever this was opened FROM — a `from` query param both
    // entry points set to their own path, never `navigate(-1)`. History is
    // not the caller: a bookmark, a shared link, or a tab whose history
    // reaches further back than the entry that opened Browse would all
    // send `-1` somewhere outside the app instead of back to the words
    // list or the material's review page. `exitTo` falls back to
    // `/vocabulary/words` when `from` is absent or not a same-app path.
    navigate(exitTo, { replace: true });
  }

  function next() {
    setIndex((i) => (i + 1 < deck.length ? i + 1 : i));
    setFlipped(false);
  }

  function prev() {
    setIndex((i) => (i > 0 ? i - 1 : i));
    setFlipped(false);
  }

  // One fire-and-forget mark per card this session actually shows —
  // keyed on the word's own id so flipping it, or coming back to a card
  // already seen, never sends it twice.
  const shown = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!current || shown.current.has(current.id)) return;
    shown.current.add(current.id);
    void vocabularyApi.browsed(current.id).catch(() => {
      // Nothing to recover — a missed mark costs a display fact, not a
      // learner's progress, and retrying it would be more code than the
      // fact is worth.
    });
  }, [current]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        exit();
        return;
      }
      // A focused interactive element gets Space/arrows first — Tab to
      // "Close Browse" then Space must activate that button, not flip the
      // card underneath it. Esc still exits from here, per above: nothing
      // reachable by Tab on this page has its own use for Escape.
      if (isInteractiveElement(document.activeElement)) return;
      if (e.key === " " || e.key === "Spacebar") {
        e.preventDefault();
        setFlipped((f) => !f);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        next();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        prev();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deck.length, index]);

  // Tap flips; a horizontal drag past `SWIPE_PX`, clearly more horizontal
  // than vertical, pages instead — the same gesture a photo gallery uses,
  // so it costs a learner nothing to already know. Both read from one
  // pointer-down/up pair rather than two separate handlers that would have
  // to agree on where a tap stops being a swipe.
  const pointerStart = useRef<{ x: number; y: number } | null>(null);

  function onPointerDown(e: React.PointerEvent) {
    pointerStart.current = { x: e.clientX, y: e.clientY };
  }

  function onPointerUp(e: React.PointerEvent) {
    // A press on the source-material link (either face) must only navigate
    // — flipping or paging on the same press would fire alongside it.
    if ((e.target as HTMLElement).closest("a")) {
      pointerStart.current = null;
      return;
    }
    const start = pointerStart.current;
    pointerStart.current = null;
    if (!start) return;
    const dx = e.clientX - start.x;
    const dy = e.clientY - start.y;
    if (Math.abs(dx) > SWIPE_PX && Math.abs(dx) > Math.abs(dy)) {
      if (dx < 0) next();
      else prev();
    } else if (Math.abs(dx) < TAP_PX && Math.abs(dy) < TAP_PX) {
      setFlipped((f) => !f);
    }
  }

  if (isPending) return <BrowseSkeleton />;

  if (isError || !data) {
    return (
      <div className="mx-auto w-full max-w-xl py-16 text-center">
        <p className="text-sm text-destructive">Your words couldn&apos;t be loaded.</p>
        <Link to="/vocabulary/words" className="mt-3 inline-block text-sm text-primary hover:underline">
          Back to your words
        </Link>
      </div>
    );
  }

  if (deck.length === 0) {
    return (
      <div className="mx-auto flex min-h-[70vh] w-full max-w-xl flex-col items-center justify-center gap-3 py-10 text-center">
        <p className="text-sm text-muted-foreground">
          No words match these filters.
        </p>
        <button
          type="button"
          onClick={exit}
          className="text-sm text-primary hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          Back
        </button>
      </div>
    );
  }

  // Unreachable given the `deck.length === 0` guard above and `next`/`prev`
  // never moving `index` outside the deck — asked for anyway so the JSX
  // below can read `current.lemma` rather than asserting it past `| null`.
  if (!current) return null;

  const context = contextFor(current, materialParam);
  const meaning = wordMeaning(current);
  const cefr = current.sense_cefr || current.cefr_level;

  return (
    <div className="mx-auto flex min-h-[70vh] w-full max-w-xl flex-col items-center justify-center py-10">
      <div className="mb-4 flex w-full items-center justify-between">
        <p className="text-xs tabular-nums text-muted-foreground">
          {index + 1} / {deck.length}
        </p>
        <button
          type="button"
          onClick={exit}
          aria-label="Close Browse"
          title="Close (Esc)"
          className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors duration-fast hover:bg-surface-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>

      <div
        className="browse-card-flip w-full touch-none select-none"
        onPointerDown={onPointerDown}
        onPointerUp={onPointerUp}
      >
        <div
          role="button"
          tabIndex={0}
          aria-label={
            flipped
              ? `${current.lemma}. Showing the meaning. Press Space to turn back.`
              : `${current.lemma}. Press Space to see its meaning.`
          }
          onKeyDown={(e) => {
            // Handled at document level (Space/arrows) — this only stops a
            // focused card from also scrolling the page on Space, since the
            // browser's default for a focused element is to do that.
            if (e.key === " ") e.preventDefault();
          }}
          className={cn(
            "browse-card-inner relative h-72 w-full cursor-pointer",
            flipped && "is-flipped",
          )}
        >
          <BrowseFace className="browse-card-face">
            <p className="text-3xl font-semibold text-foreground">
              {current.lemma}
            </p>
            <SourceLink context={context} />
          </BrowseFace>

          <BrowseFace className="browse-card-face browse-card-face-back">
            <div className="flex w-full flex-1 flex-col items-center justify-center gap-2 overflow-y-auto px-2">
              <p className="flex items-baseline gap-2">
                <span className="text-xl font-semibold text-foreground">
                  {current.lemma}
                </span>
                <CefrTag level={cefr} />
              </p>
              {meaning && (meaning.en || meaning.uz) && (
                <div className="text-center">
                  {meaning.en && (
                    <p className="text-sm text-foreground">{meaning.en}</p>
                  )}
                  {meaning.uz && (
                    <p className="text-sm text-muted-foreground">{meaning.uz}</p>
                  )}
                </div>
              )}
              {context?.example && (
                <p className="mt-1 max-w-sm text-center text-sm leading-relaxed text-foreground/80 italic">
                  {context.example}
                </p>
              )}
            </div>
            <SourceLink context={context} />
          </BrowseFace>
        </div>
      </div>

      <div className="mt-6 flex items-center gap-4 text-xs text-muted-foreground">
        <Kbd>Space</Kbd>
        <span>flip</span>
        <Kbd>←</Kbd>
        <Kbd>→</Kbd>
        <span>move</span>
        <Kbd>Esc</Kbd>
        <span>close</span>
      </div>
    </div>
  );
}

/** One face of the card — front and back share this shell so the flip is
 *  two identically-sized rectangles turning over each other, never a
 *  taller back replacing a shorter front. */
function BrowseFace({
  className,
  children,
}: {
  className: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "absolute inset-0 flex flex-col items-center justify-center gap-3 rounded-2xl border border-border bg-card px-6 py-8 text-center",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** The one link both faces carry, per the spec — the source material a
 *  learner met this word in, whichever context is on screen. Absent rather
 *  than disabled when a word has no context at all (a rare, pre-P4 row). */
function SourceLink({ context }: { context: SavedContext | null }) {
  if (!context?.material_title) return null;
  return (
    <Link
      to={`/reading/${context.material_id}`}
      className="mt-1 inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
    >
      <BookOpen className="size-3" aria-hidden />
      {context.material_title}
    </Link>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded border border-border bg-surface-sunken px-1 py-px font-mono text-[0.65rem] text-foreground">
      {children}
    </kbd>
  );
}

/** Held open while the deck loads — the shape of the card itself, so the
 *  page does not jump the moment the real one lands. Built from the real
 *  component's own class strings, per `frontend/CLAUDE.md`. */
function BrowseSkeleton() {
  return (
    <SkeletonBlock
      label="Loading your words"
      className="mx-auto flex min-h-[70vh] w-full max-w-xl flex-col items-center justify-center py-10"
    >
      <div className="mb-4 flex w-full items-center justify-between">
        <p className="text-xs">
          <Skeleton className="inline-block h-[0.8em] w-10" />
        </p>
      </div>
      <div className="h-72 w-full rounded-2xl border border-border bg-card px-6 py-8">
        <div className="flex h-full flex-col items-center justify-center gap-3">
          <p className="text-3xl">
            <Skeleton className="inline-block h-[0.8em] w-32" />
          </p>
        </div>
      </div>
    </SkeletonBlock>
  );
}
