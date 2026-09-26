import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Check, EllipsisVertical } from "lucide-react";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { toast } from "@/lib/toast";
import { getErrorMessage } from "@/lib/api";
import { daysUntil, timeUntil } from "@/lib/time";
import { cn } from "@/lib/utils";
import { CefrTag } from "@/features/vocabulary/components/CefrTag";
import { CEFR_LEVELS, asLevel, type CefrLevel } from "@/features/vocabulary/cefr";
import { DeleteWordsDialog } from "@/features/vocabulary/components/DeleteWordsDialog";
import { StatusChip } from "@/features/vocabulary/components/StatusChip";
import {
  ACTION_LABEL,
  STATUS_CHIP_LABEL,
  type StatusChip as StatusChipValue,
  statusChip,
} from "@/features/vocabulary/status";
import {
  scheduleDelete,
  undoDelete,
  useFlushPendingDeletesOnLeave,
  usePendingDeletes,
} from "@/features/vocabulary/pendingDelete";
import { vocabularyApi, vocabularyWordsKey } from "@/features/vocabulary/api";
import type { BulkAction, SavedWord } from "@/features/vocabulary/types";

/**
 * The words this learner has kept — stage 2's rebuild of the stage 1 saved
 * list, now with what the practice module has done to each one: its
 * status, both directions' levels, and when it is next due.
 *
 * ## Still not the practice module
 *
 * This is a list, not a queue — pressing a row does not start a session,
 * and there is no "practise these now" here. That is `/vocabulary` and
 * `/vocabulary/practice`; this is where a learner comes to ASK about a
 * word rather than be asked one, which is also why bulk actions (mark
 * known, set aside, restore, delete) live here and nowhere in the session.
 *
 * ## Filters are client-side, on purpose
 *
 * The whole list is one call (`GET /vocabulary/words`, the spec's API
 * summary) and a few hundred rows is nothing to filter in the browser — a
 * server round trip per filter tap would be the SLOWER page. Only `status`
 * lives in the URL, because it is the one filter another screen needs to
 * link to: the home screen's "N words set aside" line points here with
 * `?status=suspended` rather than describing the filter in words and
 * hoping the learner presses the right pill.
 */

/** The four chips a learner sees (F7's §7 table), not the five wire
 *  statuses — `learning`/`review` filter as one "In rotation" pill, same as
 *  they print as one chip on the row. */
type StatusFilter = "all" | StatusChipValue;
type DirectionFilter = "all" | "passiveOnly" | "active";

const STATUS_FILTERS: StatusFilter[] = [
  "all",
  "in_rotation",
  "known",
  "suspended",
  "leech",
];

