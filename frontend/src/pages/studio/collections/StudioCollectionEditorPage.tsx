import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Eye,
  GripVertical,
  MoreHorizontal,
  Plus,
  RotateCw,
  Trash2,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useStudioCrumbs } from "@/components/studio/breadcrumbs";
import {
  CollectionBanner,
  CoverButton,
} from "@/components/studio/CollectionBanner";
import { useDebounced } from "@/hooks/use-debounced";
import { getErrorMessage } from "@/lib/api";
import { timeAgo } from "@/lib/time";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { formatClock } from "@/features/studio/format";
import { COVER_INK, coverKeyOf, newCoverSeed } from "@/features/listening/cover";
import {
  useCollection,
  useDeleteCollection,
  useMyCollections,
  usePracticeCatalogue,
  useSetCollectionItems,
  useUpdateCollection,
} from "@/features/listening/queries";
import {
  DIFFICULTY_CLASS,
  DIFFICULTY_SHORT,
  describeTask,
  partLabel,
} from "@/features/listening/practice";
import type {
  AuthorCollection,
  PracticeMaterial,
} from "@/features/listening/types";

/**
 * Building one collection: what is in it, and in what order.
 *
 * **Two panes, side by side.** What is in the course and what could go in it
 * are one decision made by comparing them, and stacked — the picker below
 * the list, as this page used to be — the comparison is a scroll: an author
 * adding the fourth paper cannot see the three they already chose. The
 * picker keeps its own scroll (`PICKER_H`), so a library of two hundred
 * never makes the page taller than the screen.
 *
 * **The cover is here too**, beside the title being typed, and it updates as
 * the name is written. The same book the author clicked on the shelf is the
 * book they are inside, which is the whole reason covers are generated from
 * the id in the first place.
 *
 * **Everything saves itself.** The title and the summary on blur, the order
 * a beat after the last move — and one line under the title says so. It used
 * to be an explicit `Save order` button, on the argument that a save per
 * move would publish half-finished sequences; a debounce answers that, and
 * an editor where one of three things has to be saved by hand is an editor
 * that loses work. What cannot be silent is a save that WITHDRAWS the
 * collection (emptying a published one does), and that still says so out
 * loud.
 */

/** The picker's own height. Tall enough to show what the search found,
 *  short enough that the page never scrolls past the pane on the left. */
const PICKER_H = "max-h-[25rem]";

