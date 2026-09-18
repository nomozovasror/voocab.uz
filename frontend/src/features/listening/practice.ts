import { AudioLines, Layers } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  QUESTION_TYPE_BLURB,
  QUESTION_TYPE_ICON,
  QUESTION_TYPE_LABEL,
} from "@/features/listening/parts";
import type {
  CatalogueAuthor,
  DifficultyBand,
  ListeningStats,
  MistakeKind,
  PartAccuracy,
  PracticeFacet,
  PracticeMaterial,
  QuestionGroupType,
} from "@/features/listening/types";

/**
 * What a catalogue row says about itself, and what the filters above it mean.
 *
 * All of it derived, none of it stored: the server sends which parts a
 * material holds and which kinds of question are in them, and everything a
 * learner reads on the row — "Part 2", "Full test", "2 question types" — is
 * worked out from those two lists here, in one place, so the row and the chip
 * that filters it can't come to disagree about what a material is.
 */

// --- Difficulty --------------------------------------------------------------

/** Title case, like every other label in the interface. */
export const DIFFICULTY_LABEL: Record<DifficultyBand, string> = {
  new: "New",
  easy: "Easy",
  medium: "Medium",
  hard: "Hard",
};

/**
 * The same four, at the width of the shortest of them.
 *
 * The chip is the right-hand column of every row, and a column whose width
 * changes per row is a ragged edge down the page — "Medium" is half as wide
 * again as "New", which was enough to make the list look unaligned even
 * though every chip was placed identically.
 *
 * Trimming the label is what fixes it at the source, rather than padding the
 * chip out to the widest word and printing three of the four with air around
 * them. "Med" is the only one that loses anything, and it loses it beside
 * "Easy" and "Hard", which is all the context it needs. The full word is
 * still what the filter menu offers and what the tooltip spells out.
 */
export const DIFFICULTY_SHORT: Record<DifficultyBand, string> = {
  new: "New",
  easy: "Easy",
  medium: "Med",
  hard: "Hard",
};

/** The chip, per band.
 *
 * `New` is deliberately the quietest of the four rather than a fifth colour:
 * it is the absence of a measurement, not a level of difficulty, and painting
 * it as loudly as `Hard` would make "nobody has done this yet" look like a
 * warning. */
export const DIFFICULTY_CLASS: Record<DifficultyBand, string> = {
  new: "border-border-subtle text-muted-foreground",
  easy: "border-correct/40 bg-correct/10 text-correct",
  // Neutral, not amber. Amber here is within a shade of the accent, and the
  // accent means "this is the action" — a chip on every second row wearing it
  // would spend the page's one loud colour on the least interesting fact it
  // has. Green and red carry the two ends; the middle is the absence of both.
  medium: "border-border-subtle bg-surface-hover text-foreground",
  hard: "border-incorrect/40 bg-incorrect/10 text-incorrect",
};

/** The bands in the order they are offered — the scale, then the absence of
 *  one. `New` is last because it is not a level of difficulty. */
export const DIFFICULTY_ORDER: DifficultyBand[] = [
  "easy",
  "medium",
  "hard",
  "new",
];

/** What a difficulty chip means, spelled out — the band alone is a claim with
 *  no working shown, and the number behind it is the working. */
export function difficultyTitle(m: PracticeMaterial): string {
  const { band, correct_pct, answered } = m.difficulty;
  if (band === "new" || correct_pct === null) {
    return answered === 0
      ? "Nobody has answered this yet"
      : `Only ${answered} answers so far — not enough to rate it`;
  }
  return `${correct_pct}% of answers to this material are correct (${answered} answers)`;
}

// --- What a material is ------------------------------------------------------

/** Four parts is a whole paper; anything less is an excerpt from one. */
export const FULL_TEST_PARTS = 4;

export interface TaskDescription {
  Icon: LucideIcon;
  label: string;
}

