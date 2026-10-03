import { useId, useState } from "react";
import { cn } from "@/lib/utils";
import { CefrTag } from "@/features/vocabulary/components/CefrTag";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { SenseLabel, WordSense } from "@/features/vocabulary/types";

/**
 * Every sense we have for a word — see `features/vocabulary/CLAUDE.md`
 * ("Lookup shows every sense", "The lookup card's shape") for why and for the
 * rules this file owns.
 *
 * The shape, in one paragraph: the sense that matters (used here / saved) is
 * a block with an accent rail on its left; the others stand flush with that
 * rail under a labelled divider; the meter is right-aligned ON THE UZBEK LINE
 * of the first sense, or on the definition line of each other row. No rules
 * between senses.
 */

/**
 * Wire -> frequency level, in ONE place, feeding the three-dot meter.
 * `most common` = 3 dots, `common` = 2, `less common` = 1 (read aloud as
 * "rare"). `usual` is never used: it is nearly a synonym of `common` and does
 * not say which ranks higher. `null` is DELIBERATELY blank (no dots at all) —
 * about three thousand senses have no SemCor data, and a guessed level would
 * hide a difference that matters to us and not to the learner.
 */
export interface Freq {
  filled: 1 | 2 | 3;
  name: "most common" | "common" | "rare";
}

const FREQ: Record<SenseLabel, Freq> = {
  "most common": { filled: 3, name: "most common" },
  common: { filled: 2, name: "common" },
  "less common": { filled: 1, name: "rare" },
};

export function senseLabel(label: SenseLabel | null | undefined): Freq | null {
  return label ? (FREQ[label] ?? null) : null;
}

/** Three dots: filled = how common. The colour is the label's (accent when
 *  lit, muted otherwise); the empty dots are a faint ring of it. The count of
 *  FILLED dots carries the meaning, so the ring may be quiet. */
/** What the dots mean, in words, under the pointer. Three dots are quick to
 *  scan and slow to decode the first time, so hovering says it plainly —
 *  still without a number, which would promise a precision SemCor's counts
 *  do not have. */
const METER_HINT: Record<Freq["name"], string> = {
  "most common": "The most common meaning",
  common: "A common meaning",
  rare: "A rarer meaning",
};

function Meter({ freq, lit = false }: { freq: Freq; lit?: boolean }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          role="img"
          aria-label={freq.name}
          className={cn(
            "inline-flex shrink-0 items-center gap-[3px]",
            lit ? "text-primary-ink" : "text-freq-dot",
          )}
        >
          {[1, 2, 3].map((i) => (
            <span
              key={i}
              aria-hidden
              className={cn(
                "size-[7px] rounded-full border border-current",
                i <= freq.filled ? "bg-current" : "opacity-40",
              )}
            />
          ))}
        </span>
      </TooltipTrigger>
      <TooltipContent side="top" className="px-2 py-1 font-mono text-[11px]">
        {METER_HINT[freq.name]}
      </TooltipContent>
    </Tooltip>
  );
}

/** `n` (mono, only where it differs from the header) then the meter,
 *  right-aligned, never inline text. `lit` is the accent colour: the sense
 *  used here (or saved), instead of writing it out. */
function Tag({
  pos,
  freq,
  lit = false,
  className,
}: {
  pos?: string | null;
  freq?: Freq | null;
  lit?: boolean;
  className?: string;
}) {
  if (!pos && !freq) return null;
  return (
    <span
      className={cn(
        "ml-auto flex shrink-0 items-center gap-2 whitespace-nowrap",
        className,
      )}
    >
      {pos && (
        <span
          className={cn(
            "font-mono text-[11px] leading-none tracking-[0.02em]",
            lit ? "text-primary-ink" : "text-muted-foreground",
          )}
        >
          {pos}
        </span>
      )}
      {freq && <Meter freq={freq} lit={lit} />}
    </span>
  );
}

/** The sense's own level, only where it is not the header's. */
function chipFor(sense: WordSense, level: string | null | undefined) {
  return sense.cefr && sense.cefr !== level ? sense.cefr : null;
}

/**
 * The sense that matters, with the accent rail: definition, then the Uzbek
 * with the tag at the far end of that line. Used for a lookup's first sense,
 * for a phrase or an old answer with no `senses`, and for the word page's
 * saved sense. `children` sit inside the rail (the passage's `Here:` gloss).
 *
 * The rail and the lit tag are the whole of "used here" / "saved" for the
 * eye; `marked` is the same fact for a screen reader, which cannot see a
 * colour.
 */
export function RailSense({
  en,
  uz,
  chip,
  pos,
  freq,
  marked,
  roomy = false,
  className,
  children,
}: {
  en: string;
  uz: string;
  chip?: string | null;
  /** Part of speech to print (only where it differs from the header's). */
  pos?: string | null;
  /** The frequency meter; null/absent = no dots. */
  freq?: Freq | null;
  /** Screen-reader-only statement of what the rail means. */
  marked?: string;
  roomy?: boolean;
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className={cn("border-l-2 border-primary pl-[11px]", className)}>
      {marked && <span className="sr-only">{marked}: </span>}
      <p className={cn("leading-[1.45] text-foreground", roomy ? "text-base" : "text-[14.5px]")}>
        {en}
        {/* On the DEFINITION, never beside the Uzbek: a chip after the
            translation read as the translation's level. */}
        <CefrTag level={chip} outline className="ml-2 align-[0.1em]" />
      </p>
      {(uz || pos || freq) && (
        <div className="mt-1 flex items-baseline gap-3">
          <span
            className={cn(
              "min-w-0 flex-1 leading-snug text-foreground/70",
              roomy ? "text-[15px]" : "text-[13.5px]",
            )}
          >
            {uz}
          </span>
          <Tag pos={pos} freq={freq} lit />
        </div>
      )}
      {children}
    </div>
  );
}

