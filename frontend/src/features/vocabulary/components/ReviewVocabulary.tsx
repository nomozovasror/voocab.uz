import { useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, GalleryHorizontal, Plus, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { toast } from "@/lib/toast";
import { getErrorMessage } from "@/lib/api";
import { vocabularyApi, vocabularyKey } from "@/features/vocabulary/api";
import {
  CEFR_LEVELS,
  CEFR_TONE,
  asLevel,
  levelRank,
  type CefrLevel,
} from "@/features/vocabulary/cefr";
import { CefrTag } from "@/features/vocabulary/components/CefrTag";
import { meanings } from "@/features/vocabulary/meaning";
import {
  isFiltering,
  keeps,
  toggleLevel,
  type WordFilter,
} from "@/features/vocabulary/filter";
import type {
  SavedWord,
  VocabularyEntry,
  VocabularyList,
} from "@/features/vocabulary/types";

/**
 * What this passage was worth learning, offered once it can no longer help.
 *
 * ## Why it is here and not anywhere else
 *
 * An IELTS teacher whose student struggles with a passage sets its vocabulary
 * as homework. That is the actual practice this automates, and it is the
 * single most valuable thing on this page after the mistakes — because the
 * words come out of a text the reader has just spent twenty minutes inside.
 * A word met in a passage somebody argued with is remembered; the same word
 * on a list of four hundred is not.
 *
 * It cannot be shown before the paper is submitted, and not only as a matter
 * of taste: the server refuses the list to anybody who has not finished
 * (`may_see_all`). Eighty-six glosses open mid-paper would make the three
 * lookups a formality.
 *
 * ## It is half of a pair now, not a section at the bottom of a page
 *
 * This used to be a bordered panel under the mistakes, and the list ran to
 * a hundred and one entries of four lines each — about ten screens of words
 * with no passage anywhere near them, which is a dictionary with the one
 * thing that made it worth reading taken out.
 *
 * Now it is one of two tabs beside the passage itself, and the passage is
 * marked with what this list is talking about. Pointing at an entry lights
 * the word where it stands in the text; pointing at the text lights the
 * entry. That is the whole argument for saving vocabulary from a paper
 * rather than from a list, made visible instead of written down.
 *
 * ## One bar, doing the work three headings used to
 *
 * The list was cut into sections: the looked-up words first under their own
 * heading, then the rest, then the B1 words folded into a `<details>`. Each
 * cut was defensible and together they were a page with four headings and
 * one opinion, and none of them could be UNDONE — a reader who wanted only
 * the C1 words had no way to ask for that, and one who wanted the easy
 * words had to find a disclosure triangle at the bottom.
 *
 * The proportional bar is the same information in a shape that can be
 * pressed. It is a legend (this is what B2 looks like), a distribution (this
 * passage is half B2 and a third C1 — before a word of the list is read),
 * and the filter, all in one object thirty-four pixels high. Chips would
 * have been the same control minus the distribution, which is the part
 * nothing else on the page says.
 *
 * **Nothing selected shows everything.** A filter that starts empty-handed
 * is a page that looks broken until it is understood.
 *
 * ## What survived the sections
 *
 * The looked-up words still come FIRST. They are not a subset worth a
 * badge, they are a different fact: every other word here is one the
 * frequency lists think is hard, and those two or three are the ones that
 * stopped THIS reader, mid-paper, badly enough to spend one of three on.
 * Nothing else on the platform knows which words those were. They now carry
 * that in a tag on the row and a toggle in the card instead of a heading
 * over a block, which costs a line and gains the ability to ask for them.
 *
 * Everything else is sorted by LEVEL, which is the opposite of the lookup
 * panel's passage order and right for the opposite reason: mid-paper the
 * question is "what does this one mean", and here it is "which of these
 * should I learn first".
 */

/** Which of the words a save just returned answers for THIS material's row.
 *
 *  `POST /vocabulary/words` still hands back the learner's whole list, not
 *  just what changed — the same shape `GET /vocabulary/words` returns — so a
 *  save has to pick its own row out of it. Lemma alone cannot: a learner who
 *  already keeps `bank` the river bank and has just saved `bank` the finance
 *  term now has two rows called `bank` in that list. Matching on a context
 *  from THIS material is what tells them apart, since only the row just
 *  created or touched carries one. */
function savedWordIdFor(
  words: SavedWord[],
  lemma: string,
  materialId: string,
): string | null {
  const found = words.find(
    (word) =>
      word.lemma === lemma &&
      word.contexts.some((ctx) => ctx.material_id === materialId),
  );
  return found?.id ?? null;
}

export function ReviewVocabulary({
  materialId,
  data,
  only,
  lookedUp,
  savedEarlier,
  lit,
  onPoint,
  filter,
  onFilter,
  onGoTo,
  className,
}: {
  materialId: string;
  /** The passage's words. Fetched by the PAGE rather than here, because the
   *  passage beside this list is marked from the same rows — and two
   *  components asking the same question of the same cache is one of them
   *  reading a copy it did not know it had. */
  data: VocabularyList;
  /** Which of them to show. `"saved"` is the Saved layer's panel: the same
   *  list with everything the learner has not met before taken out, and the
   *  same rows — a word they saved a fortnight ago and have just met again
   *  is not a different KIND of entry, it is the same entry with a history. */
  only?: "saved";
  /** The lemmas this attempt spent its lookups on, from the attempt itself.
   *  Empty for a sitting before the measurement existed, and for anybody who
   *  looked nothing up. */
  lookedUp: string[];
  /** Which were already on the learner's list when this page opened.
   *
   *  Not the same as `entry.saved`, which moves the moment somebody presses
   *  a button here. "Saved earlier" is a claim about a DIFFERENT DAY — you
   *  met this word a fortnight ago and here it is again — and a badge that
   *  appeared on a word two seconds after it was saved would be the page
   *  congratulating somebody on remembering what they just did. */
  savedEarlier: Set<string>;
  /** The lemma being pointed at, from either side. */
  lit: string | null;
  onPoint: (lemma: string | null) => void;
  /** Which words are being looked at. Held by the PAGE, because the same
   *  filter decides what the passage is marked with — see `filter.ts`. */
  filter: WordFilter;
  onFilter: (next: WordFilter) => void;
  /** Take the passage to a word. Pointing at a row lights the word where it
   *  stands, which is worth nothing when it stands four screens down — and
   *  in a list of a hundred, most of them do. */
  onGoTo: (lemma: string) => void;
  className?: string;
}) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const key = vocabularyKey(materialId);
  // This review page's own path — Browse's exit button reads it back as
  // `from`, so closing Browse returns HERE rather than wherever the
  // browser's history happened to hold (a bookmark or a shared link has
  // none to fall back on).
  const browseFrom = `${location.pathname}${location.search}`;

  const save = useMutation({
    mutationFn: (lemmas: string[]) => vocabularyApi.save(materialId, lemmas),
    // Marked saved in place rather than refetched. The server's answer is
    // the learner's whole list, which is not what this page is showing, and
    // a refetch of eighty-six rows to change one button is a page that
    // flickers every time somebody presses Save.
    onSuccess: (result, lemmas) => {
      qc.setQueryData<VocabularyList>(key, (was) =>
        was
          ? {
              ...was,
              entries: was.entries.map((entry) =>
                lemmas.includes(entry.lemma)
                  ? {
                      ...entry,
                      saved: true,
                      saved_word_id: savedWordIdFor(
                        result.words,
                        entry.lemma,
                        materialId,
                      ),
                    }
                  : entry,
              ),
            }
          : was,
      );
      // One toast whether this was the row's `＋` or "Save all 85" — a
      // learner who just pressed either has the same question, "where did
      // that go", and the practice module is the answer either way.
      toast({
        message: "Added to your words",
        kind: "success",
        action: { label: "Vocabulary", onClick: () => navigate("/vocabulary") },
      });
    },
    onError: (e) => toast(getErrorMessage(e)),
  });

  /** And off the list again.
   *
   *  By id, not by lemma — a saved word is one `LexemeSense` per learner
   *  now, so `bank` the finance term and `bank` the river bank are two rows
   *  and the ✕ on this one must remove only the sense this row is showing.
   *  Patched in place like the save, for the same reason — the server's
   *  answer is their entire list, which is not what this page is showing. */
  const drop = useMutation({
    mutationFn: (wordId: string) => vocabularyApi.forget(wordId),
    onSuccess: (_result, wordId) => {
      qc.setQueryData<VocabularyList>(key, (was) =>
        was
          ? {
              ...was,
              entries: was.entries.map((entry) =>
                entry.saved_word_id === wordId
                  ? { ...entry, saved: false, saved_word_id: null }
                  : entry,
              ),
            }
          : was,
      );
    },
    onError: (e) => toast(getErrorMessage(e)),
  });

  const opened = useMemo(() => new Set(lookedUp), [lookedUp]);

  const { base, shown, levels, openedCount, unusualCount } = useMemo(() => {
    const base =
      only === "saved" ? data.entries.filter((e) => e.saved) : data.entries;

    // Counted off the panel's OWN words rather than off `data.levels`, which
    // is the whole passage's. In the Saved panel those are two different
    // numbers, and a bar drawn from the wrong one would be a picture of a
    // list that is not on screen.
    const levels = {} as Record<CefrLevel, number>;
    for (const level of CEFR_LEVELS) levels[level] = 0;
    for (const entry of base) {
      const level = asLevel(entry.cefr_level);
      if (level) levels[level] += 1;
    }

    const shown = base
      .filter((entry) => keeps(filter, entry, (lemma) => opened.has(lemma)))
      .sort(
        (a, b) =>
          // The words that beat this reader, first. See the header comment:
          // it is the one ordering nothing else on the platform can make.
          Number(opened.has(b.lemma)) - Number(opened.has(a.lemma)) ||
          levelRank(a.cefr_level) - levelRank(b.cefr_level) ||
          a.paragraph_index - b.paragraph_index ||
          a.offset_start - b.offset_start,
      );

    return {
      base,
      shown,
      levels,
      openedCount: base.filter((e) => opened.has(e.lemma)).length,
      unusualCount: base.filter((e) => e.sense_differs).length,
    };
  }, [data, filter, only, opened]);

  const unsaved = shown.filter((entry) => !entry.saved);
  const filtering = isFiltering(filter);

  return (
    <section className={cn("min-w-0", className)}>
      <header className="rounded-xl bg-surface-sunken px-4 py-3">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          {only === "saved" ? (
            <>
              <div className="flex min-w-0 flex-1 items-baseline justify-between gap-3">
                <h2 className="text-sm font-semibold text-foreground">
                  {/* "words" stays plural either way: the list being counted
                      against is the learner's whole vocabulary, and "1 of
                      your saved word" is a sentence about nothing. */}
                  {base.length === 1 ? "One" : base.length} of your saved words{" "}
                  {base.length === 1 ? "is" : "are"} in this passage
                </h2>
                {/* Scoped to THIS material, per the brief's §C entry point 2
                 *  — never the whole saved list, which is what the words
                 *  page's own Browse button already offers. Not practice:
                 *  see `features/vocabulary/CLAUDE.md`. */}
                {base.length > 0 && (
                  <Link
                    to={`/vocabulary/browse?material=${materialId}&from=${encodeURIComponent(browseFrom)}`}
                    className="flex shrink-0 items-center gap-1.5 rounded-md bg-surface-hover px-2 py-1 text-xs font-medium text-foreground transition-colors duration-fast hover:bg-foreground/15 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                  >
                    <GalleryHorizontal className="size-3.5" aria-hidden />
                    Browse
                  </Link>
                )}
              </div>
              {/* The argument for the layer, said once. Meeting a word again
                  in a new context is the single most effective thing that can
                  happen to it, and it is the one thing on this page the
                  reader did not have to do anything to earn. */}
              <p className="text-xs text-muted-foreground">
                Met again, in a text you have just read closely.
              </p>
            </>
          ) : (
            <>
              <h2 className="text-sm font-semibold text-foreground">
                {data.total} words worth learning here
              </h2>
              {/* Said rather than discovered. A coloured bar reads as a
                  chart, and nothing about a chart suggests pressing it —
                  the one sentence is cheaper than the readers who never
                  find out the control is there. */}
              <p className="text-xs text-muted-foreground">
                click a level to filter
              </p>
            </>
          )}
        </div>

        <LevelBar levels={levels} chosen={filter.levels} onFilter={onFilter} />

        <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap gap-1.5">
            {openedCount > 0 && (
              <Toggle
                on={filter.lookedUp}
                onClick={() =>
                  onFilter({ ...filter, lookedUp: !filter.lookedUp })
                }
              >
                Looked up · {openedCount}
              </Toggle>
            )}
            {/* "Six of them are used in a sense that is not the word's
                usual one" — the nastiest kind of hard word, because nothing
                about it looks difficult and so nothing tells the reader
                there is anything to check. It was a clause in the subtitle;
                as a toggle it is the same fact and also a way to read the
                six. */}
            {unusualCount > 0 && (
              <Toggle
                on={filter.unusual}
                onClick={() => onFilter({ ...filter, unusual: !filter.unusual })}
              >
                Unusual · {unusualCount}
              </Toggle>
            )}
          </div>

          {/* One save button where there were three.
              "All of them", "just the C1" and "just my look-ups" were three
              buttons answering three questions the filter now answers
              itself — and answering them better, because the reader can see
              what they are about to save before they press it. What it
              saves is exactly what is on screen. */}
          {only !== "saved" && unsaved.length > 0 && (
            <button
              type="button"
              disabled={save.isPending}
              onClick={() => save.mutate(unsaved.map((entry) => entry.lemma))}
              className="flex items-center gap-1 rounded-md bg-surface-hover px-2.5 py-1 text-xs text-foreground transition-colors duration-fast hover:bg-foreground/15 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50"
            >
              <Plus className="size-3" aria-hidden />
              {filtering ? "Save these" : "Save all"} {unsaved.length}
            </button>
          )}
        </div>
      </header>

      {shown.length > 0 ? (
        <ul className="mt-3">
          {shown.map((entry) => (
            <Word
              key={entry.id}
              entry={entry}
              earlier={savedEarlier.has(entry.lemma)}
              opened={opened.has(entry.lemma)}
              lit={lit === entry.lemma}
              onPoint={onPoint}
              busy={save.isPending || drop.isPending}
              onSave={() =>
                entry.saved && entry.saved_word_id
                  ? drop.mutate(entry.saved_word_id)
                  : save.mutate([entry.lemma])
              }
              onGoTo={onGoTo}
            />
          ))}
        </ul>
      ) : (
        // Only reachable by asking for it — two toggles that do not overlap,
        // say C1 and unusual. It names the filter rather than the list, so
        // the reader knows it is their own question that came back empty and
        // not the passage.
        <p className="mt-6 text-center text-xs text-muted-foreground">
          No words here match that.
        </p>
      )}
    </section>
  );
}