/**
 * The one thing the meta line says about the questions inside.
 *
 * A single type names itself and wears its own icon — the same icon the
 * editor uses, imported from the same table, because an author who built a
 * map-labelling task and a learner looking for one should be looking at the
 * same mark.
 *
 * Beyond that a name would be a lie by omission: a part holding form
 * completion *and* multiple choice is not a form-completion material, and
 * labelling it after whichever came first is how a catalogue teaches people
 * to distrust it. So several types in one part count themselves, and several
 * parts stop describing the questions at all — a whole paper is not "notes
 * completion", it is a whole paper.
 */
export function describeTask(m: PracticeMaterial): TaskDescription | null {
  if (m.part_count > 1) {
    return {
      Icon: AudioLines,
      label:
        m.part_count >= FULL_TEST_PARTS
          ? "Full test"
          : `${m.part_count} parts`,
    };
  }
  if (m.question_types.length === 1) {
    const type = m.question_types[0];
    return { Icon: QUESTION_TYPE_ICON[type], label: QUESTION_TYPE_LABEL[type] };
  }
  if (m.question_types.length > 1) {
    return { Icon: Layers, label: `${m.question_types.length} question types` };
  }
  return null;
}

/** "Part 2", or nothing where there is more than one to name. */
export function partLabel(m: PracticeMaterial): string | null {
  if (m.part_count !== 1) return null;
  const [n] = m.part_numbers;
  return n ? `Part ${n}` : null;
}

// --- Filters -----------------------------------------------------------------

/**
 * What the chip row selects: everything, one part, or a whole paper.
 *
 * One selection rather than a set, because these are three answers to the
 * same question ("which of them do I want to see"). "Done" is the other
 * question and toggles independently — it is about the learner, not about the
 * material.
 */
export type Scope = "all" | "full" | 1 | 2 | 3 | 4;

/** Every answer to the scope question, in the order the menu offers them.
 *
 *  One menu rather than six chips. Six was already the widest thing in the
 *  filter row, and the row has since gained the control that switches between
 *  materials and courses — which is a question ABOUT the whole page and has
 *  to come first. Something had to fold up, and this is the one that folds
 *  without loss: exactly one of these is ever true, so a menu says what a row
 *  of chips said, at a sixth of the width. */
export const SCOPE_OPTIONS: Scope[] = ["all", 1, 2, 3, 4, "full"];

export function scopeLabel(scope: Scope): string {
  if (scope === "all") return "All parts";
  if (scope === "full") return "Full test";
  return `Part ${scope}`;
}

/**
 * Everything the controls above the list can say, in one value.
 *
 * `bands` and `types` are arrays and an EMPTY one means "all of them", not
 * "none of them" — the difference matters, because the alternative is
 * seeding state with every option pre-selected and then having to keep that
 * seed in step with whatever the catalogue happens to contain today.
 */
export interface PracticeFilterState {
  scope: Scope;
  /**
   * Whether materials the reader has already sat are in the list.
   *
   * Off by default, which is the one filter here that starts doing something.
   * The list answers "what shall I practise next", and a paper somebody has
   * already sat is the least likely answer on the page — leaving them in
   * meant a learner scrolled past their own history to find anything new,
   * and the more they practised the worse the page got at its job.
   *
   * They are never gone, only put away: the chip brings them straight back,
   * and the line above the list says how many are being held. A filter that
   * hides things silently is a filter that makes the catalogue look broken.
   */
  showDone: boolean;
  query: string;
  /** Any of these bands. Difficulty is a scale, so "Easy or Medium" is a real
   *  request, which is why this is a set of toggles and the scope above is
   *  not. */
  bands: DifficultyBand[];
  /** Any of these types. A material holding several matches on any one of
   *  them: somebody looking for map labelling wants the full test that has
   *  some in it too. */
  types: QuestionGroupType[];
}

