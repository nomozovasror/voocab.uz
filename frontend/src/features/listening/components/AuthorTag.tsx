import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { AuthorSummary } from "@/features/listening/practice";
import type { CatalogueAuthor } from "@/features/paper/types";

/**
 * Who wrote it, at the end of a catalogue row's meta line.
 *
 * Small on purpose — 20px and inline, sharing the line with the question
 * count and the clock. A byline is context for a decision that is being made
 * about the material, so it goes where the rest of the context is; the moment
 * it gets its own row and a 40px picture, the page is about the authors.
 */

/** A hue from the author's id: the same person is the same colour on every
 *  row, on every visit, without anything being stored.
 *
 *  A hash rather than a palette index so adding authors never re-colours the
 *  existing ones — with `authors.length % 5` everybody shifts the day
 *  somebody signs up. */
function hueFor(id: string): number {
  let hash = 0;
  for (let i = 0; i < id.length; i += 1) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  }
  // 360 stops rather than a handful of buckets: two authors sharing a hue is
  // harmless, and the alternative is a visibly repeating palette.
  return hash % 360;
}

export function AuthorAvatar({
  author,
  className,
}: {
  author: CatalogueAuthor;
  className?: string;
}) {
  if (author.avatar_url) {
    return (
      <img
        src={author.avatar_url}
        alt=""
        loading="lazy"
        className={cn("size-5 rounded-full object-cover", className)}
      />
    );
  }
  // The one place in this feature that sets a colour outside the token set,
  // and it has to: a per-author tint is derived from data, so there is no
  // token it could be.
  //
  // Mixed toward the theme's own foreground rather than pinned to a fixed
  // lightness, which is what keeps it legible in all three themes: on a dark
  // ground the mix lightens the letter, on a light ground it darkens it, and
  // the hue — the only part that identifies the author — survives both. It is
  // never the sole carrier of the information anyway; the name is beside it.
  const hue = hueFor(author.id);
  return (
    <span
      aria-hidden
      style={{
        backgroundColor: `color-mix(in srgb, hsl(${hue} 60% 50%) 22%, transparent)`,
        color: `color-mix(in srgb, hsl(${hue} 70% 50%) 65%, var(--foreground))`,
      }}
      className={cn(
        "flex size-5 shrink-0 items-center justify-center rounded-full text-xs font-medium",
        className,
      )}
    >
      {author.display_name.charAt(0).toUpperCase()}
    </span>
  );
}

/** Avatar and name as one unbreakable unit — they are one thing to read, and
 *  a meta line that wraps between them reads as two. */
export function AuthorTag({
  author,
  summary,
}: {
  author: CatalogueAuthor;
  /** What else they have written. Absent — nobody counted — and the byline is
   *  just a byline: a tooltip that opened on nothing would be a promise of
   *  detail that isn't there. */
  summary?: AuthorSummary;
}) {
  const tag = (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <AuthorAvatar author={author} />
      {author.display_name}
    </span>
  );

  if (!summary) return tag;

  return (
    <Tooltip>
      {/* asChild onto the span, and not for style: this byline lives inside
          the row's <a>, and Radix's default trigger is a <button> — a button
          inside a link is markup no browser agrees on how to treat. The span
          is not focusable, which is correct here rather than a compromise:
          the row itself takes the focus, and the column beside the list
          already says all of this and more when the row is focused. */}
      <TooltipTrigger asChild>{tag}</TooltipTrigger>
      <TooltipContent side="top" className="w-64">
        <AuthorCard author={author} summary={summary} />
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * The byline, opened up.
 *
 * Bigger is most of the point — 36px of avatar and the name at reading size,
 * where the row has 20px and a caption. The rest is the two facts the page
 * can stand behind: how much they have written, and how much of it this
 * reader has sat.
 *
 * Both are counted by the server over the whole library and carried on the
 * row. They used to be counted here, over the catalogue the page had — which
 * stopped being the catalogue the day the list started arriving a page at a
 * time, and "4 materials here" under a name has to mean four. What is
 * deliberately NOT here is the rest of what was tried on the aside's author
 * card — the parts they favour, the difficulty they land on, their total
 * question count. All true, none of it any help in deciding whether to sit
 * the material the pointer is on.
 */
function AuthorCard({
  author,
  summary,
}: {
  author: CatalogueAuthor;
  summary: AuthorSummary;
}) {
  const { materials, done } = summary;
  return (
    <div className="flex items-center gap-3">
      <AuthorAvatar author={author} className="size-9 text-base" />
      <div className="min-w-0">
        <p className="truncate text-sm text-foreground">
          {author.display_name}
        </p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          <span className="tabular-nums">{materials}</span> material
          {materials === 1 ? "" : "s"} here
          {/* Only once there is something to report. "0 done" under a name is
              a scoreboard nobody asked for, on the first material they have
              ever seen from this author. */}
          {done > 0 && (
            <>
              {" · "}
              <span className="tabular-nums">{done}</span> sat by you
            </>
          )}
        </p>
      </div>
    </div>
  );
}
