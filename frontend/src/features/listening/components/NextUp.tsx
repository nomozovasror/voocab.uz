import { Link } from "react-router-dom";
import { ArrowRight, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { fmtClock } from "@/lib/time";
import {
  familyOfType,
  familyIcon,
  DIFFICULTY_CLASS,
  DIFFICULTY_SHORT,
  describeTask,
  difficultyTitle,
  partLabel,
} from "@/features/listening/practice";
import type { Scope } from "@/features/listening/practice";
import { CollectionCover } from "@/features/listening/components/CollectionBook";
import { coverKeyOf } from "@/features/paper/cover";
import type {
  NextUp as NextUpData,
  PracticeMaterial,
} from "@/features/paper/types";

/**
 * One slot above the list, and what fills it depends on where the reader is.
 *
 * Three shapes — carrying a course on, having just finished one, or being
 * suggested something — in the same place at about the same height, so
 * crossing from one state to the next does not make the page jump under
 * somebody's pointer. And nothing at all before there is enough history to
 * say anything: a block that appears once there is something to go on is a
 * better first impression than one that was always there saying nothing.
 *
 * Small either way. Its whole job is to be looked past by anybody who already
 * knows what they want, and the list underneath has to survive on the first
 * screenful.
 */

/** The line that says what this is, and the one that justifies it.
 *
 *  The panel on the other side of the page also talks about where the reader
 *  goes wrong, and the two used to lead with competing analyses, each with
 *  its own number — leaving somebody to decide which to believe. They are
 *  split by job: the panel diagnoses, this recommends, and the diagnosis
 *  appears here only as the reason, in the panel's own figure. */
function heading(data: NextUpData): string {
  if (data.reason === "weak_part") {
    return data.accuracy_pct === null
      ? `Papers with Part ${data.part} in them.`
      : `Part ${data.part} is where you drop the most marks — ${data.accuracy_pct}% on a first try.`;
  }
  if (data.reason === "steady") {
    // No weakest part to name, so it does not invent one. What is true about
    // this reader is that they are level; what follows is that the next thing
    // is harder rather than elsewhere.
    return "You're steady across every part — time for something harder.";
  }
  return data.accuracy_pct === null
    ? "Picked from what you haven't sat yet."
    : `Pitched around your first-try average of ${data.accuracy_pct}%.`;
}

/** Where "Browse all …" points the list. A filter, not a page: the reader is
 *  asking to see more of the same kind of thing, and taking them elsewhere to
 *  see it would throw away the search and the mode they are in. */
function browse(data: NextUpData): { label: string; scope: Scope } | null {
  if (data.reason === "weak_part" && data.part) {
    return { label: `Browse all Part ${data.part}`, scope: data.part as Scope };
  }
  if (data.reason === "steady") {
    return { label: "Browse full tests", scope: "full" };
  }
  return null;
}

export function NextUp({
  data,
  basePath,
  onBrowse,
  onCourses,
  onTypes,
}: {
  /** Where this paper's pages live. See PracticeRow. */
  basePath: string;
  data: NextUpData;
  /** Applies the block's own "browse all" to the list below it. */
  onBrowse: (scope: Scope) => void;
  /** Switches the list below to the courses shelf. A callback rather than a
   *  link because there is no page to go to: the shelf IS this page with the
   *  other tab selected, and navigating would be leaving somewhere to arrive
   *  back at it. */
  onCourses: () => void;
  /** Into the Question types tab. Like `onCourses`, it switches the list
   *  rather than navigating: the reader is asking to see more of the same
   *  kind of thing, and going somewhere would throw away their search. */
  onTypes: () => void;
}) {
  // Too little history to say anything, and silence is the answer rather than
  // a fallback: a recommendation off one paper is a guess in a confident
  // voice, and the reader cannot tell those apart.
  if (data.reason === "none") return null;
  if (data.reason === "finished_course" && data.collection) {
    return <Finished data={data} basePath={basePath} onCourses={onCourses} />;
  }
  if (data.reason === "course" && data.collection && data.items.length > 0) {
    return <CarryOn data={data} basePath={basePath} onCourses={onCourses} />;
  }
  if (data.reason === "task_type" && data.task_type && data.next_group_id) {
    return <CarryOnTask data={data} basePath={basePath} onTypes={onTypes} />;
  }
  // A suggestion with nothing to suggest is a heading over an empty box.
  if (data.items.length === 0) return null;
  return <Suggested data={data} basePath={basePath} onBrowse={onBrowse} />;
}

/**
 * Carrying on with a KIND of question rather than a course.
 *
 * Deliberately quieter than the course card beside it, and not because there
 * was less room: a course is a route somebody chose, drawn with its cover and
 * the lesson they are up to. A kind of question is a habit they fell into —
 * two maps last week — so the card reports it and offers the next one, and
 * does not dress it up as a syllabus. No cover, because there is no book.
 *
 * It only ever appears where the course card does not; the server settles
 * that, and the rule it follows is that a course outranks this.
 */
function CarryOnTask({
  data,
  basePath,
  onTypes,
}: {
  /** Where this paper's pages live. See PracticeRow. */
  basePath: string;
  data: NextUpData;
  onTypes: () => void;
}) {
  const family = familyOfType(data.task_type);
  if (!family) return null;
  const Icon = familyIcon(family);
  const of = data.of ?? 0;
  const done = data.done ?? 0;

  return (
    <Slot label="Carry on with a kind of question">
      <div className="flex items-center gap-4">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-surface-sunken">
          <Icon className="size-4 text-muted-foreground" aria-hidden />
        </span>

        <div className="min-w-0 flex-1">
          <p className="min-w-0 truncate text-xs text-muted-foreground">
            Carry on ·{" "}
            <button
              type="button"
              onClick={onTypes}
              className="text-foreground transition-colors hover:underline"
            >
              {family.label}
            </button>
          </p>
          <p className="mt-0.5 truncate text-sm text-foreground">
            <span className="tabular-nums text-muted-foreground">
              {done} of {of} done ·{" "}
            </span>
            {data.remaining ?? 0} left
          </p>
          {/* Green, never the accent — the accent is the button, and how far
              somebody has got is a report. The same bar the card on the tab
              draws, so the two agree at a glance. */}
          <span
            aria-hidden
            className="mt-1.5 block h-1 overflow-hidden rounded-full bg-border-subtle"
          >
            <span
              className="block h-full rounded-full bg-correct transition-[width] duration-base"
              style={{ width: `${Math.round((done / Math.max(1, of)) * 100)}%` }}
            />
          </span>
        </div>

        <div className="flex shrink-0 items-center gap-3">
          <Button
            type="button"
            variant="ghost"
            size="xs"
            onClick={onTypes}
            className="hidden px-0 text-xs text-muted-foreground hover:bg-transparent hover:text-foreground sm:inline-flex"
          >
            See all
          </Button>
          <Button asChild size="sm">
            <Link to={`${basePath}/drills/${data.next_group_id}`}>
              Continue
              <ArrowRight className="size-3.5" aria-hidden />
            </Link>
          </Button>
        </div>
      </div>
    </Slot>
  );
}

/** The shell all three states wear, so the slot keeps its shape. */
function Slot({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <section
      aria-label={label}
      className="mb-5 rounded-xl border border-border-subtle bg-card/40 p-3"
    >
      {children}
    </section>
  );
}

/** Cover, header line, progress bar — the half these two states share. */
function CourseHead({
  data,
  basePath,
  lead,
  right,
  children,
}: {
  /** Where this paper's pages live. See PracticeRow. */
  basePath: string;
  data: NextUpData;
  lead: React.ReactNode;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  const collection = data.collection!;
  const of = data.of ?? 0;
  const done = data.done ?? 0;

  return (
    <div className="flex gap-4">
      {/* The cover at a third the size and without its title — the course is
          named in full two words to the right, and at this width the title
          would be unreadable type competing with it. What survives is the
          colour and the pattern, which is what the reader recognises the book
          by in the first place. */}
      <Link
        to={`${basePath}/collections/${collection.id}`}
        tabIndex={-1}
        aria-hidden
        className="w-14 shrink-0 self-start"
      >
        <CollectionCover
          coverKey={coverKeyOf(collection)}
          title={collection.title}
          showTitle={false}
          className="shadow-[0_3px_8px_rgba(0,0,0,0.34)]"
        />
      </Link>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-baseline justify-between gap-3">
          {lead}
          {right}
        </div>

        <div
          className="mt-1.5 h-0.5 overflow-hidden rounded-full bg-foreground/10"
          role="progressbar"
          aria-valuenow={done}
          aria-valuemin={0}
          aria-valuemax={of}
          aria-label={`${done} of ${of} done`}
        >
          <div
            className="h-full rounded-full bg-correct transition-[width] duration-slow ease-out motion-reduce:transition-none"
            style={{ width: `${of > 0 ? Math.round((done / of) * 100) : 0}%` }}
          />
        </div>

        <div className="mt-2.5 flex items-end justify-between gap-4">
          {children}
        </div>
      </div>
    </div>
  );
}

// --- Carrying a course on ---------------------------------------------------

function CarryOn({
  data,
  basePath,
  onCourses,
}: {
  /** Where this paper's pages live. See PracticeRow. */
  basePath: string;
  data: NextUpData;
  onCourses: () => void;
}) {
  const collection = data.collection!;
  const next = data.items[0];

  return (
    <Slot label="Carry on with your course">
      <CourseHead
      basePath={basePath}
        data={data}
        lead={
          <p className="min-w-0 truncate text-xs text-muted-foreground">
            Carry on ·{" "}
            <Link
              to={`${basePath}/collections/${collection.id}`}
              className="text-foreground transition-colors hover:underline"
            >
              {collection.title}
            </Link>
          </p>
        }
        right={
          /* "2 left" rather than "4 of 6 done". Both are true — somebody who
             skipped a lesson is legitimately on lesson four with four done —
             but only one of them invites the reader to subtract and find an
             off-by-one that isn't there. The bar already says how far along
             they are. */
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
            {data.remaining ?? 0} left
          </span>
        }
      >
        <div className="min-w-0">
          {/* One lesson, not the rest of the course. Two rows under a
              Continue button leave the reader working out which one the
              button opens; one row cannot disagree with it. The rest is a
              click away on the course's own page. */}
          <p className="truncate text-sm text-foreground">
            {data.position != null && (
              <span className="text-muted-foreground">
                Lesson {data.position} ·{" "}
              </span>
            )}
            {next.title}
          </p>
          <div className="mt-1 flex items-center gap-2">
            <Meta material={next} />
            <span
              title={difficultyTitle(next)}
              className={cn(
                "shrink-0 rounded-full border px-2 py-0.5 text-xs font-medium",
                DIFFICULTY_CLASS[next.difficulty.band],
              )}
            >
              {DIFFICULTY_SHORT[next.difficulty.band]}
            </span>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-3">
          {/* Only where there is more than this one. "My courses (1)" is a
              link back to what you are already looking at. */}
          {data.in_progress_count > 1 && (
            <Button
              type="button"
              variant="ghost"
              size="xs"
              onClick={onCourses}
              className="hidden px-0 text-xs text-muted-foreground hover:bg-transparent hover:text-foreground sm:inline-flex"
            >
              My courses ({data.in_progress_count})
            </Button>
          )}
          <Link
            to={`${basePath}/collections/${collection.id}`}
            className="text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            View course
          </Link>
          <Button asChild size="sm">
            <Link to={`${basePath}/${next.id}`}>
              Continue
              <ArrowRight className="size-3.5" aria-hidden />
            </Link>
          </Button>
        </div>
      </CourseHead>
    </Slot>
  );
}

// --- Having just finished one -----------------------------------------------

function Finished({
  data,
  basePath,
  onCourses,
}: {
  /** Where this paper's pages live. See PracticeRow. */
  basePath: string;
  data: NextUpData;
  onCourses: () => void;
}) {
  const collection = data.collection!;
  const of = data.of ?? 0;

  return (
    <Slot label="You finished a course">
      <CourseHead
      basePath={basePath}
        data={data}
        lead={
          <p className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
            <Check className="size-3.5 shrink-0 text-correct" aria-hidden />
            <span className="truncate">
              <span className="text-foreground">{collection.title}</span> —
              finished
            </span>
          </p>
        }
      >
        <p className="min-w-0 text-sm text-foreground">
          All {of} lesson{of === 1 ? "" : "s"} done
          {/* Only where there is one. A course of materials nobody has scored
              has no average, and inventing one would be the first dishonest
              number on a page full of guarded ones. */}
          {data.accuracy_pct !== null && (
            <span className="text-muted-foreground">
              {" · "}
              <span className="tabular-nums">{data.accuracy_pct}%</span> on
              first try
            </span>
          )}
        </p>
        <div className="flex shrink-0 items-center gap-3">
          <Link
            to={`${basePath}/statistics`}
            className="text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            See your results
          </Link>
          <Button type="button" size="sm" variant="outline" onClick={onCourses}>
            Find another course
            <ArrowRight className="size-3.5" aria-hidden />
          </Button>
        </div>
      </CourseHead>
    </Slot>
  );
}

// --- Being suggested something ----------------------------------------------

function Suggested({
  data,
  basePath,
  onBrowse,
}: {
  data: NextUpData;
  basePath: string;
  onBrowse: (scope: Scope) => void;
}) {
  const more = browse(data);

  return (
    <Slot label="Suggested materials">
      <div className="flex items-baseline justify-between gap-4">
        <p className="min-w-0 text-xs">
          <span className="text-muted-foreground">Suggested for you · </span>
          <span className="text-foreground">{heading(data)}</span>
        </p>
        {more && (
          <Button
            type="button"
            variant="ghost"
            size="xs"
            onClick={() => onBrowse(more.scope)}
            className="shrink-0 px-0 text-xs text-muted-foreground hover:bg-transparent hover:text-foreground"
          >
            {more.label}
            <ArrowRight className="size-3" aria-hidden />
          </Button>
        )}
      </div>

      {/* Tiles rather than rows. As rows they were the same shape as the
          catalogue underneath, and somebody scanning down the page read them
          as its first three entries — a suggestion that looks like the list
          is not a suggestion. Side by side they are plainly a different
          thing.

          Not an ordered list: three suggestions are a set, and nothing says
          sit them in this order. */}
      <ul className="mt-2.5 grid gap-2 sm:grid-cols-3">
        {data.items.map((m) => (
          <li key={m.id}>
            <Tile material={m} basePath={basePath} />
          </li>
        ))}
      </ul>
    </Slot>
  );
}

function Tile({
  material: m,
  basePath,
}: {
  material: PracticeMaterial;
  basePath: string;
}) {
  return (
    <Link
      to={`${basePath}/${m.id}`}
      className="block rounded-lg bg-surface-sunken px-3 py-2.5 transition-colors duration-fast hover:bg-surface-hover focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      <p className="truncate text-sm text-foreground">{m.title}</p>
      <div className="mt-1.5 flex items-center justify-between gap-2">
        <Meta material={m} />
        <span
          title={difficultyTitle(m)}
          className={cn(
            "shrink-0 rounded-full border px-2 py-0.5 text-xs font-medium",
            DIFFICULTY_CLASS[m.difficulty.band],
          )}
        >
          {DIFFICULTY_SHORT[m.difficulty.band]}
        </span>
      </div>
    </Link>
  );
}

/** The one line of what a material is. Shared by the tile and the carry-on
 *  row, so the two describe a paper the same way. */
function Meta({ material: m }: { material: PracticeMaterial }) {
  const task = describeTask(m);
  const bits = [
    partLabel(m),
    task?.label,
    m.duration_ms != null ? fmtClock(m.duration_ms) : null,
  ];
  return (
    <p className="min-w-0 truncate text-xs text-muted-foreground">
      {bits.filter(Boolean).join(" · ")}
    </p>
  );
}

/**
 * The slot, waiting.
 *
 * Present at all because this sits ABOVE the list: a block that appeared once
 * loaded would push the whole catalogue down the page under the reader's
 * pointer. Built to the carry-on shape, which is the tallest of the three, so
 * nothing moves upward when the real one arrives either.
 */
export function NextUpSkeleton() {
  return (
    <section
      aria-hidden
      className="mb-5 rounded-xl border border-border-subtle bg-card/40 p-3"
    >
      <div className="flex gap-4">
        <div className="w-14 shrink-0">
          {/* The cover's own viewBox holds the ratio, exactly as the real
              one does — so the slot reserves the height the book will take
              without anybody writing that height down twice. */}
          <svg
            viewBox="0 0 156 214"
            className="block h-auto w-full rounded-l-sm rounded-r-md"
            aria-hidden
          >
            <rect width={156} height={214} className="fill-foreground/10" />
          </svg>
        </div>
        <div className="flex min-w-0 flex-1 flex-col">
          <p className="text-xs">
            <Skeleton className="inline-block h-[0.8em] w-48 max-w-full" />
          </p>
          <div className="mt-1.5 h-0.5 rounded-full bg-foreground/10" />
          <div className="mt-2.5">
            <p className="text-sm">
              <Skeleton className="inline-block h-[0.8em] w-64 max-w-full" />
            </p>
            <p className="mt-1 text-xs">
              <Skeleton className="inline-block h-[0.8em] w-40" />
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