/**
 * Which of the two lists the page is showing.
 *
 * Not a filter, and it is worth being clear about the difference: a filter
 * narrows a list, and this changes which list there is. It lives beside the
 * filters because that is where somebody looks for it, but nothing else in
 * `PracticeFilterState` applies to courses — a course has no part number and
 * no difficulty band — so switching to them puts most of the row away rather
 * than leaving controls that would do nothing.
 *
 * The search field is the exception, and the one thing that makes the switch
 * feel like one page rather than two: the same field searches whichever list
 * is showing.
 */
export const LIST_MODES = ["materials", "courses", "drills"] as const;

export type ListMode = (typeof LIST_MODES)[number];

/**
 * What each tab is called.
 *
 * A table rather than the literal rendered with CSS `capitalize`, which is
 * what the switch used to do. That trick holds exactly as long as every mode
 * is one lowercase word that title-cases correctly, and it is an undocumented
 * rule nobody would know they had broken. The names are in the interface's
 * one place for names, like every other label here.
 */
export const LIST_MODE_LABEL: Record<ListMode, string> = {
  materials: "Materials",
  courses: "Courses",
  // Named after what the tab SHOWS, which is the eleven kinds of question.
  // "Drills" was tried and is the jargon of the thing rather than its name —
  // a word a learner has to be taught before the tab means anything, where
  // "question type" is what their teacher and their book already call it.
  // The internal value stays `drills`, because that is what the tab lists
  // and what the routes under it are.
  drills: "Question types",
};

/**
 * What one card on the Question types tab covers.
 *
 * Usually one kind of question, and then the card is that kind. The exception
 * is labelling: map and diagram labelling are the same task on two kinds of
 * picture — the same sheet of A-I letters, the same eight options, the same
 * thing to do — and the library holds twenty-three maps and TWO diagrams. Two
 * cards there would be one nobody clicks beside one that answers the same
 * question, and a learner who wants to practise labelling wants both.
 *
 * Flow-chart completion is deliberately NOT in it, though the seed pipeline
 * groups it with them for its own reasons. Every map and diagram group in the
 * library carries a picture and its letters; not one flow chart does — it is a
 * template with gaps, which is a different thing to sit.
 *
 * A family is a set of types because that is what the server filters by: the
 * list endpoint takes `type` repeated, so a card is just the types it names.
 */
export interface TaskFamily {
  /** What the tab's state and the filter chip carry. Equal to the single
   *  type's name where there is one, so nothing had to be migrated. */
  key: string;
  types: QuestionGroupType[];
  label: string;
  blurb: string;
}

/** The one family that is more than its type. */
const LABELLING: TaskFamily = {
  key: "labelling",
  types: ["map_labelling", "diagram_labelling"],
  label: "Map & diagram labelling",
  blurb: "Places or parts named on a picture",
};

/**
 * Which part of the paper a drill came from.
 *
 * The catalogue's scope question asked of a group instead of a material, and
 * it is a real one here in a way it is not elsewhere: every map in the
 * library is Part 2, every form completion Part 1, and choosing Part 2 leaves
 * the eight kinds that actually appear in it. A learner working on their
 * weakest part wants the tasks that live there.
 *
 * Matched on the server against the number the part STARTS at, never against
 * its index — see `_in_part`. Every seeded material is one part stored at
 * index 0, so an index match would find nothing at all.
 */
export type DrillPart = "all" | 1 | 2 | 3 | 4;

export const DRILL_PART_ORDER: DrillPart[] = [1, 2, 3, 4];

export function drillPartLabel(part: DrillPart): string {
  return part === "all" ? "Any part" : `Part ${part}`;
}

/**
 * The one filter a course has.
 *
 * It is the ordering read as a question rather than as an order: the list
 * already leads with what is half-finished, and this is for the reader who
 * wants only that part of it. Everything else the catalogue filters by — the
 * part, the task, the difficulty band — belongs to a paper, not to a route
 * through several of them.
 *
 * It exists because of what switching lists used to do: the filter row simply
 * emptied, which read as the controls having broken rather than as their
 * having become irrelevant. A row that changes what it offers is answering
 * the new question; a row that goes blank is refusing to.
 */