export default function VocabularyPage() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const status = (params.get("status") as StatusFilter | null) ?? "all";
  const [cefr, setCefr] = useState<"all" | CefrLevel>("all");
  const [material, setMaterial] = useState<"all" | string>("all");
  const [direction, setDirection] = useState<DirectionFilter>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  // Bulk delete's own count, held apart from `selected.size` so the dialog's
  // "Delete 12 words?" doesn't relabel itself if the selection changes while
  // it's open. Null closes it.
  const [deleteDialogCount, setDeleteDialogCount] = useState<number | null>(null);
  const pendingDeletes = usePendingDeletes();
  // Keeps this page registered as a place "Removed · Undo" can be shown for
  // as long as it's mounted — see `pendingDelete.ts` for why the word page
  // shares this registration rather than each page owning its own timer.
  useFlushPendingDeletesOnLeave();

  const { data, isPending, isError } = useQuery({
    queryKey: vocabularyWordsKey,
    queryFn: () => vocabularyApi.words(),
  });

  function setStatus(next: StatusFilter) {
    setParams(
      (prev) => {
        const copy = new URLSearchParams(prev);
        if (next === "all") copy.delete("status");
        else copy.set("status", next);
        return copy;
      },
      { replace: true },
    );
  }

  const materials = useMemo(() => {
    const seen = new Map<string, string>();
    for (const word of data?.words ?? []) {
      for (const ctx of word.contexts) {
        if (!seen.has(ctx.material_id)) seen.set(ctx.material_id, ctx.material_title);
      }
    }
    return [...seen.entries()];
  }, [data]);

  const filtered = useMemo(() => {
    if (!data) return [];
    return data.words.filter((word) => {
      if (status !== "all" && statusChip(word.status) !== status) return false;
      if (cefr !== "all" && asLevel(word.cefr_level) !== cefr) return false;
      if (material !== "all" && !word.contexts.some((c) => c.material_id === material))
        return false;
      if (direction === "passiveOnly" && word.active_level !== null) return false;
      if (direction === "active" && word.active_level === null) return false;
      return true;
    });
  }, [data, status, cefr, material, direction]);

  function toggleSelected(lemma: string) {
    setSelected((was) => {
      const next = new Set(was);
      if (next.has(lemma)) next.delete(lemma);
      else next.add(lemma);
      return next;
    });
  }

  const allVisibleSelected =
    filtered.length > 0 && filtered.every((w) => selected.has(w.lemma));

  function toggleSelectAll() {
    setSelected((was) => {
      if (allVisibleSelected) {
        const next = new Set(was);
        for (const w of filtered) next.delete(w.lemma);
        return next;
      }
      return new Set([...was, ...filtered.map((w) => w.lemma)]);
    });
  }

  const bulk = useMutation({
    mutationFn: (action: BulkAction) =>
      vocabularyApi.bulkWords({ lemmas: [...selected], action }),
    onSuccess: (result, action) => {
      setSelected(new Set());
      setDeleteDialogCount(null);
      void qc.invalidateQueries({ queryKey: vocabularyWordsKey });
      // Every count the practice home screen shows (due, set-aside,
      // totals) can move on any of these four verbs, not just `known` and
      // `suspend` — a restored word re-enters `due_now` the moment its
      // schedule is recomputed.
      void qc.invalidateQueries({ queryKey: ["vocabulary", "practice", "summary"] });
      toast({
        message: `${result.changed} ${result.changed === 1 ? "word" : "words"} ${
          action === "forget" ? "deleted" : "updated"
        }`,
        kind: "success",
      });
    },
    onError: (e) => toast(getErrorMessage(e)),
  });

  // The Delete button's own branch, not the bulk endpoint's: exactly one
  // selected word gets the cheap answer (the row becomes "Removed · Undo",
  // no request yet — `pendingDelete.ts`); more than one opens
  // `DeleteWordsDialog`, which is what actually calls `bulk.mutate("forget")`
  // once it's confirmed.
  function handleDeleteClick() {
    if (selected.size === 1) {
      const [lemma] = selected;
      scheduleDelete(lemma);
      setSelected(new Set());
    } else if (selected.size > 1) {
      setDeleteDialogCount(selected.size);
    }
  }

  // The per-row menu's own mutation, apart from `bulk` above even though it
  // calls the same endpoint — `bulk` is scoped to `selected` and clears it
  // on success, which a single row's own menu has no business touching.
  const rowAction = useMutation({
    mutationFn: ({ lemma, action }: { lemma: string; action: BulkAction }) =>
      vocabularyApi.bulkWords({ lemmas: [lemma], action }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: vocabularyWordsKey });
      void qc.invalidateQueries({ queryKey: ["vocabulary", "practice", "summary"] });
    },
    onError: (e) => toast(getErrorMessage(e)),
  });

  if (isPending) return <ListSkeleton />;

  if (isError || !data) {
    return (
      <div className="mx-auto w-full max-w-2xl py-16">
        <h1 className="text-2xl font-semibold text-foreground">Vocabulary</h1>
        <p className="mt-2 text-sm text-destructive">
          Your words couldn&apos;t be loaded.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-2xl pb-24">
      <header className="pt-2 pb-4">
        <h1 className="text-2xl font-semibold text-foreground">Vocabulary</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {data.total > 0
            ? `${data.total} ${data.total === 1 ? "word" : "words"} you kept.`
            : "Words you keep from a passage collect here."}
        </p>
      </header>

      {data.total > 0 && (
        <div className="flex flex-col gap-2.5">
          <PillRow
            label="Status"
            value={status}
            options={STATUS_FILTERS.map(
              (s) => [s, s === "all" ? "All" : STATUS_CHIP_LABEL[s]] as const,
            )}
            onChange={setStatus}
          />
          <div className="flex flex-wrap items-center gap-2.5">
            <PillRow
              label="Level"
              value={cefr}
              options={[["all", "All"] as const, ...CEFR_LEVELS.map((l) => [l, l] as const)]}
              onChange={setCefr}
            />
            <PillRow
              label="Direction"
              value={direction}
              options={[
                ["all", "All"] as const,
                ["passiveOnly", "Passive only"] as const,
                ["active", "Also active"] as const,
              ]}
              onChange={setDirection}
            />
          </div>
          {materials.length > 1 && (
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              Source
              <select
                value={material}
                onChange={(e) => setMaterial(e.target.value)}
                className="rounded-md border border-border bg-surface-sunken px-2 py-1 text-xs text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                <option value="all">All materials</option>
                {materials.map(([id, title]) => (
                  <option key={id} value={id}>
                    {title}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      )}

      {data.total === 0 ? (
        <Empty />
      ) : (
        <>
          {selected.size > 0 && (
            <BulkBar
              count={selected.size}
              busy={bulk.isPending}
              onKnown={() => bulk.mutate("known")}
              onSuspend={() => bulk.mutate("suspend")}
              onRestore={() => bulk.mutate("restore")}
              onDelete={handleDeleteClick}
            />
          )}

          <DeleteWordsDialog
            count={deleteDialogCount}
            deleting={bulk.isPending}
            onCancel={() => setDeleteDialogCount(null)}
            onConfirm={() => bulk.mutate("forget")}
          />

          {filtered.length > 0 ? (
            <ul className="mt-3 space-y-2">
              <li>
                {/* A `<label>` wrapping a real `<input>` gets this for
                 *  free; `Checkbox` is a styled `<button>` (see its own
                 *  comment) so the click has to be wired onto the row
                 *  itself too, or only the small square would answer. */}
                <label
                  onClick={toggleSelectAll}
                  className="flex items-center gap-2 px-1 py-1 text-xs text-muted-foreground"
                >
                  <Checkbox checked={allVisibleSelected} onChange={toggleSelectAll} />
                  Select all ({filtered.length})
                </label>
              </li>
              {filtered.map((word) =>
                pendingDeletes.has(word.lemma) ? (
                  <RemovedRow
                    key={word.lemma}
                    lemma={word.lemma}
                    onUndo={() => undoDelete(word.lemma)}
                  />
                ) : (
                  <Word
                    key={word.lemma}
                    word={word}
                    selected={selected.has(word.lemma)}
                    onToggleSelected={() => toggleSelected(word.lemma)}
                    onAction={(action) => rowAction.mutate({ lemma: word.lemma, action })}
                    actionBusy={rowAction.isPending}
                    onDelete={() => scheduleDelete(word.lemma)}
                  />
                ),
              )}
            </ul>
          ) : (
            <p className="mt-8 text-center text-xs text-muted-foreground">
              No words match these filters.
            </p>
          )}
        </>
      )}
    </div>
  );
}

function PillRow<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly (readonly [T, string])[];
  onChange: (value: T) => void;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="flex flex-wrap items-center gap-1.5 text-xs"
    >
      <span className="text-muted-foreground">{label}</span>
      {options.map(([opt, text]) => {
        const on = value === opt;
        return (
          <button
            key={opt}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(opt)}
            className={cn(
              "rounded-full px-2.5 py-1 font-medium transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
              on
                ? "bg-primary/20 text-primary"
                : "bg-surface-hover text-muted-foreground hover:text-foreground",
            )}
          >
            {text}
          </button>
        );
      })}
    </div>
  );
}

/** A checkbox drawn the app's own way rather than the browser's — a square
 *  that matches the tick `ReviewVocabulary`'s Save button already wears,
 *  so "this row is selected" and "this word is saved" read as the same
 *  kind of fact rather than two different widgets doing the same job. */
function Checkbox({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: () => void;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-label={label}
      onClick={(e) => {
        e.stopPropagation();
        onChange();
      }}
      className={cn(
        "flex size-5 shrink-0 items-center justify-center rounded-md border transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        checked
          ? "border-primary bg-primary/20 text-primary"
          : "border-border text-transparent hover:border-primary/50",
      )}
    >
      <Check className="size-3.5" aria-hidden />
    </button>
  );
}

/** The bulk action bar. Delete no longer confirms IN the bar — pressing it
 *  with exactly one word selected defers straight to "Removed · Undo" (no
 *  question to ask), and with more than one it opens `DeleteWordsDialog`;
 *  either way `onDelete` is the same press, and the caller is the one that
 *  knows which of the two `count` calls for. */
function BulkBar({
  count,
  busy,
  onKnown,
  onSuspend,
  onRestore,
  onDelete,
}: {
  count: number;
  busy: boolean;
  onKnown: () => void;
  onSuspend: () => void;
  onRestore: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-surface-sunken px-3 py-2">
      <p className="text-sm text-foreground">{count} selected</p>
      <div className="flex flex-wrap gap-1.5">
        <Button type="button" variant="outline" size="sm" disabled={busy} onClick={onKnown}>
          {ACTION_LABEL.markKnown}
        </Button>
        <Button type="button" variant="outline" size="sm" disabled={busy} onClick={onSuspend}>
          {ACTION_LABEL.setAside}
        </Button>
        <Button type="button" variant="outline" size="sm" disabled={busy} onClick={onRestore}>
          {ACTION_LABEL.returnToRotation}
        </Button>
        <Button
          type="button"
          variant="destructive"
          size="sm"
          disabled={busy}
          onClick={onDelete}
        >
          Delete
        </Button>
      </div>
    </div>
  );
}

/** The word's own meaning, said once. Prefers the field stage 2 put on the
 *  word itself; falls back to a context that has one, exactly as stage 1's
 *  saved list already did — a word kept before either field existed has
 *  neither, and prints nothing rather than guessing. */
function wordMeaning(word: SavedWord): { en: string; uz: string } {
  if (word.meaning_core_en || word.meaning_core_uz) {
    return { en: word.meaning_core_en, uz: word.meaning_core_uz };
  }
  const core = word.contexts.find((c) => c.meaning_core_en) ?? word.contexts[0];
  return {
    en: core?.meaning_core_en || core?.meaning_en || "",
    uz: core?.meaning_core_uz || core?.meaning_uz || "",
  };
}

/** The earlier of the two directions' due dates — the date this row would
 *  next pull the learner back in, whichever card gets there first. */
function earliestDue(word: SavedWord): string | null {
  const dates = [word.passive_due, word.active_due].filter(
    (d): d is string => Boolean(d),
  );
  if (!dates.length) return null;
  return dates.reduce((a, b) => (new Date(a) < new Date(b) ? a : b));
}

/** One row: word, part of speech, CEFR chip, usual meaning, next review —
 *  exactly the fixes brief's §7 list. Actions live in the menu at the row's
 *  end, never inline, so the status chip (a fact) and the menu (an
 *  invitation to act) cannot be mistaken for each other. Resolving a leech
 *  word's three-way fork is not one of these four — that lives on the word
 *  page (F5), which this row already links to. */
function Word({
  word,
  selected,
  onToggleSelected,
  onAction,
  actionBusy,
  onDelete,
}: {
  word: SavedWord;
  selected: boolean;
  onToggleSelected: () => void;
  onAction: (action: Exclude<BulkAction, "forget">) => void;
  actionBusy: boolean;
  onDelete: () => void;
}) {
  const meaning = wordMeaning(word);
  const due = earliestDue(word);

  return (
    <li
      className={cn(
        "rounded-xl border px-4 py-3 transition-colors duration-fast",
        selected ? "border-primary/50 bg-primary/5" : "border-border",
      )}
    >
      <div className="flex items-start gap-3">
        <Checkbox
          checked={selected}
          onChange={onToggleSelected}
          label={`Select ${word.lemma}`}
        />
        <Link
          to={`/vocabulary/words/${encodeURIComponent(word.lemma)}`}
          className="min-w-0 flex-1 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <p className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
            <span className="text-base font-semibold text-foreground">
              {word.lemma}
            </span>
            {word.pos && (
              <span className="text-xs text-muted-foreground italic">{word.pos}</span>
            )}
            <CefrTag level={word.cefr_level} />
            <StatusChip status={word.status} />
            {word.active_level && (
              <span className="text-[0.7rem] text-muted-foreground">
                · {word.active_paused ? "active, paused" : "also active"}
              </span>
            )}
          </p>
          {(meaning.uz || meaning.en) && (
            <p className="mt-0.5 text-sm text-foreground">
              {meaning.uz}
              {meaning.en && (
                <span className="ml-1.5 text-xs text-muted-foreground">
                  {meaning.en}
                </span>
              )}
            </p>
          )}
          <p className="mt-1 text-xs text-muted-foreground">
            {word.status === "known"
              ? STATUS_CHIP_LABEL.known
              : word.status === "suspended"
                ? `back ${daysUntil(word.suspended_until)}`
                : word.status === "leech"
                  ? "stuck — open to choose"
                  : due
                    ? `next review ${timeUntil(due)}`
                    : "not yet scheduled"}
          </p>
        </Link>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              title={`${word.lemma} actions`}
              aria-label={`${word.lemma} actions`}
              className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors duration-fast hover:bg-surface-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              <EllipsisVertical className="size-4" aria-hidden />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            {word.status !== "known" && (
              <DropdownMenuItem disabled={actionBusy} onClick={() => onAction("known")}>
                {ACTION_LABEL.markKnown}
              </DropdownMenuItem>
            )}
            {(word.status === "known" || word.status === "suspended") && (
              <DropdownMenuItem disabled={actionBusy} onClick={() => onAction("restore")}>
                {ACTION_LABEL.returnToRotation}
              </DropdownMenuItem>
            )}
            {word.status !== "suspended" && (
              <DropdownMenuItem disabled={actionBusy} onClick={() => onAction("suspend")}>
                {ACTION_LABEL.setAside}
              </DropdownMenuItem>
            )}
            <DropdownMenuItem variant="destructive" onClick={onDelete}>
              Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </li>
  );
}

/** What a deleted row becomes for the few seconds it can still be undone —
 *  same slot in the list the word's own row held, so nothing above or below
 *  it moves. Pressing Undo just calls `undoDelete`; nothing was ever sent to
 *  the server, so there is nothing else to reverse. */
function RemovedRow({ lemma, onUndo }: { lemma: string; onUndo: () => void }) {
  return (
    <li className="flex items-center gap-1.5 rounded-xl border border-dashed border-border px-4 py-3 text-sm text-muted-foreground">
      <span>Removed</span>
      <span aria-hidden>·</span>
      <button
        type="button"
        onClick={onUndo}
        aria-label={`Undo removing ${lemma}`}
        className="font-medium text-primary transition-colors hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        Undo
      </button>
    </li>
  );
}

/** Nothing saved yet, said in terms of the thing that fills it. A list that
 *  explains only that it is empty leaves the reader to guess how it stops
 *  being. */
function Empty() {
  return (
    <div className="mt-4 rounded-xl border border-dashed border-border px-5 py-10 text-center">
      <p className="text-sm text-muted-foreground">
        Sit a reading passage, and the words worth learning from it are waiting
        on the review page afterwards — with what each one means in that
        passage.
      </p>
      <Link
        to="/reading"
        className="mt-4 inline-flex items-center gap-1.5 text-sm text-primary transition-colors hover:underline"
      >
        <BookOpen className="size-3.5" aria-hidden />
        Find a passage
      </Link>
    </div>
  );
}

/** The page's shape, held open while it loads. Built from the real
 *  component's own class strings — `frontend/CLAUDE.md`. */
function ListSkeleton() {
  return (
    <SkeletonBlock
      label="Loading your words"
      className="mx-auto w-full max-w-2xl pb-24"
    >
      <header className="pt-2 pb-4">
        <h1 className="text-2xl font-semibold">
          <Skeleton className="inline-block h-[0.8em] w-40" />
        </h1>
        <p className="mt-1 text-sm">
          <Skeleton className="inline-block h-[0.8em] w-52" />
        </p>
      </header>
      <Skeleton className="h-6 w-full max-w-md rounded-full" />
      <ul className="mt-3 space-y-2">
        {[0, 1, 2].map((row) => (
          <li key={row} className="rounded-xl border border-border px-4 py-3">
            <p className="text-base">
              <Skeleton className="inline-block h-[0.8em] w-28" />
            </p>
            <p className="mt-1 text-sm">
              <Skeleton className="inline-block h-[0.8em] w-52" />
            </p>
            <p className="text-xs">
              <Skeleton className="inline-block h-[0.8em] w-40" />
            </p>
          </li>
        ))}
      </ul>
    </SkeletonBlock>
  );
}