/**
 * The distribution, the legend and the filter, as one bar.
 *
 * Each level takes the width its COUNT deserves — `flex-grow` off the
 * number, with a basis of zero so the numbers alone decide — which means
 * the bar is a picture of the passage before it is a control. A text that
 * is half B2 looks like one; a text that is nearly all C1 looks like a
 * different afternoon's work.
 *
 * A floor on the width, because a level with two words in a hundred would
 * otherwise be a sliver too narrow to read its own name, let alone press.
 * That makes the proportions approximate at the extremes and it is the
 * right trade: the bar's job is to be read, and an honest sliver nobody can
 * hit is a control that does not exist.
 *
 * A level with nothing in it is absent rather than empty. A zero-width
 * segment is a rendering artefact; a missing one is a passage with no C1
 * words in it, which is worth knowing.
 */
function LevelBar({
  levels,
  chosen,
  onFilter,
}: {
  levels: Record<CefrLevel, number>;
  chosen: CefrLevel[];
  onFilter: (next: WordFilter) => void;
}) {
  const present = CEFR_LEVELS.filter((level) => levels[level] > 0);
  if (!present.length) return null;
  return (
    <div className="mt-3 flex h-8 gap-1">
      {present.map((level) => {
        const on = chosen.includes(level);
        return (
          <button
            key={level}
            type="button"
            aria-pressed={on}
            aria-label={`${levels[level]} ${level} words`}
            onClick={() =>
              onFilter(
                toggleLevel(
                  { levels: chosen, lookedUp: false, unusual: false },
                  level,
                ),
              )
            }
            style={{ flexGrow: levels[level], flexBasis: 0 }}
            className={cn(
              "flex min-w-16 items-center justify-between rounded-md px-2.5 font-mono text-xs transition-[filter,box-shadow] duration-fast hover:brightness-125 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
              CEFR_TONE[level].chip,
              // Inset, so a pressed segment does not grow by two pixels and
              // shove its neighbours along the bar.
              on && "inset-ring-2 inset-ring-current",
            )}
          >
            <span className="font-medium">{level}</span>
            <span className="tabular-nums opacity-75">{levels[level]}</span>
          </button>
        );
      })}
    </div>
  );
}

