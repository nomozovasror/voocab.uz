import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ChevronDown, ChevronUp, Plus, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useStudioCrumbs } from "@/components/studio/breadcrumbs";
import { useDebounced } from "@/hooks/use-debounced";
import { getErrorMessage } from "@/lib/api";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
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
 * The order is the content. Everything else on this page — the title, the
 * line of summary, the publish control — is small beside the two lists, and
 * the two lists are the whole job: what is in, and what could be.
 *
 * Saving is explicit rather than autosaved, which is the opposite of the
 * material editor and deliberately so. An author reordering a course is
 * moving things about to see how they look, and a save on every move would
 * publish half-finished sequences to anybody reading. So the order is local
 * state until they say otherwise, and the page says when it has drifted from
 * what is stored.
 */
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
    { label: "collections", to: "/studio/collections" },
    { label: collection?.title ?? "…" },
  ]);

  const update = useUpdateCollection();
  const setItems = useSetCollectionItems();
  const remove = useDeleteCollection();

  // --- The order, held locally until saved ---------------------------------
  const [order, setOrder] = useState<string[]>([]);
  const [seeded, setSeeded] = useState(false);
  useEffect(() => {
    // Seeded once. Re-seeding on every fetch would throw away an in-progress
    // reorder the moment anything else invalidated this query.
    if (seeded || !detail.data) return;
    setOrder(detail.data.items.map((m) => m.id));
    setSeeded(true);
  }, [detail.data, seeded]);

  const saved = useMemo(
    () => detail.data?.items.map((m) => m.id) ?? [],
    [detail.data],
  );
  const dirty =
    seeded &&
    (order.length !== saved.length ||
      order.some((mid, i) => mid !== saved[i]));

  // Titles for the ids we hold, from whichever list has them: the collection's
  // own rows for what was already in it, the picker's for what has just been
  // added and not yet saved.
  const [picked, setPicked] = useState<Record<string, PracticeMaterial>>({});
  const byId = useMemo(() => {
    const map = new Map<string, PracticeMaterial>();
    for (const m of detail.data?.items ?? []) map.set(m.id, m);
    for (const m of Object.values(picked)) map.set(m.id, m);
    return map;
  }, [detail.data, picked]);

  const move = (from: number, to: number) => {
    if (to < 0 || to >= order.length) return;
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

  const save = () => {
    if (!id) return;
    setItems.mutate(
      { id, materialIds: order },
      {
        onSuccess: (result) => {
          void detail.refetch();
          // Publishing can be withdrawn by a save that empties a collection.
          // Said out loud, because a flag that changed itself and stayed
          // quiet is a flag the author finds out about from a learner.
          if (result.visibility === "private" && collection?.visibility === "public") {
            toast("Withdrawn: a published collection can't be empty.", "warning");
          } else {
            toast("Order saved", "success");
          }
        },
        onError: (err) => toast(getErrorMessage(err)),
      },
    );
  };

  if (detail.isError) {
    return (
      <div className="mx-auto w-full max-w-3xl py-8">
        <p className="text-sm text-muted-foreground">
          {getErrorMessage(detail.error) || "Couldn't load this collection."}
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-3xl py-8">
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
          onSave={(fields) =>
            update.mutate(
              { id: collection.id, ...fields },
              { onError: (err) => toast(getErrorMessage(err)) },
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
        <div className="mt-4">
          <Skeleton className="inline-block h-[0.8em] w-64 max-w-full" />
        </div>
      )}

      {/* --- In the collection ------------------------------------------- */}
      <section className="mt-8">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-sm text-foreground">
            In this collection
            <span className="ml-2 text-xs text-muted-foreground tabular-nums">
              {order.length}
            </span>
          </h2>
          <Button size="sm" onClick={save} disabled={!dirty || setItems.isPending}>
            {dirty ? "Save order" : "Saved"}
          </Button>
        </div>

        {detail.isLoading ? (
          <ul className="mt-3">
            {[0, 1, 2].map((i) => (
              <li key={i} className="border-b border-border-subtle py-3 last:border-b-0">
                <Skeleton className="inline-block h-[0.8em] w-56 max-w-full" />
              </li>
            ))}
          </ul>
        ) : order.length === 0 ? (
          <p className="mt-3 rounded-xl border border-dashed border-border px-5 py-10 text-center text-sm text-muted-foreground">
            Nothing in it yet. Add materials from below.
          </p>
        ) : (
          <ol className="mt-3">
            {order.map((materialId, index) => (
              <li
                key={materialId}
                className="flex items-center gap-3 border-b border-border-subtle py-2.5 last:border-b-0"
              >
                <span className="w-6 shrink-0 text-right text-sm tabular-nums text-muted-foreground">
                  {index + 1}.
                </span>
                <span className="min-w-0 flex-1 truncate text-sm text-foreground">
                  {byId.get(materialId)?.title ?? "…"}
                </span>
                {/* Buttons rather than drag and drop. Drag is nicer with a
                    mouse and unusable without one, and this list is the one
                    place on the page where the exact position matters. */}
                <div className="flex shrink-0 items-center gap-0.5">
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label="Move up"
                    disabled={index === 0}
                    onClick={() => move(index, index - 1)}
                  >
                    <ChevronUp className="size-3.5" aria-hidden />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label="Move down"
                    disabled={index === order.length - 1}
                    onClick={() => move(index, index + 1)}
                  >
                    <ChevronDown className="size-3.5" aria-hidden />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label="Remove from collection"
                    onClick={() =>
                      setOrder((prev) => prev.filter((x) => x !== materialId))
                    }
                  >
                    <X className="size-3.5" aria-hidden />
                  </Button>
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>

      <Picker inCollection={order} onAdd={add} />
    </div>
  );
}

/** Title, summary, and the publish control.
 *
 *  Saved on blur rather than on every keystroke: these are two short fields
 *  somebody edits once, and a request per character to keep them in step with
 *  a name being typed is a lot of noise for no benefit. */
function Details({
  collection,
  onSave,
  onDelete,
  busy,
}: {
  collection: AuthorCollection;
  onSave: (fields: { title?: string; summary?: string; visibility?: string }) => void;
  onDelete: () => void;
  busy: boolean;
}) {
  const [title, setTitle] = useState(collection.title);
  const [summary, setSummary] = useState(collection.summary);
  const published = collection.visibility === "public";

  return (
    <header className="mt-4">
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        onBlur={() =>
          title.trim() && title !== collection.title
            ? onSave({ title: title.trim() })
            : setTitle(collection.title)
        }
        aria-label="Collection title"
        maxLength={200}
        className="w-full rounded-lg bg-transparent text-2xl font-semibold text-foreground focus-visible:outline-none"
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
        className="mt-1 w-full rounded-lg bg-transparent text-sm text-muted-foreground placeholder:text-muted-foreground/60 focus-visible:outline-none"
      />

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button
          variant={published ? "outline" : "default"}
          size="sm"
          disabled={busy || (!published && !!collection.blocker)}
          onClick={() =>
            onSave({ visibility: published ? "private" : "public" })
          }
        >
          {published ? "Withdraw" : "Publish"}
        </Button>
        {/* Why it can't go out, where the button that can't be pressed is. */}
        {!published && collection.blocker && (
          <p className="text-xs text-muted-foreground">{collection.blocker}</p>
        )}
        {published && (
          <Link
            to={`/listening/collections/${collection.id}`}
            className="text-xs text-primary transition-colors hover:underline"
          >
            See it as a learner does
          </Link>
        )}
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto text-muted-foreground hover:text-destructive"
          disabled={busy}
          onClick={onDelete}
        >
          <Trash2 className="size-3.5" aria-hidden />
          Delete
        </Button>
      </div>
    </header>
  );
}

/**
 * What could go in: anybody's published material, and the author's own.
 *
 * The catalogue's own query behind it, so the search, the filters and the
 * paging are the ones that already exist rather than a second, worse
 * implementation. `done=true` because an author choosing what belongs in a
 * course is not shopping for something to practise — their own history has
 * nothing to do with it.
 */
function Picker({
  inCollection,
  onAdd,
}: {
  inCollection: string[];
  onAdd: (m: PracticeMaterial) => void;
}) {
  const [query, setQuery] = useState("");
  const settled = useDebounced(query, 250);
  const params = useMemo(() => {
    // `done=true` because an author choosing what belongs in a course is not
    // shopping for something to practise — their own history has nothing to
    // do with what the course should contain.
    const next: Record<string, string> = { done: "true" };
    if (settled.trim()) next.q = settled.trim();
    return next;
  }, [settled]);
  const { data, isLoading, hasNextPage, fetchNextPage, isFetchingNextPage } =
    usePracticeCatalogue(params);

  const rows = useMemo(
    () => data?.pages.flatMap((page) => page.items) ?? [],
    [data],
  );
  const chosen = new Set(inCollection);

  return (
    <section className="mt-10">
      <h2 className="text-sm text-foreground">Add materials</h2>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search by title or author"
        aria-label="Search materials to add"
        className="mt-3 h-9 w-full rounded-lg border border-border bg-card px-3 text-sm text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
      />

      {isLoading ? (
        <ul className="mt-3">
          {[0, 1, 2].map((i) => (
            <li key={i} className="border-b border-border-subtle py-3 last:border-b-0">
              <Skeleton className="inline-block h-[0.8em] w-56 max-w-full" />
            </li>
          ))}
        </ul>
      ) : rows.length === 0 ? (
        <p className="mt-3 rounded-xl border border-dashed border-border px-5 py-10 text-center text-sm text-muted-foreground">
          Nothing matches that.
        </p>
      ) : (
        <>
          <ul className="mt-3">
            {rows.map((m) => {
              const already = chosen.has(m.id);
              const task = describeTask(m);
              const part = partLabel(m);
              return (
                <li
                  key={m.id}
                  className="flex items-center gap-3 border-b border-border-subtle py-2.5 last:border-b-0"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-foreground">{m.title}</p>
                    <p className="mt-0.5 truncate text-xs text-muted-foreground">
                      {[part, task?.label, m.author?.display_name]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  </div>
                  <span
                    className={cn(
                      "w-14 shrink-0 rounded-full border py-0.5 text-center text-xs font-medium",
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
              variant="outline"
              size="sm"
              className="mt-4"
              disabled={isFetchingNextPage}
              onClick={() => void fetchNextPage()}
            >
              Show more
            </Button>
          )}
        </>
      )}
    </section>
  );
}
