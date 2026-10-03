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
 * The tag is small dim mono: part of speech, then ONE marker. `used here`
 * (popover) and `saved` (word page) replace nothing on the page word-wise
 * but outrank the frequency label, which is general knowledge where they
 * are the answer to the question asked. No label where the server sent
 * none; no numbers, ever.
 */
function marker(sense: WordSense): string | null {
  if (sense.used_here) return "used here";
  if (sense.saved) return "saved";
  return sense.label;
}

/** `n · used here` — inline, so it costs no line of its own. */
export function SenseTag({
  sense,
  className,
}: {
  sense: WordSense;
  className?: string;
}) {
  const parts = [sense.pos, marker(sense)].filter(Boolean);
  if (parts.length === 0) return null;
  return (
    <span
      className={cn(
        "font-mono text-[0.62rem] leading-none text-muted-foreground/70",
        className,
      )}
    >
      {parts.join(" · ")}
    </span>
  );
}

/** A sense in full: definition, then Uzbek. */
export function SenseOpen({
  sense,
  roomy = false,
}: {
  sense: WordSense;
  roomy?: boolean;
}) {
  return (
    <>
      <p
        className={cn(
          "leading-snug text-foreground",
          roomy ? "text-sm" : "text-[0.82rem]",
        )}
      >
        <SenseTag sense={sense} className="mr-1.5 align-[0.08em]" />
        {sense.definition_en}
        <CefrTag level={sense.cefr} className="ml-1.5 align-[0.1em]" />
      </p>
      {sense.meaning_uz && (
        <p
          className={cn(
            "mt-1 leading-snug text-muted-foreground",
            roomy ? "text-sm" : "text-[0.8rem]",
          )}
        >
          {sense.meaning_uz}
        </p>
      )}
    </>
  );
}

/**
 * One line: the start of the definition and the tag; pressing opens it. The
 * full text lives in a sibling panel, never inside the button (flow content
 * is invalid there, and the button's name would become the whole text).
 */
function SenseRow({ sense }: { sense: WordSense }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return (
    <li className="border-t border-border/60 first:border-t-0">
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
            "size-3 shrink-0 self-center text-muted-foreground/70 transition-transform",
            open && "rotate-90",
          )}
        />
        <span
          className={cn(
            "min-w-0 flex-1 truncate text-[0.78rem] text-foreground/85",
            open && "sr-only",
          )}
        >
          {sense.definition_en}
        </span>
        {open ? (
          <span
            className="flex-1 text-[0.62rem] leading-none text-transparent select-none"
            aria-hidden
          >
            &nbsp;
          </span>
        ) : (
          <SenseTag sense={sense} className="shrink-0" />
        )}
      </button>
      <div id={panelId} hidden={!open} className="pb-1 pl-[1.125rem]">
        {open && <SenseOpen sense={sense} />}
      </div>
    </li>
  );
}

const COLLAPSED_ROWS = 1;

/**
 * The popover's senses: the first is drawn by the caller, in full, exactly
 * as the single meaning always was. These are the rest — ONE line shows,
 * and anything past it waits behind `show all (N)`. One rather than two
 * keeps a many-sense word about as tall as the old card with its `Here:`
 * block (measured: two lines added ~70–100px; the popover was rejected once
 * for growing).
 */
export function SenseRows({ senses }: { senses: WordSense[] }) {
  const [all, setAll] = useState(false);
  const rest = senses.slice(1);
  const shown = all ? rest : rest.slice(0, COLLAPSED_ROWS);
  if (rest.length === 0) return null;
  return (
    <div className="mt-1.5 border-t border-border pt-0.5">
      <ul aria-label="Other meanings">
        {shown.map((s) => (
          <SenseRow key={s.sense_id} sense={s} />
        ))}
      </ul>
      {!all && rest.length > COLLAPSED_ROWS && (
        <button
          type="button"
          aria-expanded={false}
          onClick={() => setAll(true)}
          className="w-full rounded border-t border-border/60 py-1 text-left font-mono text-[0.68rem] text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          show all ({senses.length})
        </button>
      )}
    </div>
  );
}

/** The word page's senses: all open, nothing to press. */
export function SenseList({ senses }: { senses: WordSense[] }) {
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
          <SenseOpen sense={s} roomy />
        </li>
      ))}
    </ul>
  );
}