export default function StudioCollectionEditorPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const detail = useCollection(id);
  // The author's own listing carries the two things the learner-facing read
  // does not: whether it is published, and how much of it a learner can
  // actually see.
  const mine = useMyCollections();
  const collection = useMemo(
    () => mine.data?.find((c) => c.id === id),
    [mine.data, id],
  );
  useStudioCrumbs([
    // Collections are a tab of the listening studio, so the trail says so —
    // otherwise the way back out of an editor is a crumb that lands
    // somewhere the header does not admit exists.
    { label: "listening", to: "/studio/listening" },
    { label: "collections", to: "/studio/collections" },
    { label: collection?.title ?? "…" },
  ]);

  const update = useUpdateCollection();
  const setItems = useSetCollectionItems();
  const remove = useDeleteCollection();

  // --- The order, saved a beat after it settles ----------------------------
  const [order, setOrder] = useState<string[]>([]);
  const [seeded, setSeeded] = useState(false);
  useEffect(() => {
    // Seeded once. Re-seeding on every fetch would throw away an in-progress
    // reorder the moment anything else invalidated this query.
    if (seeded || !detail.data) return;
    setOrder(detail.data.items.map((m) => m.id));
    setSeeded(true);
  }, [detail.data, seeded]);

  const stored = useMemo(
    () => detail.data?.items.map((m) => m.id) ?? [],
    [detail.data],
  );
  const dirty =
    seeded &&
    (order.length !== stored.length || order.some((mid, i) => mid !== stored[i]));

  // When the page last wrote something, for the line under the title. An ISO
  // string rather than a flag: "Saved" with no when is a claim about the
  // past that never expires.
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const noteSaved = () => setSavedAt(new Date().toISOString());

  // Titles for the ids we hold, from whichever list has them: the
  // collection's own rows for what was already in it, the picker's for what
  // has just been added and not yet saved.
  const [picked, setPicked] = useState<Record<string, PracticeMaterial>>({});
  const byId = useMemo(() => {
    const map = new Map<string, PracticeMaterial>();
    for (const m of detail.data?.items ?? []) map.set(m.id, m);
    for (const m of Object.values(picked)) map.set(m.id, m);
    return map;
  }, [detail.data, picked]);

  // How long the whole course runs, over what is in it NOW — unsaved
  // additions included, because the band has to agree with the list under
  // it. Null where nothing has a duration: a total that silently skipped
  // half the papers would be a number the author could act on and be wrong.
  const runtime = useMemo(() => {
    const known = order
      .map((mid) => byId.get(mid)?.duration_ms)
      .filter((ms): ms is number => typeof ms === "number");
    if (known.length === 0) return null;
    return formatClock(known.reduce((sum, ms) => sum + ms, 0));
  }, [order, byId]);

  const move = (from: number, to: number) => {
    if (to < 0 || to >= order.length || from === to) return;
    setOrder((prev) => {
      const next = prev.slice();
      const [row] = next.splice(from, 1);
      next.splice(to, 0, row);
      return next;
    });
  };

  const add = (m: PracticeMaterial) => {
    setPicked((prev) => ({ ...prev, [m.id]: m }));
    setOrder((prev) => (prev.includes(m.id) ? prev : [...prev, m.id]));
  };

  // The last payload we tried, so a server that comes back with a different
  // list than it was sent — it drops duplicates and anything deleted since —
  // cannot leave `dirty` true and put this in a loop.
  const attempted = useRef<string | null>(null);
  const published = collection?.visibility === "public";

  // The stable halves of two query objects. The objects themselves are new
  // on every render, and depending on them would clear and re-arm the timer
  // below every time anything else on this page re-rendered — which is a
  // debounce that can be starved into never firing.
  const saveItems = setItems.mutate;
  const refetchDetail = detail.refetch;
  const savePending = setItems.isPending;

  useEffect(() => {
    if (!id || !dirty || savePending) return;
    const payload = order.join(",");
    if (attempted.current === payload) return;

    // A beat, not a keystroke. Dragging a row past three others is four
    // moves and one intent, and a request per move would publish every
    // half-finished sequence in between to anybody reading.
    const timer = setTimeout(() => {
      attempted.current = payload;
      saveItems(
        { id, materialIds: order },
        {
          onSuccess: (result) => {
            void refetchDetail();
            noteSaved();
            // Publishing can be withdrawn by a save that empties a
            // collection. Said out loud, because a flag that changed itself
            // and stayed quiet is a flag the author hears about from a
            // learner.
            if (result.visibility === "private" && published) {
              toast("Withdrawn: a published collection can't be empty.", "warning");
            }
          },
          onError: (err) => toast(getErrorMessage(err)),
        },
      );
    }, 700);
    return () => clearTimeout(timer);
  }, [id, dirty, order, published, saveItems, refetchDetail, savePending]);

  if (detail.isError) {
    return (
      <div className="mx-auto w-full max-w-[62.5rem] py-8 font-mono">
        <p className="text-sm text-muted-foreground">
          {getErrorMessage(detail.error) || "Couldn't load this collection."}
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-[62.5rem] pb-16 font-mono">
      <Link
        to="/studio/collections"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" aria-hidden />
        All collections
      </Link>

      {collection ? (
        <Details
          collection={collection}
          count={order.length}
          runtime={runtime}
          saving={update.isPending || setItems.isPending}
          savedAt={savedAt}
          dirty={dirty}
          onSave={(fields) =>
            update.mutate(
              { id: collection.id, ...fields },
              { onSuccess: noteSaved, onError: (err) => toast(getErrorMessage(err)) },
            )
          }
          onReroll={() =>
            update.mutate(
              { id: collection.id, cover_seed: newCoverSeed() },
              {
                onSuccess: noteSaved,
                onError: (err) => toast(getErrorMessage(err)),
              },
            )
          }
          onDelete={() =>
            remove.mutate(collection.id, {
              onSuccess: () => navigate("/studio/collections"),
              onError: (err) => toast(getErrorMessage(err)),
            })
          }
          busy={update.isPending || remove.isPending}
        />
      ) : (
        <DetailsSkeleton />
      )}

      {/* Two panes, and the gap between them is the point: the left is the
          course, the right is everywhere it could come from. */}
      <div className="mt-7 grid items-start gap-7 lg:grid-cols-2">
        <InCollection
          order={order}
          byId={byId}
          loading={detail.isLoading}
          onMove={move}
          onRemove={(materialId) =>
            setOrder((prev) => prev.filter((x) => x !== materialId))
          }
        />
        <Picker inCollection={order} onAdd={add} />
      </div>
    </div>
  );
}

