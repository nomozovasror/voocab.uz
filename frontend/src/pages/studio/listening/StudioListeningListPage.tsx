import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useStudioCrumbs } from "@/components/studio/breadcrumbs";
import { cn } from "@/lib/utils";
import { getErrorMessage } from "@/lib/api";
import { toast } from "@/lib/toast";
import { formatClock, formatHours, formatQuestionType } from "@/features/studio/format";
import { DeleteMaterialDialog } from "@/components/studio/DeleteMaterialDialog";
import { useStudioListening } from "@/features/studio/queries";
import { useDeleteListeningMaterial } from "@/features/listening/queries";
import type { StudioListeningItem } from "@/features/studio/types";

const DASH = "—"; // "no data yet" marker — never a fabricated 0

// ── Small building blocks ────────────────────────────────────────────────

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded bg-card px-1.5 py-0.5 font-mono text-foreground">
      {children}
    </kbd>
  );
}

function KeyboardHints() {
  return (
    <div className="mt-6 flex flex-wrap gap-5 text-xs text-muted-foreground">
      <span className="flex items-center gap-1.5">
        <Kbd>n</Kbd> new material
      </span>
      <span className="flex items-center gap-1.5">
        <Kbd>↑↓</Kbd> navigate
      </span>
      <span className="flex items-center gap-1.5">
        <Kbd>↵</Kbd> open
      </span>
      <span className="flex items-center gap-1.5">
        <Kbd>⌫</Kbd> delete
      </span>
    </div>
  );
}

interface CreateTileProps {
  selected: boolean;
  big?: boolean;
  innerRef: (el: HTMLAnchorElement | null) => void;
  onFocus: () => void;
}

function CreateTile({ selected, big, innerRef, onFocus }: CreateTileProps) {
  return (
    <Link
      ref={innerRef}
      to="/studio/listening/new"
      onFocus={onFocus}
      className={cn(
        "group flex w-full items-center gap-3.5 rounded-lg border border-dashed px-5 py-5 text-left text-muted-foreground transition-colors duration-150",
        "hover:border-primary hover:text-foreground focus-visible:border-primary focus-visible:text-foreground focus-visible:outline-none",
        selected ? "border-primary text-foreground" : "border-border",
        big && "flex-col items-center justify-center gap-2 py-16 text-center",
      )}
    >
      <span
        aria-hidden
        className={cn("leading-none text-primary", big ? "text-3xl" : "text-xl")}
      >
        +
      </span>
      <span className={big ? "" : "block"}>
        <span className="block text-foreground">new listening material</span>
        <span className="mt-1 block text-xs text-muted-foreground">
          upload audio, add parts and questions
        </span>
      </span>
    </Link>
  );
}

function StatusPill({ item }: { item: StudioListeningItem }) {
  const processing =
    item.transcript_status === "pending" || item.transcript_status === "processing";
  const { label, cls } = processing
    ? { label: "processing", cls: "bg-primary/15 text-primary" }
    : item.visibility === "public"
      ? { label: "public", cls: "bg-foreground/8 text-foreground/80" }
      : { label: "draft", cls: "bg-foreground/5 text-muted-foreground" };
  return (
    <span className={cn("shrink-0 rounded-full px-2.5 py-0.5 text-xs", cls)}>
      {label}
    </span>
  );
}

function buildMeta(item: StudioListeningItem): string {
  const parts: string[] = [];
  const clock = formatClock(item.duration_ms);
  parts.push(clock ?? "no audio yet");

  // All of the kinds it holds, not the first: a part can mix form completion
  // and multiple choice, and naming one of them would label the whole
  // material after half of it.
  if (item.question_types.length > 0) {
    parts.push(item.question_types.map(formatQuestionType).join(" + "));
    parts.push(`${item.question_count} question${item.question_count === 1 ? "" : "s"}`);
  } else if (item.question_count === 0) {
    // Honesty rule: don't invent a question type — just say there isn't one yet.
    parts.push("no questions yet");
  } else {
    parts.push(`${item.question_count} question${item.question_count === 1 ? "" : "s"}`);
  }
  return parts.join(" · ");
}

interface RowProps {
  item: StudioListeningItem;
  selected: boolean;
  innerRef: (el: HTMLAnchorElement | null) => void;
  onFocus: () => void;
  onDelete: () => void;
}

