import { useId, useState } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { CefrTag } from "@/features/vocabulary/components/CefrTag";
import type { WordSense } from "@/features/vocabulary/types";

/**
 * Every sense we have for a word — see `features/vocabulary/CLAUDE.md`
 * ("Lookup shows every sense") for why. A wrong pick of the first sense is
 * an ordering, not an answer.
 *
 * ONE place for the tag, on every sense: the right end of its first line,
 * small dim mono, never before the definition (the popover was rejected for
 * noise twice, and tags in three places was most of it). And nothing the
 * header already said: a sense's part of speech is printed only where it
 * differs from the header's, its CEFR chip only where it differs from the
 * header's level. No label where the server sent none; no numbers, ever.
 */
function marker(sense: WordSense): string | null {
  if (sense.used_here) return "used here";
  if (sense.saved) return "saved";
  return sense.label;
}

/** `n · used here` — a flex item at the end of the line, never inline text. */
export function SenseTag({
  sense,
  showPos,
  className,
}: {
  sense: WordSense;
  /** Only where the part of speech tells senses apart. */
  showPos: boolean;
  className?: string;
}) {
  const parts = [showPos ? sense.pos : null, marker(sense)].filter(Boolean);
  if (parts.length === 0) return null;
  return (
    <span
      className={cn(
        "shrink-0 font-mono text-[0.62rem] leading-none text-muted-foreground/70",
        className,
      )}
    >
      {parts.join(" · ")}
    </span>
  );
}

/** The Uzbek, and the sense's level only where it is not the header's. */
function SenseUz({
  sense,
  level,
  roomy,
}: {
  sense: WordSense;
  level: string | null | undefined;
  roomy: boolean;
}) {
  const chip = sense.cefr && sense.cefr !== level ? sense.cefr : null;
  if (!sense.meaning_uz && !chip) return null;
  return (
    <p
      className={cn(
        "mt-1 leading-snug text-muted-foreground",
        roomy ? "text-sm" : "text-[0.8rem]",
      )}
    >
      {sense.meaning_uz}
      <CefrTag level={chip} className={sense.meaning_uz ? "ml-1.5 align-[0.1em]" : ""} />
    </p>
  );
}

/**
 * A sense in full: the definition with its tag at the right end of that
 * line, then the Uzbek. `tagged` is false for a word with ONE sense — there
 * is nothing to tell it from, so it carries no tag at all.
 */
export function SenseOpen({
  sense,
  level,
  showPos = false,
  tagged = true,
  roomy = false,
}: {
  sense: WordSense;
  /** The header's CEFR level; a chip is drawn only where this sense differs. */
  level?: string | null;
  showPos?: boolean;
  tagged?: boolean;
  roomy?: boolean;
}) {
  return (
    <>
      <p className="flex items-baseline gap-2">
        <span
          className={cn(
            "min-w-0 flex-1 leading-snug text-foreground",
            roomy ? "text-sm" : "text-[0.82rem]",
          )}
        >
          {sense.definition_en}
        </span>
        {tagged && <SenseTag sense={sense} showPos={showPos} />}
      </p>
      <SenseUz sense={sense} level={level} roomy={roomy} />
    </>
  );
}

/**
 * One row, one disclosure. The chevron, the definition and the tag are one
 * line; pressing opens the SAME definition to wrap in full right there (a
 * `<span>` — phrasing content, valid in a button), and only what was not
 * on the line (the Uzbek, a differing level) goes in the sibling panel.
 * The tag stays at the right end either way.
 */
function SenseRow({
  sense,
  level,
  showPos,
}: {
  sense: WordSense;
  level: string | null | undefined;
  showPos: boolean;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return (
    <li>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-baseline gap-1.5 rounded py-1 text-left focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <ChevronRight
          aria-hidden
          className={cn(
            "mt-[3px] size-3 shrink-0 self-start text-muted-foreground/70 transition-transform",
            open && "rotate-90",
          )}
        />
        <span
          className={cn(
            "min-w-0 flex-1 text-[0.78rem] leading-snug",
            open ? "text-foreground" : "truncate text-foreground/85",
          )}
        >
          {sense.definition_en}
        </span>
        <SenseTag sense={sense} showPos={showPos} />
      </button>
      <div id={panelId} hidden={!open} className="pb-1 pl-[1.125rem]">
        {open && <SenseUz sense={sense} level={level} roomy={false} />}
      </div>
    </li>
  );
}

const COLLAPSED_ROWS = 1;

/**
 * The popover's senses: the first is drawn by the caller, in full. These are
 * the rest — ONE line shows, and anything past it waits behind `show all
 * (N)`. One rather than two keeps a many-sense word about as tall as the old
 * card with its `Here:` block. A single rule above them separates them from
 * the first sense; between rows there is spacing, not lines.
 */
export function SenseRows({
  senses,
  level,
  headerPos,
}: {
  senses: WordSense[];
  level?: string | null;
  headerPos?: string | null;
}) {
  const [all, setAll] = useState(false);
  const rest = senses.slice(1);
  const shown = all ? rest : rest.slice(0, COLLAPSED_ROWS);
  if (rest.length === 0) return null;
  return (
    <div className="mt-1.5 border-t border-border pt-0.5">
      <ul aria-label="Other meanings" className="space-y-0.5">
        {shown.map((s) => (
          <SenseRow
            key={s.sense_id}
            sense={s}
            level={level}
            showPos={Boolean(s.pos) && s.pos !== headerPos}
          />
        ))}
      </ul>
      {!all && rest.length > COLLAPSED_ROWS && (
        <button
          type="button"
          aria-expanded={false}
          onClick={() => setAll(true)}
          className="w-full rounded py-1 text-left font-mono text-[0.68rem] text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          show all ({senses.length})
        </button>
      )}
    </div>
  );
}

/**
 * The word page's senses: all open, nothing to press. Part of speech is
 * printed only where the lemma has more than one among its senses.
 */
export function SenseList({
  senses,
  level,
}: {
  senses: WordSense[];
  level?: string | null;
}) {
  const showPos = new Set(senses.map((s) => s.pos).filter(Boolean)).size > 1;
  return (
    <ul className="mt-2 space-y-2">
      {senses.map((s) => (
        <li
          key={s.sense_id}
          className={cn(
            "rounded-lg border px-3.5 py-2.5",
            s.saved ? "border-primary/40 bg-primary/5" : "border-border/60",
          )}
        >
          <SenseOpen sense={s} level={level} showPos={showPos} roomy />
        </li>
      ))}
    </ul>
  );
}