export type CourseStatus = "all" | "in_progress" | "not_started" | "finished";

export const COURSE_STATUS_ORDER: CourseStatus[] = [
  "all",
  "in_progress",
  "not_started",
  "finished",
];

export const COURSE_STATUS_LABEL: Record<CourseStatus, string> = {
  all: "All courses",
  in_progress: "In progress",
  not_started: "Not started",
  finished: "Finished",
};

/**
 * Which part of the paper a course drills.
 *
 * The catalogue's own scope question, asked of a route through several papers
 * instead of one: does this course have Part 3 in it. `full` sits in the same
 * menu rather than beside it because it is the same kind of answer — a
 * mock-test set and a Part 3 drill are two things somebody might be after,
 * and two menus would be asking twice.
 *
 * A whole paper answers to `full` AND to each of its parts. That is not an
 * inconsistency: it IS four parts, and somebody looking for Part 3 practice
 * is not wrong to be shown a paper containing one.
 */
export type CourseCovers = "all" | "1" | "2" | "3" | "4" | "full";

/** The narrowing answers only. `all` is the absence of one, so it is not in
 *  the list the menu is built from — it is the line above it. */
export const COURSE_COVERS_ORDER = ["1", "2", "3", "4", "full"] as const;

export const COURSE_COVERS_LABEL: Record<CourseCovers, string> = {
  all: "Any part",
  "1": "Part 1",
  "2": "Part 2",
  "3": "Part 3",
  "4": "Part 4",
  full: "Full tests",
};

/**
 * How much of somebody's life a course wants.
 *
 * The first question anybody has about a course, and "eleven materials" only
 * answers it once you have seen a few. Three bands answer it at a glance: an
 * evening, a fortnight, a syllabus. The ranges are in the labels because a
 * band name without its range is a word somebody has to learn.
 */
export type CourseLength = "all" | "short" | "medium" | "long";

export const COURSE_LENGTH_ORDER = ["short", "medium", "long"] as const;

export const COURSE_LENGTH_LABEL: Record<CourseLength, string> = {
  all: "Any length",
  short: "Short (1–5)",
  medium: "Medium (6–15)",
  long: "Long (16+)",
};

export const EMPTY_FILTERS: PracticeFilterState = {
  scope: "all",
  showDone: false,
  query: "",
  bands: [],
  types: [],
};

/** Whether the list is showing less than everything — what puts "Clear
 *  filters" on screen. One definition, so the button can't appear over an
 *  unfiltered list or hide over a filtered one. */
export function isNarrowed(f: PracticeFilterState): boolean {
  return (
    f.scope !== "all" ||
    // Widening rather than narrowing, and still here: "Clear filters" means
    // "put the list back the way it was", and leaving this one set would make
    // the button a liar about the one filter that is on by default.
    f.showDone ||
    f.query.trim() !== "" ||
    f.bands.length > 0 ||
    f.types.length > 0
  );
}

/**
 * The filter state as query parameters.
 *
 * This function IS the move that made the page survive a big library. The
 * filtering used to happen here, in the browser, over a catalogue the server
 * had sent in full — which works precisely as long as sending it in full is
 * reasonable. Now the same state is handed to the server and the browser
 * receives a page.
 *
 * An empty array means "all of them" and is left out entirely rather than
 * sent as an empty parameter, so the URL says what was asked for and nothing
 * else. `done` is only ever sent true: false is the default at both ends.
 */
export function catalogueParams(
  f: PracticeFilterState,
  sort: SortKey,
): Record<string, string | string[]> {
  const params: Record<string, string | string[]> = {};
  const query = f.query.trim();
  if (query) params.q = query;
  if (f.scope !== "all") params.scope = String(f.scope);
  if (f.types.length) params.types = f.types;
  if (f.bands.length) params.bands = f.bands;
  if (f.showDone) params.done = "true";
  if (sort !== "newest") params.sort = sort;
  return params;
}

