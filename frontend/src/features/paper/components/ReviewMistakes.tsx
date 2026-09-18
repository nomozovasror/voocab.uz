import { cn } from "@/lib/utils";
import {
  MISTAKE_LABEL,
  mistakeAdvice,
  mistakePhrase,
} from "@/features/listening/practice";
import type { MistakeKind } from "@/features/paper/types";

/**
 * Where the marks went on this paper.
 *
 * **At the bottom, after the questions.** It is the summary of what is above
 * it, and a summary printed first is a page the reader has to scroll past to
 * reach what they came for — which on a review is the mistakes themselves.
 * The chart answers "was there a pattern"; that is a question somebody asks
 * once they have read the twelve rows, not before.
 *
 * The same six kinds under the same names as the practice page's "Where you
 * lose marks", and that is a requirement rather than a coincidence: the
 * sidebar's figure is this one aggregated over many papers, so a slip called
 * "Spelling" here and "Wrong answer" there would leave the reader unable to
 * trust either. Both come from one classifier on the server
 * (`backend/app/services/mistakes.py`) and share `MISTAKE_LABEL`.
 *
 * No threshold here, unlike the sidebar. Over a career four mistakes are not
 * a pattern and the panel says so; over ONE paper four mistakes are the whole
 * of what happened, and somebody reading their own attempt is entitled to see
 * them broken down however few there are.
 *
 * Letter-answered questions are absent by construction — the server sends no
 * kind for them, because there is no spelling in "b" and filing every wrong
 * letter under "Wrong answer" would inflate one bar with the one thing this
 * panel cannot explain.
 */
export function ReviewMistakes({
  groups,
  skill = "listening",
  className,
}: {
  groups: { kind: MistakeKind; count: number }[];
  /** Which paper this was, because half the advice names what to do next and
   *  that is different on a paper you read. */
  skill?: string;
  className?: string;
}) {
  if (!groups.length) return null;

  return (
    <section
      aria-label="Where the marks went"
      className={cn("border-t border-border pt-5", className)}
    >
      <h2 className="mb-3 text-xs tracking-caps uppercase text-muted-foreground">
        Where the marks went
      </h2>
      {groups.length === 1 ? (
        <OneKind kind={groups[0].kind} count={groups[0].count} skill={skill} />
      ) : (
        <Breakdown groups={groups} />
      )}
    </section>
  );
}

/**
 * Everything went the same way, so there is no breakdown to draw.
 *
 * A chart of one bar at 100% is a shape that says nothing: there is nothing
 * to compare it against, and the bar and the count together carry no more
 * than the sentence does. The sentence carries more, in fact — it can name
 * what to do about it, and what to do is not the same for every kind.
 * "Listen to those moments again" is right for an answer that went past
 * somebody and exactly wrong for one they heard and misspelled, who needs to
 * read their sheet back rather than play the recording a fourth time.
 */
function OneKind({
  kind,
  count,
  skill,
}: {
  kind: MistakeKind;
  count: number;
  skill: string;
}) {
  const many = count > 1;
  return (
    <p className="text-sm leading-normal text-muted-foreground">
      {/* "All three marks went to" is only true of more than one. One mistake
          is one mistake, and saying "all one" of them is the page counting
          out loud. */}
      {many ? `All ${word(count)} marks went to ` : "Your one mistake was "}
      <span className="text-foreground">{mistakePhrase(kind, many)}</span> —{" "}
      {mistakeAdvice(skill)[kind]}.
    </p>
  );
}

/** Small counts read as words in a sentence and as digits in a table, and
 *  this is a sentence. Past ten the word is longer than the number is
 *  informative. */
const TEN = [
  "one",
  "two",
  "three",
  "four",
  "five",
  "six",
  "seven",
  "eight",
  "nine",
  "ten",
];

function word(n: number): string {
  return n <= TEN.length ? TEN[n - 1] : String(n);
}

function Breakdown({
  groups,
}: {
  groups: { kind: MistakeKind; count: number }[];
}) {
  const most = groups[0].count;
  return (
    <ul className="space-y-1.5">
      {groups.map((group) => (
        <li key={group.kind} className="flex items-center gap-3 text-sm">
          <span className="min-w-0 flex-1 truncate text-foreground/80">
            {MISTAKE_LABEL[group.kind]}
          </span>
          {/* Bars against the BIGGEST kind, not against the total — the
              question this list answers is "which of these is the one", and
              proportions of a whole make every slice look small. Same choice
              as the sidebar's, so the two read alike. */}
          <span className="h-1.5 w-20 shrink-0 overflow-hidden rounded-full bg-surface-sunken">
            <span
              className={cn(
                "block h-full rounded-full",
                group.kind === groups[0].kind
                  ? "bg-incorrect"
                  : "bg-foreground/40",
              )}
              style={{ width: `${Math.round((group.count / most) * 100)}%` }}
            />
          </span>
          <span className="w-5 shrink-0 text-right tabular-nums text-muted-foreground">
            {group.count}
          </span>
        </li>
      ))}
    </ul>
  );
}
