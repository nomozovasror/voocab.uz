import { Link } from "react-router-dom";
import { BookOpen, Sparkles } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { fmtClock } from "@/lib/time";
import {
  DIFFICULTY_CLASS,
  DIFFICULTY_SHORT,
  describeTask,
  difficultyTitle,
  partLabel,
} from "@/features/listening/practice";
import type { NextUp as NextUpData, PracticeMaterial } from "@/features/listening/types";

/**
 * Three materials, above a catalogue nobody can read all of.
 *
 * A list of a thousand papers answers "what exists". This answers the
 * question people actually arrive with — "I have twenty minutes, what should
 * I do" — and it is the only part of the page that makes a choice on the
 * reader's behalf.
 *
 * Which is why the sentence above the three is not decoration. A
 * recommendation that cannot say why it was made is a shuffle with a
 * confident label on it, and the reader has no way to tell the two apart
 * except by being told. Each of the three reasons is a different claim, and
 * two of them are claims about the reader that had to be earned before the
 * server was allowed to make them (backend/app/services/recommend.py).
 *
 * Deliberately small. It sits above the list, not instead of it: somebody who
 * knows what they want should be able to look straight past this at the
 * search field, so it is three lines and a heading rather than three cards
 * with cover images.
 */

/**
 * What the block says it is doing, per reason.
 *
 * **`course` is a continuation, not a suggestion**, and it is the one case
 * where the heading is not "Suggested for you". Somebody four papers into a
 * six-paper course did not ask to be advised; they asked to carry on, and the
 * sentence that helps them is which lesson it is. The block still looks the
 * same because it is the same block — the reader has one place to look for
 * "what now" whichever half of the page they were working from.
 *
 * **The heading is an action; the reason is a line under it.** That division
 * is doing real work, because the panel beside this one is also about where
 * the reader goes wrong, and the two used to lead with competing diagnoses —
 * "Part 1 is where you lose most marks" against "Where you lose marks", each
 * with a different number attached. A reader with two analyses in front of
 * them has to decide which to believe, which is a job the page has handed
 * them rather than done.
 *
 * So they are split by job. The panel diagnoses: what you get wrong, in what
 * kind. This recommends: what to sit. The diagnosis appears here only as the
 * one-line justification for the recommendation, in the panel's own words and
 * never with a second figure of its own.
 *
 * Written in full sentences rather than assembled from fragments — "Part 3 ·
 * 52%" is a readout, and this is meant to be read.
 */
function heading(data: NextUpData): { title: string; note: string } {
  if (data.reason === "course" && data.collection) {
    return {
      title: "Carry on",
      note:
        data.position && data.of
          ? `Lesson ${data.position} of ${data.of} in ${data.collection.title}.`
          : data.collection.title,
    };
  }
  if (data.reason === "weak_part") {
    return {
      title: "Worth sitting next",
      // The number is the working, and it is the SAME number the sidebar
      // shows — first-try accuracy on that part — said once here as a reason
      // rather than restated as a finding.
      note:
        data.accuracy_pct === null
          ? `Papers with Part ${data.part} in them.`
          : `Your first-try average on Part ${data.part} is ${data.accuracy_pct}%.`,
    };
  }
  if (data.reason === "start") {
    return {
      title: "Suggested for you",
      note: "Part 1 — the gentlest section, and the one the others build on.",
    };
  }
  return {
    title: "Suggested for you",
    note:
      data.accuracy_pct === null
        ? "Picked from what you haven't sat yet."
        : `Pitched around your first-try average of ${data.accuracy_pct}%.`,
  };
}

