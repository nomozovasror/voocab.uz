import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, ChevronUp, Pencil, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { useStudioCrumbs } from "@/components/studio/breadcrumbs";
import { cn } from "@/lib/utils";
import { getErrorMessage } from "@/lib/api";
import { toast } from "@/lib/toast";
import { timeAgo } from "@/lib/time";
import {
  useApproveSense,
  useFixSense,
  useReviewContexts,
  useReviewQueue,
} from "@/features/lexicon/queries";
import {
  CEFR_LEVELS,
  CORE_REASON,
  REASON_LABEL,
  REVIEW_REASONS,
} from "@/features/lexicon/reasons";
import type { ReviewRow } from "@/features/lexicon/types";

const PAGE_SIZE = 50;

// ── Small building blocks ────────────────────────────────────────────────

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded bg-card px-1.5 py-0.5 font-mono text-foreground">
      {children}
    </kbd>
  );
}

function ReasonChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number | null;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "rounded-full px-3 py-1 text-xs whitespace-nowrap transition-colors",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        active
          ? "bg-primary/15 text-primary"
          : "bg-surface-sunken text-muted-foreground hover:text-foreground",
      )}
    >
      {label}
      {count != null && (
        <span className="ml-1.5 tabular-nums opacity-70">{count}</span>
      )}
    </button>
  );
}

/** Every reason the sense currently carries, in words a reviewer reads once
 *  rather than looking up a code — see `REASON_LABEL`. */
function ReasonBadges({ reasons }: { reasons: string[] }) {
  if (reasons.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {reasons.map((reason) => (
        <span
          key={reason}
          className="rounded-full bg-destructive/10 px-2 py-0.5 text-xs text-destructive"
        >
          {REASON_LABEL[reason as keyof typeof REASON_LABEL] ?? reason}
        </span>
      ))}
    </div>
  );
}

function EditForm({
  row,
  onCancel,
  onSave,
  saving,
}: {
  row: ReviewRow;
  onCancel: () => void;
  onSave: (payload: { meaning_uz: string; definition_en: string; cefr: string }) => void;
  saving: boolean;
}) {
  const [meaningUz, setMeaningUz] = useState(row.meaning_uz);
  const [definitionEn, setDefinitionEn] = useState(row.definition_en);
  const [cefr, setCefr] = useState(row.cefr ?? "");

  const fieldClass =
    "w-full rounded-lg border border-transparent bg-card px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus-visible:border-border-strong focus-visible:outline-none";

  return (
    <form
      className="mt-3 space-y-2.5 rounded-lg border border-dashed border-border p-3"
      onSubmit={(e) => {
        e.preventDefault();
        onSave({ meaning_uz: meaningUz, definition_en: definitionEn, cefr });
      }}
    >
      <div>
        <label className="mb-1 block font-mono text-xs text-muted-foreground">
          Definition (English)
        </label>
        <input
          className={fieldClass}
          value={definitionEn}
          onChange={(e) => setDefinitionEn(e.target.value)}
          maxLength={400}
        />
      </div>
      <div>
        <label className="mb-1 block font-mono text-xs text-muted-foreground">
          Meaning (Uzbek)
        </label>
        <input
          className={fieldClass}
          value={meaningUz}
          onChange={(e) => setMeaningUz(e.target.value)}
          maxLength={400}
        />
      </div>
      <div>
        <label className="mb-1 block font-mono text-xs text-muted-foreground">
          CEFR level
        </label>
        <select
          className={cn(fieldClass, "font-mono")}
          value={cefr}
          onChange={(e) => setCefr(e.target.value)}
        >
          <option value="">— unrated —</option>
          {CEFR_LEVELS.map((level) => (
            <option key={level} value={level}>
              {level}
            </option>
          ))}
        </select>
      </div>
      <div className="flex justify-end gap-2 font-mono">
        <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
          cancel
        </Button>
        <Button type="submit" size="sm" disabled={saving}>
          {saving ? "saving…" : "save & approve"}
        </Button>
      </div>
    </form>
  );
}

function ContextsPeek({ senseId }: { senseId: string }) {
  const { data, isLoading, isError } = useReviewContexts(senseId);
  return (
    <div className="mt-3 space-y-2 rounded-lg bg-surface-sunken p-3">
      {isLoading ? (
        <>
          <Skeleton className="h-3 w-3/4" />
          <Skeleton className="h-3 w-1/2" />
        </>
      ) : isError ? (
        <p className="text-xs text-muted-foreground">
          Couldn't load material sentences.
        </p>
      ) : !data || data.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          Not used in any material yet.
        </p>
      ) : (
        data.map((ctx, i) => (
          <div key={i} className="text-xs leading-relaxed">
            <span className="text-foreground">{ctx.example}</span>
            <span className="ml-2 text-muted-foreground">— {ctx.material_title}</span>
          </div>
        ))
      )}
    </div>
  );
}