// ── The header: cover, name, and what has been saved ──────────────────────

/** Title, summary, cover and the publish control.
 *
 *  Saved on blur rather than on every keystroke: these are two short fields
 *  somebody edits once, and a request per character to keep them in step with
 *  a name being typed is a lot of noise for no benefit. */
function Details({
  collection,
  count,
  runtime,
  saving,
  savedAt,
  dirty,
  onSave,
  onReroll,
  onDelete,
  busy,
}: {
  collection: AuthorCollection;
  /** What is in it RIGHT NOW, unsaved additions included — the banner has to
   *  agree with the list under it, not with the last request. */
  count: number;
  /** How long the whole course runs, `18:20`, or null where nothing in it
   *  has a duration yet. */
  runtime: string | null;
  saving: boolean;
  savedAt: string | null;
  dirty: boolean;
  onSave: (fields: {
    title?: string;
    summary?: string;
    visibility?: string;
    cover_seed?: string;
  }) => void;
  onReroll: () => void;
  onDelete: () => void;
  busy: boolean;
}) {
  const [title, setTitle] = useState(collection.title);
  const [summary, setSummary] = useState(collection.summary);
  const published = collection.visibility === "public";
  const hidden = collection.item_count - collection.public_item_count;

  return (
    <>
      <CollectionBanner coverKey={coverKeyOf(collection)} className="mt-4">
        {/* Top: what it is called, and what can be done to it. */}
        <div className="flex items-start gap-4">
          <div className="min-w-0 flex-1">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onBlur={() =>
                title.trim() && title !== collection.title
                  ? onSave({ title: title.trim() })
                  : setTitle(collection.title)
              }
              aria-label="Collection title"
              placeholder="Name this collection"
              maxLength={200}
              className="cover-field w-full bg-transparent pb-1 text-2xl leading-tight font-medium outline-none"
              style={{ color: COVER_INK.title }}
            />
            <input
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              onBlur={() =>
                summary !== collection.summary
                  ? onSave({ summary: summary.trim() })
                  : undefined
              }
              placeholder="One line about what it's for"
              aria-label="Collection summary"
              maxLength={300}
              className="cover-field cover-field-sub mt-2 w-full bg-transparent pb-1 text-xs outline-none"
              style={{ color: COVER_INK.faint }}
            />
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {/* A cover nobody chose can still be a cover nobody wants. The
                seed is the only thing about a collection's book an author
                can change, and this is how they change it — a new stock, a
                new pattern, a new cut, everywhere the course appears. */}
            <CoverButton onClick={onReroll} disabled={busy} title="Different cover">
              <RotateCw className="size-3.5" aria-hidden />
              Cover
            </CoverButton>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <CoverButton
                  className="px-2"
                  aria-label="More actions"
                  disabled={busy}
                >
                  <MoreHorizontal className="size-4" aria-hidden />
                </CoverButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="font-mono">
                {published && (
                  <DropdownMenuItem asChild>
                    <Link to={`/listening/collections/${collection.id}`}>
                      <Eye className="size-3.5" aria-hidden />
                      See it as a learner does
                    </Link>
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem
                  variant="destructive"
                  disabled={busy}
                  onSelect={onDelete}
                >
                  <Trash2 className="size-3.5" aria-hidden />
                  Delete collection
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>

            <CoverButton
              live
              disabled={busy || (!published && !!collection.blocker)}
              title={(!published && collection.blocker) || undefined}
              onClick={() =>
                onSave({ visibility: published ? "private" : "public" })
              }
            >
              {published ? "Withdraw" : "Publish"}
            </CoverButton>
          </div>
        </div>

        {/* Foot: what is in it, what state it is in, and when it was last
            written down — the same three facts the shelf's cover carries,
            with room here to say them in full. */}
        <div
          className="flex items-center gap-3 text-xs"
          style={{ color: COVER_INK.faint }}
        >
          <span className="tabular-nums">
            {count === 0
              ? "Empty"
              : `${count} material${count === 1 ? "" : "s"}`}
            {runtime && ` · ${runtime}`}
          </span>

          <span
            className="rounded-full px-2 py-0.5"
            style={{
              backgroundColor: COVER_INK.plate,
              color: published ? COVER_INK.plateText : COVER_INK.plateWarn,
            }}
          >
            {published ? "Public" : "Draft"}
          </span>

          <SaveState
            saving={saving}
            savedAt={savedAt}
            dirty={dirty}
            className="ml-auto"
          />
        </div>
      </CollectionBanner>

      {/* Under the band, and only when there is something to say. The banner
          carries the state; this carries the one thing an author has to DO
          about it, which is a different job and does not belong on a
          control's own surface. */}
      {!published && collection.blocker ? (
        <p className="mt-2.5 text-xs text-muted-foreground">
          {collection.blocker}
        </p>
      ) : published && hidden > 0 ? (
        <p className="mt-2.5 text-xs text-attention">
          <span className="tabular-nums">{hidden}</span> of them are still
          drafts — a learner sees{" "}
          <span className="tabular-nums">{collection.public_item_count}</span>.
        </p>
      ) : null}
    </>
  );
}

/**
 * What the page has written down, in one line.
 *
 * Three states and no fourth: writing it, written and when, or carrying a
 * change it has not written yet. Nothing at all before the first save —
 * "Saved" over a collection nobody has touched this visit is a claim about
 * work that did not happen.
 */
function SaveState({
  saving,
  savedAt,
  dirty,
  className,
}: {
  saving: boolean;
  savedAt: string | null;
  dirty: boolean;
  className?: string;
}) {
  // `timeAgo` is a function of now, so a page left open would keep saying
  // "just now" an hour later. Cheap tick, and only while there is something
  // for it to age.
  const [, tick] = useState(0);
  useEffect(() => {
    if (!savedAt || saving) return;
    const timer = setInterval(() => tick((n) => n + 1), 30_000);
    return () => clearInterval(timer);
  }, [savedAt, saving]);

  const text = saving
    ? "Saving…"
    : dirty
      ? "Unsaved changes"
      : savedAt
        ? `Saved ${timeAgo(savedAt)}`
        : null;

  // Held open whether or not it has anything in it: a line that appears on
  // the first save would move the row it is in the moment somebody typed.
  return <span className={cn("h-4", className)}>{text}</span>;
}

/** The band, before it has a cover. Same height, so nothing on the page
 *  moves when the collection arrives. */
function DetailsSkeleton() {
  return (
    <div
      className="mt-4 h-[9.375rem] rounded-l-[0.25rem] rounded-r-xl bg-card"
      aria-hidden
    />
  );
}

// ── Left pane: what is in the course ──────────────────────────────────────

/**
 * The order IS the content — `next_material_id` is the first unsat one in
 * this sequence, so what an author does here is the one thing a collection
 * claims over a filter.
 *
 * Dragging is the gesture for it, because a sequence is a spatial idea and
 * arrows make it arithmetic. It is not the ONLY gesture: the handle is a
 * button, and the arrow keys move the row it holds. Drag alone is a
 * reorder that cannot be done without a mouse, on the one control on this
 * page where position is the whole point.
 */
function InCollection({
  order,
  byId,
  loading,
  onMove,
  onRemove,
}: {
  order: string[];
  byId: Map<string, PracticeMaterial>;
  loading: boolean;
  onMove: (from: number, to: number) => void;
  onRemove: (materialId: string) => void;
}) {
  const [dragging, setDragging] = useState<number | null>(null);

  return (
    <section>
      <PaneHead
        title="In this collection"
        note={
          order.length === 0
            ? undefined
            : `${order.length} · drag to reorder`
        }
      />

      {loading ? (
        <ul className="space-y-2">
          {[0, 1, 2].map((i) => (
            <li key={i} className="h-14 rounded-lg bg-card/70" aria-hidden />
          ))}
        </ul>
      ) : order.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border px-4 py-10 text-center text-xs leading-relaxed text-muted-foreground">
          Nothing in it yet.
          <br />
          Add materials from the right.
        </p>
      ) : (
        <ol className="space-y-2">
          {order.map((materialId, index) => {
            const material = byId.get(materialId);
            return (
              <li
                key={materialId}
                draggable
                onDragStart={(e) => {
                  setDragging(index);
                  e.dataTransfer.effectAllowed = "move";
                }}
                onDragOver={(e) => {
                  // The reorder happens on hover rather than on drop, so the
                  // list under the cursor is the list being made — a drop
                  // that rearranges afterwards is a guess the author only
                  // gets to check once it is done.
                  e.preventDefault();
                  if (dragging === null || dragging === index) return;
                  onMove(dragging, index);
                  setDragging(index);
                }}
                onDragEnd={() => setDragging(null)}
                className={cn(
                  "group/row flex items-center gap-2.5 rounded-lg bg-card px-3 py-2.5",
                  "transition-[opacity,background-color] duration-fast",
                  dragging === index && "opacity-50",
                )}
              >
                <button
                  type="button"
                  aria-label={`Reorder ${material?.title ?? "material"}, position ${index + 1} of ${order.length}. Use the arrow keys.`}
                  onKeyDown={(e) => {
                    if (e.key === "ArrowUp") {
                      e.preventDefault();
                      onMove(index, index - 1);
                    } else if (e.key === "ArrowDown") {
                      e.preventDefault();
                      onMove(index, index + 1);
                    }
                  }}
                  className="shrink-0 cursor-grab text-muted-foreground/50 transition-colors group-hover/row:text-muted-foreground focus-visible:text-foreground focus-visible:outline-none active:cursor-grabbing"
                >
                  <GripVertical className="size-4" aria-hidden />
                </button>

                <span className="w-4 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                  {index + 1}
                </span>

                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs text-foreground">
                    {material?.title ?? "…"}
                  </p>
                  <p className="mt-0.5 truncate text-[0.6875rem] text-muted-foreground">
                    {material ? metaLine(material) : ""}
                  </p>
                </div>

                <button
                  type="button"
                  onClick={() => onRemove(materialId)}
                  aria-label={`Remove ${material?.title ?? "material"}`}
                  className="shrink-0 rounded p-0.5 text-muted-foreground/50 transition-colors group-hover/row:text-muted-foreground hover:text-destructive focus-visible:text-destructive focus-visible:outline-none"
                >
                  <X className="size-3.5" aria-hidden />
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

/** `Part 1 · Form completion · 6:06` — what tells two papers apart at a
 *  glance, in the order somebody scanning a course reads them. */
function metaLine(m: PracticeMaterial): string {
  return [partLabel(m), describeTask(m)?.label, formatClock(m.duration_ms)]
    .filter(Boolean)
    .join(" · ");
}

function PaneHead({ title, note }: { title: string; note?: string }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <h2 className="text-sm text-foreground">{title}</h2>
      {note && (
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
          {note}
        </span>
      )}
    </div>
  );
}

// ── Right pane: what could go in ──────────────────────────────────────────

/** The part chips. `scope` is the catalogue's own parameter, so these narrow
 *  the QUERY and not the page — the rule the practice list is built on, and
 *  the reason there is no "not added" chip beside them: membership is local
 *  and unsaved, so filtering by it would empty pages the server still counts
 *  as full. A row already in the collection says so on its own button. */
const PARTS: Array<{ value: string; label: string }> = [
  { value: "all", label: "All" },
  { value: "1", label: "Part 1" },
  { value: "2", label: "Part 2" },
  { value: "3", label: "Part 3" },
  { value: "4", label: "Part 4" },
];

/**
 * What could go in: anybody's published material, and the author's own.
 *
 * The catalogue's own query behind it, so the search, the filters and the
 * paging are the ones that already exist rather than a second, worse
 * implementation.
 */
function Picker({
  inCollection,
  onAdd,
}: {
  inCollection: string[];
  onAdd: (m: PracticeMaterial) => void;
}) {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("all");
  const settled = useDebounced(query, 250);

  const params = useMemo(() => {
    // `done=true` because an author choosing what belongs in a course is not
    // shopping for something to practise — their own history has nothing to
    // do with what the course should contain.
    const next: Record<string, string> = { done: "true" };
    if (settled.trim()) next.q = settled.trim();
    if (scope !== "all") next.scope = scope;
    return next;
  }, [settled, scope]);

  const { data, isLoading, hasNextPage, fetchNextPage, isFetchingNextPage } =
    usePracticeCatalogue(params);

  const rows = useMemo(
    () => data?.pages.flatMap((page) => page.items) ?? [],
    [data],
  );
  const total = data?.pages[0]?.total ?? null;
  const chosen = new Set(inCollection);

  return (
    <section>
      <PaneHead
        title="Add materials"
        note={total == null ? undefined : `${total} available`}
      />

      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search by title or author"
        aria-label="Search materials to add"
        className="h-9 w-full rounded-lg border border-transparent bg-card px-3 font-mono text-xs text-foreground placeholder:text-muted-foreground focus-visible:border-border-strong focus-visible:outline-none"
      />

      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {PARTS.map((part) => (
          <button
            key={part.value}
            type="button"
            onClick={() => setScope(part.value)}
            aria-pressed={scope === part.value}
            className={cn(
              "rounded-full px-3 py-1 text-xs transition-colors duration-fast",
              "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
              scope === part.value
                ? "bg-primary/15 text-primary"
                : "bg-card text-muted-foreground hover:text-foreground",
            )}
          >
            {part.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <ul className="mt-3 space-y-4">
          {[0, 1, 2, 3].map((i) => (
            <li key={i} aria-hidden>
              <Skeleton className="h-3.5 w-52 max-w-full" />
              <Skeleton className="mt-2 h-3 w-36" />
            </li>
          ))}
        </ul>
      ) : rows.length === 0 ? (
        <p className="mt-3 rounded-lg border border-dashed border-border px-4 py-10 text-center text-xs text-muted-foreground">
          Nothing matches that.
        </p>
      ) : (
        // Its own scroll, so the library's length is never the page's
        // length: with the two panes side by side, a picker that grew would
        // leave the collection alone at the top of a very tall column.
        // `scrollbar-quiet` is the app's own treatment for a kept native
        // scroll — invisible at rest, there when reached for, and the gutter
        // reserved either way so arriving at it never reflows the rows.
        <div className={cn("scrollbar-quiet mt-1 overflow-y-auto pr-1", PICKER_H)}>
          <ul>
            {rows.map((m) => {
              const already = chosen.has(m.id);
              return (
                <li
                  key={m.id}
                  className="flex items-center gap-2.5 border-b border-border-subtle py-2.5 last:border-b-0"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs text-foreground">{m.title}</p>
                    <p className="mt-0.5 truncate text-[0.6875rem] text-muted-foreground">
                      {[partLabel(m), describeTask(m)?.label, m.author?.display_name]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  </div>
                  <span
                    className={cn(
                      "w-12 shrink-0 rounded-full border py-0.5 text-center text-[0.6875rem]",
                      DIFFICULTY_CLASS[m.difficulty.band],
                    )}
                  >
                    {DIFFICULTY_SHORT[m.difficulty.band]}
                  </span>
                  {/* Already in it stays visible and disabled rather than
                      disappearing. A list that removes what you just clicked
                      makes the next click land on something else. */}
                  <Button
                    variant="ghost"
                    size="xs"
                    className="shrink-0 font-mono"
                    disabled={already}
                    onClick={() => onAdd(m)}
                  >
                    {already ? (
                      "Added"
                    ) : (
                      <>
                        <Plus className="size-3" aria-hidden />
                        Add
                      </>
                    )}
                  </Button>
                </li>
              );
            })}
          </ul>

          {hasNextPage && (
            <Button
              variant="ghost"
              size="sm"
              className="mt-3 w-full font-mono"
              disabled={isFetchingNextPage}
              onClick={() => void fetchNextPage()}
            >
              {isFetchingNextPage ? "Loading…" : "Show more"}
            </Button>
          )}
        </div>
      )}
    </section>
  );
}
