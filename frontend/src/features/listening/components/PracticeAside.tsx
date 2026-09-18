import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import { fmtClock, timeAgo } from "@/lib/time";
import { QUESTION_TYPE_ICON, QUESTION_TYPE_LABEL } from "@/features/paper/question-types";
import {
  ACCURACY_TEXT,
  DIFFICULTY_CLASS,
  DIFFICULTY_LABEL,
  accuracyTone,
  authorSummary,
  standingFor,
} from "@/features/listening/practice";
import type { Scope } from "@/features/listening/practice";
import { AuthorAvatar } from "@/features/listening/components/AuthorTag";
import {
  PracticeStats,
  PracticeStatsSkeleton,
} from "@/features/listening/components/PracticeStats";
import type { LearnerStats, PracticeMaterial } from "@/features/paper/types";

/**
 * The column beside the list — two cards, each with something to say about
 * whichever row the reader is pointing at.
 *
 * At rest the big card is about the READER (where they are weak, what they
 * have done) and the small one is where they left off. Under the pointer both
 * turn to the row: what that material would be like to sit, and who wrote it.
 *
 * The swap is the whole idea. A catalogue row can only hold what fits on one
 * line, and the questions somebody actually has before clicking — is this
 * hard? have I done it? is it the part I keep losing marks on? who wrote it
 * and what else have they written? — need a paragraph each. Hovering is a
 * cheap way to ask, and hovering away is a cheap way to stop asking.
 */

/** The shell both cards wear. One definition so the two can't drift. */
function Card({
  children,
  className,
  label,
}: {
  children: React.ReactNode;
  className?: string;
  label: string;
}) {
  return (
    <section
      aria-label={label}
      className={cn(
        "flex flex-col overflow-hidden rounded-2xl border border-border-subtle bg-card/60",
        className,
      )}
    >
      {children}
    </section>
  );
}

/** The line that names what the block is about. Sentence case and quiet: set
 *  in tracked uppercase, five of these down one card turned it into a form to
 *  be filled in rather than a paragraph to be read. */
function Label({ children }: { children: React.ReactNode }) {
  return <p className="text-xs text-muted-foreground">{children}</p>;
}

interface PracticeAsideProps {
  /** Where this paper's pages live. See PracticeRow. */
  basePath: string;
  stats: LearnerStats | undefined;
  statsLoading: boolean;
  /** The row under the pointer, or with keyboard focus. */
  preview: PracticeMaterial | null;

  onPractisePart: (scope: Scope) => void;
}

export function PracticeAside({
  stats,
  basePath,
  statsLoading,
  preview,
  onPractisePart,
}: PracticeAsideProps) {
  if (!preview) {
    if (statsLoading) return <PracticeStatsSkeleton />;
    if (!stats) return null;
    // stats being in error falls through to nothing on purpose. The column is
    // support for the list, and a red box where the encouragement goes would
    // make a failed side request look like the page is broken.
    return (
      <Face key="stats">
        <PracticeStats stats={stats} onBrowsePart={onPractisePart} />
      </Face>
    );
  }

  return (
    // Keyed by the row it is describing, so React replaces the subtree on
    // every change and the fade runs again. Without a key the same elements
    // would be reused with new text in them, and moving from one row to the
    // next would swap the words with no fade at all.
    <Face key={preview.id}>
      <div className="space-y-3">
        <Card label="About this material">
          <MaterialPreview material={preview} stats={stats} basePath={basePath} />
        </Card>
        {preview.author && (
          <Card label="About the author" className="px-4 py-3.5">
            <AuthorPanel material={preview} />
          </Card>
        )}
      </div>
    </Face>
  );
}

/**
 * One face of a card, arriving out of a blur.
 *
 * The animation is in globals.css because it moves `filter`, which no utility
 * does. Off where the reader has asked for less motion — a dissolve is the
 * whole of what this contributes, so without it there is nothing to keep.
 */
function Face({ children }: { children: React.ReactNode }) {
  return (
    <div className="animate-fade-blur motion-reduce:animate-none flex flex-1 flex-col">
      {children}
    </div>
  );
}

// --- The big card, under the pointer ---------------------------------------