function ListeningRow({ item, selected, innerRef, onFocus, onDelete }: RowProps) {
  const processing =
    item.transcript_status === "pending" || item.transcript_status === "processing";
  const attemptsDisplay = processing || item.attempts === 0 ? DASH : String(item.attempts);
  const avgDisplay =
    processing || item.avg_score_pct == null ? DASH : `${Math.round(item.avg_score_pct)}%`;

  return (
    // The delete control is a sibling of the link rather than inside it: a
    // button nested in an anchor is neither valid nor clickable without
    // fighting the navigation. It sits over the row's right edge, which the
    // link leaves clear for it.
    <div className="group/row relative">
      <Link
        ref={innerRef}
        to={`/studio/listening/${item.id}`}
        onFocus={onFocus}
        className={cn(
          "flex items-center gap-4 rounded-lg bg-card/70 py-4 pr-14 pl-5 transition-colors duration-150",
          "hover:bg-card focus-visible:bg-card focus-visible:outline-none",
          selected && "ring-1 ring-primary/60",
        )}
      >
        <div className="min-w-0 flex-1">
          <div className="truncate text-foreground">{item.title}</div>
          <div className="mt-0.5 truncate text-xs tabular-nums text-muted-foreground">
            {buildMeta(item)}
          </div>
        </div>
        <StatusPill item={item} />
        <div className="flex shrink-0 gap-5">
          <div className="text-center">
            <div
              className={cn(
                "text-base font-medium tabular-nums",
                attemptsDisplay === DASH ? "text-muted-foreground" : "text-foreground",
              )}
            >
              {attemptsDisplay}
            </div>
            <div className="text-[11px] text-muted-foreground">attempts</div>
          </div>
          <div className="text-center">
            <div
              className={cn(
                "text-base font-medium tabular-nums",
                avgDisplay === DASH ? "text-muted-foreground" : "text-foreground",
              )}
            >
              {avgDisplay}
            </div>
            <div className="text-[11px] text-muted-foreground">avg score</div>
          </div>
        </div>
      </Link>

      <button
        type="button"
        onClick={onDelete}
        aria-label={`Delete ${item.title}`}
        title="Delete this material"
        className="absolute top-1/2 right-3 flex size-8 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity group-hover/row:opacity-100 hover:bg-destructive/10 hover:text-destructive focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <Trash2 className="size-4" aria-hidden />
      </button>
    </div>
  );
}