/** One of the two filters that is not a level. Quiet by default and wearing
 *  the app's accent when it is on, which is the same "this is the thing"
 *  the accent says everywhere else. */
function Toggle({
  on,
  onClick,
  children,
}: {
  on: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn(
        "rounded-full px-2.5 py-1 text-[0.7rem] transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        on
          ? "bg-primary/20 text-primary"
          : "bg-surface-hover text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

/**
 * One word, with the sentence it was met in a press away.
 *
 * ## The example is folded, and the ROW is what unfolds it
 *
 * The sentence is the reason this beats a word list — what a learner will
 * remember is the passage, and the sentence is the handle on it — but it is
 * also two lines on every one of a hundred entries, and a hundred entries
 * four lines deep is the wall of words this panel was rebuilt to stop
 * being. Folded, the same list is a page and a half and the sentence is
 * there for the words somebody actually stops on.
 *
 * It was a small `Example ▸` button on a line of its own under each entry,
 * which is the worst of both: it cost the line the folding was meant to
 * save. Then it was a chevron beside the save button, which cost no line
 * and was still a second thing to look at on every one of a hundred rows.
 * Now there is no control at all: the row is a pointer, and pressing it
 * opens the sentence and takes the passage to the word.
 *
 * `＋` stops the press going through to the row. Saving a word and reading
 * its sentence are two different intentions and the buttons are a
 * centimetre apart; a save that also opened a paragraph would be the page
 * doing something nobody asked for every single time.
 *
 * ## Hover is unchanged, and it is the point of the whole panel
 *
 * Pointing at the row lights the word where it stands in the passage, and
 * pointing at the passage lights the row. That is the two-pane review's one
 * argument made visible, and it must not be spent on the disclosure: the
 * hover says WHERE, the press says WHAT IT MEANT THERE.
 */
function Word({
  entry,
  earlier,
  opened,
  lit,
  onPoint,
  busy,
  onSave,
  onGoTo,
}: {
  entry: VocabularyEntry;
  earlier: boolean;
  /** One of the three this reader spent a look-up on, mid-paper. */
  opened: boolean;
  lit: boolean;
  onPoint: (lemma: string | null) => void;
  busy: boolean;
  onSave: () => void;
  /** Take the passage to this word. */
  onGoTo: (lemma: string) => void;
}) {
  const [hovered, setHovered] = useState(false);
  const [open, setOpen] = useState(false);
  const sense = meanings(entry);
  const canOpen = Boolean(entry.example);
  const press = () => {
    // Both, and in this order. Hover already lights the word where it
    // stands, which is worth nothing when it stands four screens down —
    // and a list of a hundred words is mostly four screens down. A press
    // is the reader saying "that one", so the passage goes there.
    onGoTo(entry.lemma);
    if (canOpen) setOpen((was) => !was);
  };

  return (
    <li
      onMouseEnter={() => {
        setHovered(true);
        onPoint(entry.lemma);
      }}
      onMouseLeave={() => {
        setHovered(false);
        onPoint(null);
      }}
      className={cn(
        "-mx-2 rounded-lg border-b border-border/60 transition-colors duration-fast last:border-b-0",
        (hovered || lit) && "bg-surface-hover",
      )}
    >
      {/* The disclosure is a div inside the li rather than the li itself:
          `role="button"` on an <li> takes `listitem` off it, and a list of a
          hundred words that does not announce itself as a list is a
          regression a screen reader user cannot work around. */}
      <div
        role="button"
        tabIndex={0}
        aria-expanded={canOpen ? open : undefined}
        onClick={press}
        onKeyDown={(e) => {
          if (e.key !== "Enter" && e.key !== " ") return;
          e.preventDefault();
          press();
        }}
        className="flex cursor-pointer items-start gap-3 px-2 py-2.5 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
            <span className="text-sm font-semibold text-foreground">
              {entry.lemma}
            </span>
            {entry.pos && (
              <span className="text-[0.7rem] text-muted-foreground italic">
                {entry.pos}
              </span>
            )}
            <CefrTag level={entry.cefr_level} />
            {/* The two facts that are about the READER rather than about the
                word, so they are outlined rather than filled: the colour in
                this row belongs to the level, and a second filled chip would
                read as a second level. Both are named in the words the
                filter above uses, or a toggle would appear to do nothing. */}
            {opened && <Flag>looked up</Flag>}
            {earlier && <Flag>saved earlier</Flag>}
            {sense.here && <Flag>unusual sense</Flag>}
          </p>
          {/* English in the mono face the rest of the paper's own words are
              set in, Uzbek in the sans — the app's global rule, and here it
              also does the work of telling two one-line definitions apart at
              a glance without a label in front of either. */}
          <p className="mt-0.5 font-mono text-xs text-foreground/80">
            {sense.en}
          </p>
          <p className="text-xs text-muted-foreground">{sense.uz}</p>
          {/* The passage's own sense, under the one worth carrying away,
              and only where the two are different — see `meaning.ts`. The
              label is a word rather than an icon because it is doing the
              whole job: without it these are two definitions with nothing
              to say which is which. */}
          {sense.here && (
            <p className="mt-1 border-l-2 border-border pl-2">
              <span className="font-mono text-xs text-foreground/80">
                <span className="text-muted-foreground">Here: </span>
                {sense.here.en}
              </span>
              <span className="block text-xs text-muted-foreground">
                {sense.here.uz}
              </span>
            </p>
          )}
          {/* Said once, quietly, never as a badge — see `LookupPopover`'s
              own copy of this line. Saving a second sense of a lemma
              already on the list is ordinary; this is information, not a
              warning. */}
          {!entry.saved && entry.other_sense_saved && (
            <p className="mt-1 text-[0.68rem] text-muted-foreground/70 italic">
              You&apos;ve saved another meaning of this word.
            </p>
          )}
        </div>

        {/* One control in this column, centred against the entry it
            belongs to. There was a chevron under it saying the row opens —
            and it was a second thing to look at on every one of a hundred
            rows, for a disclosure the row itself already invites by being
            a pointer. What the column is FOR is the button. */}
        <button
          type="button"
          disabled={busy}
          // See the component comment: the row opens the sentence and
          // takes the passage to the word, and a save that also did that
          // would be the page acting twice on one press.
          onClick={(e) => {
            e.stopPropagation();
            onSave();
          }}
          title={
            entry.saved ? "Take it off your list" : "Add to your vocabulary"
          }
          aria-label={
            entry.saved ? `Remove ${entry.lemma}` : `Save ${entry.lemma}`
          }
          className={cn(
            "group flex size-8 shrink-0 items-center justify-center self-center rounded-lg border transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50",
            entry.saved
              ? "border-correct/40 bg-correct/10 text-correct hover:border-destructive/40 hover:bg-destructive/10 hover:text-destructive"
              : "border-border bg-surface-hover text-foreground hover:border-primary/50 hover:bg-primary/15 hover:text-primary",
          )}
        >
          {entry.saved ? (
            <>
              {/* The tick until the pointer is on it, then what pressing
                  would do — or `Saved` is a button that removes, which
                  nobody presses twice on purpose. */}
              <Check className="size-3.5 group-hover:hidden" aria-hidden />
              <X className="hidden size-3.5 group-hover:block" aria-hidden />
            </>
          ) : (
            <Plus className="size-3.5" aria-hidden />
          )}
        </button>
      </div>

      {/* Under the whole entry rather than inside the text column, with the
          rule the app uses everywhere for "these are somebody else's
          words". It is the passage's own sentence, cut from the text rather
          than written by a model — see `seed/read_vocabulary.py`. */}
      {open && entry.example && (
        <p className="mx-2 mb-2.5 border-l-2 border-border pl-2 text-xs leading-relaxed text-muted-foreground italic">
          {entry.example}
        </p>
      )}
    </li>
  );
}

/** A fact about this reader's history with the word, not about the word. */
function Flag({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded border border-border px-1 text-[0.65rem] text-muted-foreground">
      {children}
    </span>
  );
}
