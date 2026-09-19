import { cn } from "@/lib/utils";
import { COVER_INK } from "@/features/paper/cover";
import { LISTENING, READING } from "@/features/paper/skill";
import { CollectionCover } from "@/features/listening/components/CollectionBook";

/**
 * A collection as the studio prints it: the shared cover, with the author's
 * two facts across its foot — how much is in it, and whether it is out.
 *
 * The count is preceded by the exam's own glyph, because the shelf holds
 * both and a course is a sequence through ONE of them. A word would not fit:
 * the foot has to hold a count and a plate side by side on one row, and it
 * is what fixes the column count at four (see `pages/studio/CLAUDE.md`). A
 * glyph is the vocabulary the rest of the app already uses for the same
 * distinction — the nav, the tabs and the practice cards all name these two
 * papers this way.
 *
 * One implementation, two sizes. The shelf shows it at a book's width and
 * the editor shows the same book beside the title being typed, so an author
 * who opens a course recognises the object they clicked. Two copies of this
 * markup would be two books that drift apart the first time either is
 * touched.
 *
 * `compact` is the editor's 104px cut. Only the type and the insets change —
 * the cover itself scales from its own viewBox — because at that width the
 * shelf's sizes would take the foot onto two lines, which is the bug this
 * layout was already fixed for once.
 */
export function StudioCollectionCover({
  coverKey,
  title,
  count,
  published,
  skill,
  compact,
  className,
}: {
  coverKey: string;
  title: string;
  /** Items the AUTHOR put in, drafts included — never the public count. */
  count: number;
  published: boolean;
  /** Which paper it is a course in. */
  skill: "listening" | "reading";
  compact?: boolean;
  className?: string;
}) {
  const Glyph = (skill === "reading" ? READING : LISTENING).icon;
  return (
    <div
      className={cn(
        // A literal shadow: this is the object's weight, and there is no
        // token for "this is a thing".
        "relative shadow-[0_6px_14px_rgba(0,0,0,0.32)]",
        className,
      )}
    >
      <CollectionCover coverKey={coverKey} title={title} compact={compact} />

      <div
        className={cn(
          "absolute flex items-baseline justify-between gap-2",
          compact ? "right-2.5 bottom-2.5 left-4" : "right-4 bottom-3 left-5",
        )}
      >
        {/* One line, always. `truncate` rather than a wrap: two rows here
            lift the count off the plate's baseline and the foot stops being
            a line at all. */}
        <span
          className={cn(
            "flex min-w-0 items-center gap-1 truncate whitespace-nowrap tabular-nums",
            compact ? "text-[0.5625rem]" : "text-[0.6875rem]",
          )}
          style={{ color: COVER_INK.byline }}
        >
          <Glyph
            className={cn("shrink-0", compact ? "size-2.5" : "size-3")}
            aria-hidden
          />
          {/* "Empty" rather than "0 materials": a zero next to a word is a
              measurement, and this is a state — the one the author has to do
              something about. */}
          {count === 0 ? "Empty" : `${count} material${count === 1 ? "" : "s"}`}
        </span>

        {/* Half-transparent black over whichever stock this book was dealt —
            see COVER_INK.plate for why it is not a colour of its own. Draft
            prints amber because it is the state that wants an action; public
            is the quiet one. */}
        <span
          className={cn(
            "shrink-0 rounded-full",
            compact
              ? "px-1.5 py-px text-[0.5rem]"
              : "px-2 py-0.5 text-[0.6875rem]",
          )}
          style={{
            backgroundColor: COVER_INK.plate,
            color: published ? COVER_INK.plateText : COVER_INK.plateWarn,
          }}
        >
          {published ? "Public" : "Draft"}
        </span>
      </div>
    </div>
  );
}