/** A lookup's first sense: the rail. A word with ONE sense has no tag at
 *  all — there is nothing to tell it from. */
export function PrimarySense({
  sense,
  level,
  headerPos,
  tagged,
  roomy,
  levels = false,
  children,
}: {
  sense: WordSense;
  level?: string | null;
  headerPos?: string | null;
  tagged: boolean;
  roomy?: boolean;
  /** Print the sense's own level where it differs from the header's. Off in
   *  the lookup card, which says ONE level — the header's, the same claim
   *  as the colour on the passage; the word page turns it on. */
  levels?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <RailSense
      en={sense.definition_en}
      uz={sense.meaning_uz}
      chip={levels ? chipFor(sense, level) : null}
      pos={tagged && sense.pos && sense.pos !== headerPos ? sense.pos : null}
      freq={tagged ? senseLabel(sense.label) : null}
      marked={sense.used_here ? "Used in this passage" : sense.saved ? "Saved" : undefined}
      roomy={roomy}
    >
      {children}
    </RailSense>
  );
}

/**
 * One of the other senses: the definition on one truncated line (the tag at
 * its right end), the Uzbek beneath it in a smaller dim sans. No level chip:
 * the card states one level, the header's. A disclosure button (`aria-expanded`/`aria-controls`) — pressing
 * lets the SAME definition wrap in full, the Uzbek staying beneath. No
 * chevron: hover and the focus ring say it is pressable, and a chevron alone
 * on a line is the shape that read as broken.
 */
function OtherRow({
  sense,
  showPos,
}: {
  sense: WordSense;
  showPos: boolean;
}) {
  const [open, setOpen] = useState(false);
  const defId = useId();
  return (
    <li>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={defId}
        onClick={() => setOpen((v) => !v)}
        className="block w-full rounded py-[5px] text-left transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <span
          className={cn(
            "flex items-baseline gap-3 text-[13.5px]",
            open ? "text-foreground" : "text-foreground/70",
          )}
        >
          <span id={defId} className={cn("min-w-0 flex-1", !open && "truncate")}>
            {sense.definition_en}
          </span>
          <Tag pos={showPos ? sense.pos : null} freq={senseLabel(sense.label)} />
        </span>
        {sense.meaning_uz && (
          <span className="mt-0.5 block text-[12.5px] leading-snug text-muted-foreground">
            {sense.meaning_uz}
          </span>
        )}
      </button>
    </li>
  );
}

/** Other senses visible before `show all (N)`. Two: each row is two lines
 *  now (definition + Uzbek) under a labelled divider, and three made a
 *  many-sense card ~90px taller than the old one. The user chose two. */
const VISIBLE_ROWS = 2;

/**
 * The popover's other senses (the first is the caller's `PrimarySense`):
 * under a labelled divider, left-aligned with the rail. `show all (N)`
 * counts ALL senses, the first included.
 */
export function OtherSenses({
  senses,
  headerPos,
}: {
  senses: WordSense[];
  headerPos?: string | null;
}) {
  const [all, setAll] = useState(false);
  const rest = senses.slice(1);
  if (rest.length === 0) return null;
  const shown = all ? rest : rest.slice(0, VISIBLE_ROWS);
  return (
    <div className="mt-[18px]">
      {/* The only line between senses: it LABELS the group, so it earns its
          place. Decorative to a screen reader; the list carries the name. */}
      <div aria-hidden className="mb-1 flex items-center gap-2">
        <span className="h-px w-3.5 bg-border" />
        <span className="font-mono text-[11px] text-muted-foreground">Other meanings</span>
        <span className="h-px flex-1 bg-border" />
      </div>
      <ul aria-label="Other meanings">
        {shown.map((s) => (
          <OtherRow
            key={s.sense_id}
            sense={s}
            showPos={Boolean(s.pos) && s.pos !== headerPos}
          />
        ))}
      </ul>
      {!all && rest.length > VISIBLE_ROWS && (
        <button
          type="button"
          aria-expanded={false}
          onClick={() => setAll(true)}
          className="block rounded pt-2 text-left font-mono text-[11.5px] text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          show all ({senses.length})
        </button>
      )}
    </div>
  );
}

/**
 * The word page's senses: the same structure with room. The saved sense
 * first, with the rail; then every other sense open, nothing truncated,
 * nothing to press, flush with the rail. Part of speech is printed only
 * where the lemma has more than one among its senses.
 */
export function SenseList({
  senses,
  level,
}: {
  senses: WordSense[];
  level?: string | null;
}) {
  const showPos = new Set(senses.map((s) => s.pos).filter(Boolean)).size > 1;
  const saved = senses.find((s) => s.saved);
  const rest = senses.filter((s) => s !== saved);
  return (
    <div className="mt-3">
      {saved && (
        <PrimarySense
          sense={saved}
          level={level}
          headerPos={showPos ? null : saved.pos}
          tagged
          roomy
          levels
        />
      )}
      <ul aria-label="Meanings" className={cn("space-y-[14px]", saved && "mt-[22px]")}>
        {rest.map((s) => {
          const chip = chipFor(s, level);
          return (
            <li key={s.sense_id}>
              <p className="text-[15px] leading-[1.45] text-foreground">
                {s.definition_en}
                <CefrTag level={chip} outline className="ml-2 align-[0.1em]" />
              </p>
              <div className="mt-1 flex items-baseline gap-3">
                <span className="min-w-0 flex-1 text-sm leading-snug text-foreground/70">
                  {s.meaning_uz}
                </span>
                <Tag pos={showPos ? s.pos : null} freq={senseLabel(s.label)} />
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