/** Toggle one value of a multi-select filter. */
export function toggle<T>(values: T[], value: T): T[] {
  return values.includes(value)
    ? values.filter((v) => v !== value)
    : [...values, value];
}

// --- What there is to filter BY ---------------------------------------------

/** One line of a filter menu: what it selects, what it is called, and how
 *  many materials it would leave standing. */
export interface FilterOption<T> {
  value: T;
  label: string;
  count: number;
}

/**
 * The server's facet counts, turned into menu lines.
 *
 * The counts come from the server because only it can count the library; the
 * NAMES come from here, because what we call a question type is not the
 * server's business. Anything it sends that we have no name for is dropped
 * rather than printed raw — a menu line reading "flow_chart_completion" is
 * worse than one line fewer.
 *
 * Ordered by the canonical table rather than by count, so an option keeps its
 * position in the menu from one visit to the next. A list that reorders
 * itself as the library grows is a list nobody learns.
 */
export function filterOptions<T extends string>(
  facets: PracticeFacet[],
  order: readonly T[],
  labels: Record<T, string>,
): FilterOption<T>[] {
  const counts = new Map(facets.map((f) => [f.value, f.count]));
  return order
    .filter((value) => (counts.get(value) ?? 0) > 0)
    .map((value) => ({
      value,
      label: labels[value],
      count: counts.get(value)!,
    }));
}

/** The question types in the order the menu offers them — the canonical
 *  table's own order. */
export const QUESTION_TYPE_ORDER = Object.keys(
  QUESTION_TYPE_LABEL,
) as QuestionGroupType[];

/**
 * The cards, in the order the tab draws them.
 *
 * Built from the canonical order rather than written out again, so a question
 * type added to `QUESTION_TYPE_LABEL` gets a card without anybody remembering
 * this list — and the labelling pair collapses into one card at the position
 * of whichever of them comes first.
 */
export const TASK_FAMILIES: TaskFamily[] = (() => {
  const families: TaskFamily[] = [];
  for (const type of QUESTION_TYPE_ORDER) {
    if (LABELLING.types.includes(type)) {
      if (!families.includes(LABELLING)) families.push(LABELLING);
      continue;
    }
    families.push({
      key: type,
      types: [type],
      label: QUESTION_TYPE_LABEL[type],
      blurb: QUESTION_TYPE_BLURB[type],
    });
  }
  return families;
})();

export function familyByKey(key: string | null): TaskFamily | null {
  if (!key) return null;
  return TASK_FAMILIES.find((family) => family.key === key) ?? null;
}

/** The card a question TYPE belongs to.
 *
 *  A different lookup from `familyByKey`, and both are needed: the tab's own
 *  state carries a key, while anything the server says carries a type —
 *  a group has a type, not a card. Looking a type up by key silently finds
 *  nothing for exactly the pair this table exists for, since the labelling
 *  card's key is neither of its types. */
export function familyOfType(type: string | null): TaskFamily | null {
  if (!type) return null;
  return (
    TASK_FAMILIES.find((family) =>
      family.types.includes(type as QuestionGroupType),
    ) ?? null
  );
}

/** The mark a family wears: its own type's icon, and for the labelling pair
 *  the map's — a map is what all but two of them are. */
export function familyIcon(family: TaskFamily): LucideIcon {
  return QUESTION_TYPE_ICON[family.types[0]];
}

// --- Accuracy ----------------------------------------------------------------

/**
 * Whether a percentage is low enough to be worth colouring.
 *
 * Two states, not three, and the threshold is deliberately low. The panel used
 * to paint anything under 70 red and anything over 80 green, which meant most
 * of a candidate's figures arrived pre-judged — 66% in red is a verdict nobody
 * asked for on a number that is ordinary. Red now means what red should mean:
 * this one is genuinely poor. Everything else is left alone to be read.
 */
export type AccuracyTone = "weak" | "neutral";

export const WEAK_UNDER = 60;