interface RowProps {
  row: ReviewRow;
  selected: boolean;
  editing: boolean;
  peeking: boolean;
  innerRef: (el: HTMLDivElement | null) => void;
  onFocus: () => void;
  onApprove: () => void;
  onEditToggle: () => void;
  onPeekToggle: () => void;
  onSave: (payload: { meaning_uz: string; definition_en: string; cefr: string }) => void;
  approving: boolean;
  saving: boolean;
}

function Row({
  row,
  selected,
  editing,
  peeking,
  innerRef,
  onFocus,
  onApprove,
  onEditToggle,
  onPeekToggle,
  onSave,
  approving,
  saving,
}: RowProps) {
  return (
    <div
      ref={innerRef}
      tabIndex={0}
      onFocus={onFocus}
      className={cn(
        "rounded-lg bg-card/70 px-5 py-4 transition-colors duration-150",
        "focus-visible:outline-none",
        selected && "ring-1 ring-primary/60",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="text-base font-medium text-foreground">
              {row.lemma}
            </span>
            {row.pos && (
              <span className="font-mono text-xs text-muted-foreground">
                {row.pos}
              </span>
            )}
            {row.is_phrase && (
              <span className="rounded-full bg-foreground/8 px-1.5 py-0.5 text-xs text-muted-foreground">
                phrase
              </span>
            )}
            <span className="rounded border border-border px-1.5 py-px font-mono text-xs text-muted-foreground">
              {row.cefr ?? "—"}
            </span>
            {row.frequency_band && (
              <span className="font-mono text-xs text-muted-foreground">
                {row.frequency_band}
              </span>
            )}
            {row.approved_at && (
              <span className="rounded-full bg-success/10 px-1.5 py-0.5 text-xs text-success">
                approved {timeAgo(row.approved_at)}
              </span>
            )}
          </div>

          <p className="mt-1.5 text-sm text-foreground">{row.definition_en}</p>
          <p className="text-sm text-muted-foreground">{row.meaning_uz}</p>
          {row.meaning_uz_alt && (
            <p className="mt-0.5 text-xs text-muted-foreground">
              Other translation: {row.meaning_uz_alt}
            </p>
          )}
          {row.meaning_uz_material && (
            <p className="mt-0.5 text-xs text-muted-foreground">
              From a material: {row.meaning_uz_material}
            </p>
          )}

          <div className="mt-2">
            <ReasonBadges reasons={row.review_reasons} />
          </div>

          {editing && (
            <EditForm row={row} onCancel={onEditToggle} onSave={onSave} saving={saving} />
          )}
          {peeking && !editing && <ContextsPeek senseId={row.sense_id} />}
        </div>

        <div className="flex shrink-0 items-center gap-1.5 font-mono">
          <button
            type="button"
            onClick={onPeekToggle}
            aria-expanded={peeking}
            aria-label={
              row.material_example_count > 0
                ? `Peek at ${row.material_example_count} material sentence(s)`
                : "No material sentences yet"
            }
            title="Peek at material sentences"
            disabled={row.material_example_count === 0}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            {row.material_example_count}
            {peeking ? (
              <ChevronUp className="size-3.5" />
            ) : (
              <ChevronDown className="size-3.5" />
            )}
          </button>
          <button
            type="button"
            onClick={onEditToggle}
            aria-label="Fix"
            title="Fix (E)"
            className={cn(
              "flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-foreground/5 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
              editing && "bg-foreground/5 text-foreground",
            )}
          >
            {editing ? <X className="size-4" /> : <Pencil className="size-4" />}
          </button>
          <button
            type="button"
            onClick={onApprove}
            disabled={approving}
            aria-label="Approve"
            title="Approve (A)"
            className="flex size-8 items-center justify-center rounded-md text-success transition-colors hover:bg-success/10 disabled:opacity-40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            <Check className="size-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

function RowSkeleton() {
  return (
    <div className="space-y-2 rounded-lg bg-card/70 px-5 py-4" aria-hidden>
      <div className="flex gap-2">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-4 w-8" />
        <Skeleton className="h-4 w-8" />
      </div>
      <Skeleton className="h-3.5 w-3/4" />
      <Skeleton className="h-3.5 w-1/2" />
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────

export default function StudioReviewPage() {
  useStudioCrumbs([{ label: "review" }]);

  const [reason, setReason] = useState<string | null>(null);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const { data, isLoading, isError, error, refetch } = useReviewQueue(reason, limit);

  const rows = useMemo(() => data?.rows ?? [], [data]);

  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [peekingId, setPeekingId] = useState<string | null>(null);
  const rowRefs = useRef<Array<HTMLDivElement | null>>([]);

  const approveSense = useApproveSense();
  const fixSense = useFixSense();

  // A narrowed filter, a reload, or an approval leaving the page shorter
  // than the old highlight would keep the ring on a row that is gone.
  useEffect(() => {
    setSelectedIndex(null);
    setEditingId(null);
    setPeekingId(null);
  }, [reason]);

  const focusRow = (i: number) => rowRefs.current[i]?.focus();

  const approve = (row: ReviewRow) => {
    approveSense.mutate(row.sense_id, {
      onSuccess: () => {
        toast({ title: "Approved", message: `“${row.lemma}” is cleared.`, kind: "success" });
      },
      onError: (e) => {
        toast({ title: "Not approved", message: getErrorMessage(e), kind: "error" });
      },
    });
  };

  const save = (
    row: ReviewRow,
    payload: { meaning_uz: string; definition_en: string; cefr: string },
  ) => {
    fixSense.mutate(
      {
        senseId: row.sense_id,
        payload: {
          meaning_uz: payload.meaning_uz,
          definition_en: payload.definition_en,
          cefr: payload.cefr || undefined,
        },
      },
      {
        onSuccess: () => {
          setEditingId(null);
          toast({ title: "Fixed", message: `“${row.lemma}” saved and approved.`, kind: "success" });
        },
        onError: (e) => {
          toast({ title: "Not saved", message: getErrorMessage(e), kind: "error" });
        },
      },
    );
  };

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      // The edit form's own fields (and the CEFR select) own their own
      // keystrokes — j/k/a/e must not fire while somebody is typing a
      // translation that happens to contain one of those letters.
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (target?.isContentEditable) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (rows.length === 0) return;

      if (e.key === "Escape") {
        if (editingId) setEditingId(null);
        else if (peekingId) setPeekingId(null);
        return;
      }

      if (e.key === "j" || e.key === "J" || e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((prev) => {
          const next = prev === null ? 0 : Math.min(prev + 1, rows.length - 1);
          focusRow(next);
          return next;
        });
        return;
      }
      if (e.key === "k" || e.key === "K" || e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((prev) => {
          const next = prev === null ? 0 : Math.max(prev - 1, 0);
          focusRow(next);
          return next;
        });
        return;
      }
      if (selectedIndex === null) return;
      const row = rows[selectedIndex];
      if (!row) return;

      if (e.key === "a" || e.key === "A") {
        e.preventDefault();
        approve(row);
      } else if (e.key === "e" || e.key === "E") {
        e.preventDefault();
        setEditingId((prev) => (prev === row.sense_id ? null : row.sense_id));
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, selectedIndex, editingId, peekingId]);

  return (
    <div className="studio-panel">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <ReasonChip
          label="All"
          count={null}
          active={reason === null}
          onClick={() => setReason(null)}
        />
        {REVIEW_REASONS.map((r) => (
          <ReasonChip
            key={r}
            label={REASON_LABEL[r]}
            count={data?.reason_counts[r] ?? null}
            active={reason === r}
            onClick={() => setReason(r)}
          />
        ))}
        <ReasonChip
          label="Core (top frequency)"
          count={data?.core_pending ?? null}
          active={reason === CORE_REASON}
          onClick={() => setReason(CORE_REASON)}
        />
      </div>

      {isError ? (
        <div className="rounded-lg border border-dashed border-border px-5 py-10 text-center">
          <p className="text-sm text-muted-foreground">
            {getErrorMessage(error) || "Couldn't load the review queue."}
          </p>
          <Button
            variant="outline"
            size="sm"
            className="mt-4 font-mono lowercase"
            onClick={() => void refetch()}
          >
            try again
          </Button>
        </div>
      ) : isLoading ? (
        <SkeletonBlock label="Loading the review queue" className="space-y-2.5">
          <RowSkeleton />
          <RowSkeleton />
          <RowSkeleton />
        </SkeletonBlock>
      ) : rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border px-5 py-10 text-center text-sm text-muted-foreground">
          Nothing waiting for review here.
        </p>
      ) : (
        <>
          <div className="space-y-2.5">
            {rows.map((row, i) => (
              <Row
                key={row.sense_id}
                row={row}
                selected={selectedIndex === i}
                editing={editingId === row.sense_id}
                peeking={peekingId === row.sense_id}
                innerRef={(el) => (rowRefs.current[i] = el)}
                onFocus={() => setSelectedIndex(i)}
                onApprove={() => approve(row)}
                onEditToggle={() =>
                  setEditingId((prev) => (prev === row.sense_id ? null : row.sense_id))
                }
                onPeekToggle={() =>
                  setPeekingId((prev) => (prev === row.sense_id ? null : row.sense_id))
                }
                onSave={(payload) => save(row, payload)}
                approving={approveSense.isPending}
                saving={fixSense.isPending}
              />
            ))}
          </div>
          {data && rows.length < data.total && (
            <div className="mt-4 flex justify-center">
              <Button
                variant="outline"
                size="sm"
                className="font-mono lowercase"
                onClick={() => setLimit((l) => l + PAGE_SIZE)}
              >
                load more ({rows.length} of {data.total})
              </Button>
            </div>
          )}
        </>
      )}

      <div className="mt-6 flex flex-wrap gap-5 font-mono text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <Kbd>J</Kbd>/<Kbd>K</Kbd> move
        </span>
        <span className="flex items-center gap-1.5">
          <Kbd>A</Kbd> approve
        </span>
        <span className="flex items-center gap-1.5">
          <Kbd>E</Kbd> edit
        </span>
        <span className="flex items-center gap-1.5">
          <Kbd>Esc</Kbd> close
        </span>
      </div>
    </div>
  );
}