function RowSkeleton() {
  return (
    <div
      className="flex items-center gap-4 rounded-lg bg-card/70 px-5 py-4"
      aria-hidden
    >
      <div className="min-w-0 flex-1 space-y-2">
        <div className="h-4 w-48 max-w-full animate-pulse rounded bg-foreground/10" />
        <div className="h-3 w-32 max-w-full animate-pulse rounded bg-foreground/10" />
      </div>
      <div className="h-5 w-16 shrink-0 animate-pulse rounded-full bg-foreground/10" />
      <div className="flex shrink-0 gap-5">
        <div className="h-8 w-9 animate-pulse rounded bg-foreground/10" />
        <div className="h-8 w-9 animate-pulse rounded bg-foreground/10" />
      </div>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────

export default function StudioListeningListPage() {
  useStudioCrumbs([{ label: "listening" }]);

  const { data, isLoading, isError, error, refetch } = useStudioListening();
  const navigate = useNavigate();

  // The material the author has asked to delete, held whole rather than by
  // id so the dialog can say what goes with it — and keep saying it while
  // the dialog closes over a row that has already gone.
  const [pendingDelete, setPendingDelete] = useState<StudioListeningItem | null>(
    null,
  );
  const deleteMaterial = useDeleteListeningMaterial();

  const confirmDelete = () => {
    if (!pendingDelete) return;
    const { id, title } = pendingDelete;
    deleteMaterial.mutate(id, {
      onSuccess: () => {
        setPendingDelete(null);
        // The rows below have shifted up by one, so the highlight would land
        // on a material the author never chose.
        setSelectedIndex(null);
        toast({ title: "Deleted", message: `“${title}” is gone.`, kind: "info" });
      },
      onError: (e) => {
        // The dialog stays open on failure: it is where the button that
        // failed is, and closing it would leave the author guessing whether
        // anything happened.
        toast({ title: "Not deleted", message: getErrorMessage(e), kind: "error" });
      },
    });
  };

  const items = useMemo(() => data?.items ?? [], [data]);
  const totalTiles = 1 + items.length; // create tile + rows
  const isEmpty = !isLoading && !isError && (data?.total ?? 0) === 0;

  // Roving selection across [create tile, ...rows]. `null` = nothing selected
  // yet (first arrow press lands on index 0). Real DOM focus is moved along
  // with it (see focusTile), so screen readers announce the focused link's
  // own name — no separate aria-live needed.
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const tileRefs = useRef<Array<HTMLAnchorElement | null>>([]);

  const hrefAt = useCallback(
    (i: number) => (i === 0 ? "/studio/listening/new" : `/studio/listening/${items[i - 1].id}`),
    [items],
  );

  const focusTile = (i: number) => tileRefs.current[i]?.focus();

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (target?.isContentEditable) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      // The confirm dialog holds the screen, and these listen at the window:
      // without this, "n" would navigate away from an open dialog and Enter
      // would open whichever row was highlighted behind it.
      if (pendingDelete) return;

      if (e.key === "n" || e.key === "N") {
        e.preventDefault();
        navigate("/studio/listening/new");
        return;
      }

      if (isLoading || isError || totalTiles === 0) return;

      if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        // Only ever opens the question — the answer stays a deliberate
        // click, so a stray keypress can't delete anything. The selection is
        // read from the closure rather than out of a state updater: an
        // updater has to be pure, and this one would be opening a dialog
        // from inside it.
        if (selectedIndex !== null && selectedIndex > 0) {
          setPendingDelete(items[selectedIndex - 1]);
        }
        return;
      }

      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((prev) => {
          const next = prev === null ? 0 : Math.min(prev + 1, totalTiles - 1);
          focusTile(next);
          return next;
        });
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((prev) => {
          const next = prev === null ? 0 : Math.max(prev - 1, 0);
          focusTile(next);
          return next;
        });
      } else if (e.key === "Enter") {
        setSelectedIndex((prev) => {
          if (prev !== null) {
            e.preventDefault();
            navigate(hrefAt(prev));
          }
          return prev;
        });
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isLoading, isError, totalTiles, navigate, hrefAt, pendingDelete, items, selectedIndex]);

  return (
    <div className="mx-auto w-full max-w-[56.25rem] font-mono">
      {/* The trail lives in the layout header; the title takes its place here. */}
      {!isEmpty && (
        <div className="mb-1 flex items-baseline justify-between gap-4">
          <h1 className="text-2xl font-medium tracking-wide text-foreground">listening</h1>
          {data && !isError && (
            <span className="text-xs tabular-nums text-muted-foreground">
              {data.total} material{data.total === 1 ? "" : "s"} · {formatHours(data.duration_ms)} hours
            </span>
          )}
        </div>
      )}
      {isEmpty && <h1 className="mb-1 text-2xl font-medium tracking-wide text-foreground">listening</h1>}

      {!isEmpty && <p className="mb-7 text-xs text-muted-foreground">your listening materials</p>}

      {isError ? (
        <div className="rounded-lg border border-dashed border-border px-5 py-10 text-center">
          <p className="text-sm text-muted-foreground">
            {getErrorMessage(error) || "couldn't load your listening materials."}
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
      ) : isEmpty ? (
        <div className="flex flex-col items-center gap-4 py-10 text-center">
          <p className="text-sm text-muted-foreground">
            no listening materials yet — create your first one to get started.
          </p>
          <div className="w-full max-w-md">
            <CreateTile
              big
              selected={selectedIndex === 0}
              innerRef={(el) => (tileRefs.current[0] = el)}
              onFocus={() => setSelectedIndex(0)}
            />
          </div>
        </div>
      ) : isLoading ? (
        <div className="space-y-2.5">
          <CreateTile
            selected={false}
            innerRef={() => {}}
            onFocus={() => {}}
          />
          <RowSkeleton />
          <RowSkeleton />
          <RowSkeleton />
        </div>
      ) : (
        <div className="space-y-2.5">
          <CreateTile
            selected={selectedIndex === 0}
            innerRef={(el) => (tileRefs.current[0] = el)}
            onFocus={() => setSelectedIndex(0)}
          />
          {items.map((item, i) => (
            <ListeningRow
              key={item.id}
              item={item}
              selected={selectedIndex === i + 1}
              innerRef={(el) => (tileRefs.current[i + 1] = el)}
              onFocus={() => setSelectedIndex(i + 1)}
              onDelete={() => setPendingDelete(item)}
            />
          ))}
        </div>
      )}

      <KeyboardHints />

      <DeleteMaterialDialog
        material={
          pendingDelete && {
            title: pendingDelete.title,
            visibility: pendingDelete.visibility,
            questionCount: pendingDelete.question_count,
            attempts: pendingDelete.attempts,
          }
        }
        onCancel={() => setPendingDelete(null)}
        onConfirm={confirmDelete}
        deleting={deleteMaterial.isPending}
      />
    </div>
  );
}