export function accuracyTone(pct: number): AccuracyTone {
  return pct < WEAK_UNDER ? "weak" : "neutral";
}

export const ACCURACY_TEXT: Record<AccuracyTone, string> = {
  weak: "text-incorrect",
  neutral: "text-foreground",
};

/** "2.4h", "35m" — how long has been spent, at the resolution a person
 *  thinks in. Minutes below the hour mark, because "0.6h" is a number nobody
 *  reads as thirty-six minutes. */
export function formatSpent(ms: number): string {
  const minutes = Math.round(ms / 60_000);
  if (minutes < 60) return `${minutes}m`;
  return `${(ms / 3_600_000).toFixed(1)}h`;
}


// --- Order ------------------------------------------------------------------

/**
 * How the list is ordered.
 *
 * Four, and every one of them is answerable from what a row already shows —
 * which is the test a sort has to pass. "Most popular" and "Suits you" are
 * the obvious next two and neither is here yet, because the first needs an
 * attempt count this endpoint doesn't send and the second needs the learner's
 * weakest area crossed with each material's parts. Adding them is adding a
 * line to this table and a case below; nothing else moves.
 */
export type SortKey = "newest" | "easiest" | "hardest" | "shortest";

export const SORT_ORDER: SortKey[] = ["newest", "easiest", "hardest", "shortest"];

export const SORT_LABEL: Record<SortKey, string> = {
  newest: "Newest first",
  easiest: "Easiest first",
  hardest: "Hardest first",
  shortest: "Shortest first",
};

// The four orders are named here and applied by the server (see
// backend/app/services/listening.py `_catalogue_order`). Where a band sits on
// the scale — and that `new` is last in BOTH directions, because a material
// nobody has answered enough of belongs at neither end — lives there now,
// with the query that uses it.

// --- What a row means to this reader ----------------------------------------

/**
 * Where a material sits against the reader's own record.
 *
 * This is the one thing the catalogue can say that neither the row nor the
 * statistics panel can say alone: the row knows what the material is, the
 * panel knows how the reader does, and the useful sentence is the two crossed.
 *
 * It reports the number and stops there. It used to add "your weakest area",
 * and that claim did not survive being looked at: 62% against 66% over a few
 * dozen answers is noise, and ranking one above the other told a candidate to
 * spend their evening on a difference that isn't there.
 *
 * Where a material spans several parts, the WORST of them is the one reported.
 * A whole paper is worth sitting for the part you are weakest at, and averaging
 * four parts into one number would hide exactly the fact that makes it worth
 * sitting.
 */
export interface Standing {
  part: number;
  /** `null` where the reader has not answered enough of that part to score
   *  it — a state the card says out loud rather than papering over. */
  accuracy_pct: number | null;
  answered: number;
}

export function standingFor(
  m: PracticeMaterial,
  stats: ListeningStats | undefined,
): Standing | null {
  if (!stats || m.part_numbers.length === 0) return null;
  const rows = m.part_numbers
    .map((part) => stats.by_part.find((row) => row.part === part))
    .filter((row): row is PartAccuracy => row !== undefined);
  if (rows.length === 0) return null;

  const scored = rows.filter((row) => row.accuracy_pct !== null);
  // The worst scored part if any of them is scored; otherwise the first, so
  // the card can still say which part it is and that there is no reading yet.
  const row = scored.length
    ? scored.reduce((worst, next) =>
        next.accuracy_pct! < worst.accuracy_pct! ? next : worst,
      )
    : rows[0];

  return {
    part: row.part,
    accuracy_pct: row.accuracy_pct,
    answered: row.answered,
  };
}

// --- What one author has written --------------------------------------------

/**
 * An author, summarised.
 *
 * Both numbers arrive on the row (`material.author`) rather than being
 * counted here, and that changed with pagination: counting them in the
 * browser meant counting over whatever the browser happened to have, which
 * was the whole catalogue and is now thirty rows of it. "4 materials here"
 * under a name has to mean four.
 *
 * Two numbers and no more. It used to report which parts they write, the
 * difficulty they tend to land on and how many questions they have written
 * in total; all of it was true, none of it helped anybody decide whether to
 * sit the material in front of them.
 */