export function NextUp({ data }: { data: NextUpData }) {
  // Nothing to suggest — they have sat everything the filters could offer.
  // Silence is right here: a heading over an empty box is the page insisting
  // on speaking when it has nothing to say.
  if (data.items.length === 0) return null;

  const { title, note } = heading(data);
  const carrying = data.reason === "course";

  return (
    // Smaller than it was, and the reason is what it is FOR: it sits above
    // the catalogue and its whole job is to be looked past by anybody who
    // already knows what they want. A block that takes a third of the first
    // screenful is not a suggestion, it is an interruption.
    //
    // The heading and its reason are one line rather than two — the reason is
    // a subordinate clause, and putting it on its own line gave it the weight
    // of a second claim.
    <section
      aria-label={carrying ? "Carry on with your course" : "Suggested materials"}
      className="mb-5 rounded-xl border border-border-subtle bg-card/40 px-3 py-2.5"
    >
      <p className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="inline-flex items-center gap-1.5 text-xs text-foreground">
          {/* A different mark for a continuation than for a suggestion: one
              is somewhere the reader already is, the other is the page
              offering an opinion, and the icon is the first thing read. */}
          {carrying ? (
            <BookOpen className="size-3.5 shrink-0 text-primary" aria-hidden />
          ) : (
            <Sparkles className="size-3.5 shrink-0 text-primary" aria-hidden />
          )}
          {title}
        </span>
        {/* The course's name is a link where there is one — the reader may
            want the whole sequence rather than the next three of it. */}
        {carrying && data.collection ? (
          <Link
            to={`/listening/collections/${data.collection.id}`}
            className="text-xs text-muted-foreground transition-colors hover:text-foreground hover:underline"
          >
            {note}
          </Link>
        ) : (
          <span className="text-xs text-muted-foreground">{note}</span>
        )}
      </p>

      {/* An ordered list only where the order is real. Three suggestions are
          a set — nothing says sit them in this order — but the next lessons
          of a course are a sequence, and that is the whole claim a collection
          makes. No visible numbers either way: the lesson number is in the
          line above, and repeating it down the side would be the same fact
          three times. */}
      {carrying ? (
        <ol className="mt-1.5">
          {data.items.map((m) => (
            <li key={m.id}>
              <Suggestion material={m} />
            </li>
          ))}
        </ol>
      ) : (
        <ul className="mt-1.5">
          {data.items.map((m) => (
            <li key={m.id}>
              <Suggestion material={m} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** One suggestion: the same facts a catalogue row carries, at half the
 *  weight. No history column — everything here is by definition unsat. */
function Suggestion({ material: m }: { material: PracticeMaterial }) {
  const task = describeTask(m);
  const part = partLabel(m);

  return (
    <Link
      to={`/listening/${m.id}`}
      className="flex items-center gap-3 rounded-md px-2 py-1.5 transition-colors duration-fast hover:bg-surface-hover focus-visible:bg-surface-hover focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      <span className="min-w-0 flex-1 truncate text-sm text-foreground">
        {m.title}
      </span>
      <span className="hidden shrink-0 items-center gap-1.5 text-xs text-muted-foreground sm:flex">
        {part && <span>{part}</span>}
        {task && (
          <>
            <span aria-hidden className="opacity-60">
              ·
            </span>
            <span className="max-w-40 truncate">{task.label}</span>
          </>
        )}
        {m.duration_ms != null && (
          <>
            <span aria-hidden className="opacity-60">
              ·
            </span>
            <span className="tabular-nums">{fmtClock(m.duration_ms)}</span>
          </>
        )}
      </span>
      <span
        title={difficultyTitle(m)}
        className={cn(
          "w-14 shrink-0 rounded-full border py-0.5 text-center text-xs font-medium",
          DIFFICULTY_CLASS[m.difficulty.band],
        )}
      >
        {DIFFICULTY_SHORT[m.difficulty.band]}
      </span>
    </Link>
  );
}

/**
 * The block, waiting.
 *
 * Built from the real one's class strings so the two cannot drift, and
 * present at all because this sits ABOVE the list: a block that appears once
 * loaded would push the whole catalogue down the page under the reader's
 * pointer.
 */
export function NextUpSkeleton() {
  return (
    <section
      aria-hidden
      className="mb-5 rounded-xl border border-border-subtle bg-card/40 px-3 py-2.5"
    >
      <p className="flex items-center gap-2 text-xs">
        <Skeleton className="size-3.5 shrink-0 rounded-full" />
        <Skeleton className="inline-block h-[0.8em] w-32" />
        <Skeleton className="inline-block h-[0.8em] w-56 max-w-full" />
      </p>
      <ul className="mt-1.5">
        {[0, 1, 2].map((i) => (
          <li key={i} className="flex items-center gap-3 px-2 py-1.5">
            <span className="min-w-0 flex-1 text-sm">
              <Skeleton className="inline-block h-[0.8em] w-56 max-w-full" />
            </span>
            <Skeleton className="h-6 w-14 shrink-0 rounded-full" />
          </li>
        ))}
      </ul>
    </section>
  );
}