function MaterialPreview({
  material: m,
  stats,
  basePath,
}: {
  material: PracticeMaterial;
  stats: LearnerStats | undefined;
  /** Where this paper's pages live. See PracticeRow. */
  basePath: string;
}) {
  const standing = standingFor(m, stats);
  const done = m.attempts > 0 && m.best_score !== null;
  const best =
    done && m.question_count > 0
      ? Math.round((m.best_score! / m.question_count) * 100)
      : null;

  return (
    <div className="flex flex-1 flex-col">
      <div className="px-4 py-3">
        <Label>Material</Label>
        <p className="mt-1 text-base leading-tight text-foreground">{m.title}</p>
      </div>

      {/* The conclusion first, in the slot the weakest-area line occupies at
          rest — so the eye finds the same kind of sentence in the same place
          whichever way the card is turned. */}
      {standing && (
        <Row title="For you">
          {standing.accuracy_pct === null ? (
            <span className="text-muted-foreground">
              Part {standing.part} — you haven&apos;t answered enough of it to
              say
            </span>
          ) : (
            <span className="text-foreground">
              Part {standing.part} ·{" "}
              <span
                className={cn(
                  "tabular-nums",
                  ACCURACY_TEXT[accuracyTone(standing.accuracy_pct)],
                )}
              >
                {standing.accuracy_pct}%
              </span>{" "}
              <span className="text-muted-foreground">right so far</span>
            </span>
          )}
        </Row>
      )}

      {/* The band with its working shown. The row prints the word; this is
          the number the word came from, which is the difference between a
          label and a measurement. */}
      <Row title="Difficulty">
        <span className="flex items-center gap-2">
          <span
            className={cn(
              "rounded-full border px-2 py-0.5 text-xs font-medium",
              DIFFICULTY_CLASS[m.difficulty.band],
            )}
          >
            {DIFFICULTY_LABEL[m.difficulty.band]}
          </span>
          <span className="text-muted-foreground">
            {m.difficulty.correct_pct === null
              ? m.difficulty.answered === 0
                ? "nobody has answered it yet"
                : `only ${m.difficulty.answered} answers so far`
              : `${m.difficulty.correct_pct}% right, over ${m.difficulty.answered} answers`}
          </span>
        </span>
      </Row>

      <Row title="Your record">
        {done ? (
          <span className="flex flex-wrap items-baseline gap-x-1.5 text-muted-foreground">
            <span className="tabular-nums text-foreground">{best}%</span>
            <span>best of</span>
            <span className="tabular-nums text-foreground">{m.attempts}</span>
            <span>{m.attempts === 1 ? "try" : "tries"}</span>
            {m.last_attempt_at && <span>· {timeAgo(m.last_attempt_at)}</span>}
          </span>
        ) : (
          <span className="text-muted-foreground">Not sat yet</span>
        )}
        {/* The way back to the marked paper. The row itself opens the
            material, so without this there is nowhere in the app that leads
            to a result you have already earned. */}
        {done && m.last_attempt_id && (
          <Link
            to={`${basePath}/attempts/${m.last_attempt_id}`}
            className="mt-1 inline-flex items-center gap-1 text-xs text-primary transition-colors hover:underline"
          >
            See your answers
            <ArrowRight className="size-3" aria-hidden />
          </Link>
        )}
      </Row>

      <Row title="What's in it">
        <span className="text-muted-foreground">
          <span className="tabular-nums text-foreground">
            {m.question_count}
          </span>{" "}
          question{m.question_count === 1 ? "" : "s"}
          {m.part_count > 1 && <> across {m.part_count} parts</>}
          {m.duration_ms != null && <> · {fmtClock(m.duration_ms)} of audio</>}
        </span>
        {/* Every type it holds, named. The row has space for one and says "2
            question types" for the rest, which is the honest summary and a
            useless one when you are deciding whether to sit it. */}
        {m.question_types.length > 0 && (
          <ul className="mt-1.5 space-y-1" data-preview-types>
            {m.question_types.map((type) => {
              const Icon = QUESTION_TYPE_ICON[type];
              return (
                <li
                  key={type}
                  className="flex items-center gap-1.5 text-xs text-muted-foreground"
                >
                  <Icon className="size-3.5 shrink-0 opacity-80" aria-hidden />
                  {QUESTION_TYPE_LABEL[type]}
                </li>
              );
            })}
          </ul>
        )}
      </Row>

      {/* Pinned to the foot of the card rather than left to follow the text:
          the card is floored to the height of the statistics face, so without
          this the action would float in the middle of a hole. Reachable
          because the aside holds the preview while the pointer is over it —
          see the page's hover handling. */}
      <div className="mt-auto border-t border-border-subtle px-4 py-3">
        <Link
          to={`${basePath}/${m.id}`}
          className="inline-flex items-center gap-1.5 text-sm text-primary transition-colors hover:underline"
        >
          {done ? "Sit it again" : "Sit this material"}
          <ArrowRight className="size-3.5" aria-hidden />
        </Link>
      </div>
    </div>
  );
}

/** One labelled block of the preview. */
function Row({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-border-subtle px-4 py-3">
      <Label>{title}</Label>
      <div className="mt-1 text-sm">{children}</div>
    </div>
  );
}

// --- The small card ---------------------------------------------------------

function AuthorPanel({
  material: m,
}: {
  material: PracticeMaterial;
}) {
  const author = m.author!;
  // Counted by the server and carried on the row. It used to be counted here,
  // over the catalogue the page had — which stopped being the catalogue the
  // day the list started arriving a page at a time.
  const summary = authorSummary(author);

  return (
    <div>
      <Label>Written by</Label>
      <div className="mt-2 flex items-center gap-2.5">
        <AuthorAvatar author={author} className="size-8 text-sm" />
        <div className="min-w-0">
          <p className="truncate text-sm text-foreground">
            {author.display_name}
          </p>
          {/* The name and how much of the catalogue is theirs, and nothing
              else. What parts they write, what difficulty they tend to land
              on, how many questions they have written in total — all of it
              was true and none of it helps anybody choose a material to sit
              this evening. */}
          <p className="text-xs text-muted-foreground">
            <span className="tabular-nums">{summary.materials}</span> material
            {summary.materials === 1 ? "" : "s"}
            {summary.done > 0 && (
              <>
                {" · "}
                <span className="tabular-nums">{summary.done}</span> sat by you
              </>
            )}
          </p>
        </div>
      </div>
    </div>
  );
}