export interface AuthorSummary {
  materials: number;
  /** How many of them the reader has sat. */
  done: number;
}

export function authorSummary(author: CatalogueAuthor): AuthorSummary {
  return { materials: author.materials, done: author.done };
}

// --- Mistakes ---------------------------------------------------------------

/**
 * What each kind of mistake is called, and what it says about the reader.
 *
 * The rules that produce these live on the server
 * (`backend/app/services/mistakes.py`); the words live here, with every other
 * label in the interface. The meanings are the working: "Spelling" on its own
 * is a category, and "you heard the answer correctly but wrote it wrong" is
 * the thing a candidate can do something about on Thursday evening.
 */
export const MISTAKE_LABEL: Record<MistakeKind, string> = {
  spelling: "Spelling",
  missed: "Missed entirely",
  wrong: "Wrong answer",
  plural: "Singular / plural",
  word_limit: "Over word limit",
  format: "Number / date format",
};

export const MISTAKE_MEANING: Record<MistakeKind, string> = {
  spelling: "You heard the answer correctly but wrote it wrong.",
  missed: "You left these blank — the answer went past you.",
  plural: "The word was right; the singular or plural wasn't.",
  word_limit: "The answer was there, but longer than the rubric allows.",
  format: "The right value, written a way the marker doesn't accept.",
  wrong: "A different answer entirely — the ones to listen for again.",
};

/**
 * The same six kinds as a NOUN PHRASE, and what to do about each.
 *
 * For the sentence a review writes when every mark it lost went the same way:
 * "All three marks went to *answers you heard but got wrong* — worth
 * listening again to where the answer is given." A breakdown of one category
 * is a chart with one bar in it, which says nothing a sentence doesn't say
 * better — and the sentence can say what to do about it, which the bar
 * cannot.
 *
 * Only the TAIL is written down, because the same sentence has to come out in
 * both numbers ("an answer you heard but got wrong" for a paper with one
 * mistake on it) and two lists of six would drift the first time one of them
 * was reworded.
 */
const MISTAKE_TAIL: Record<MistakeKind, string> = {
  spelling: "you heard but spelled wrong",
  missed: "that went past you entirely",
  plural: "where only the singular or plural was wrong",
  word_limit: "longer than the rubric allows",
  format: "written a way the marker doesn't accept",
  wrong: "you heard but got wrong",
};

export function mistakePhrase(kind: MistakeKind, many: boolean): string {
  return `${many ? "answers" : "an answer"} ${MISTAKE_TAIL[kind]}`;
}

/**
 * What to do about each kind — and it is per kind for a reason.
 *
 * "Listen to those moments again" is right for an answer that went past
 * somebody and exactly wrong for one they heard and misspelled, who needs to
 * read their sheet back rather than play the recording a fourth time. Every
 * line is written to work for one mistake or twelve, so the sentence around
 * it only has to choose a number in one place.
 */
export const MISTAKE_ADVICE: Record<MistakeKind, string> = {
  spelling:
    "worth reading your sheet back before you submit, rather than listening again",
  missed: "worth going back to where the answer was said and listening for it",
  plural: "worth listening for the article and the verb around the word",
  word_limit: "worth re-reading the rubric before you write",
  format: "worth writing numbers and dates the way the question does",
  wrong: "worth listening again to where the answer is given",
};

/** "1st", "2nd", "3rd", "4th" — for "83% on your 2nd try", where the ordinal
 *  is doing as much work as the percentage. */
export function ordinal(n: number): string {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  switch (n % 10) {
    case 1:
      return `${n}st`;
    case 2:
      return `${n}nd`;
    case 3:
      return `${n}rd`;
    default:
      return `${n}th`;
  }
}
