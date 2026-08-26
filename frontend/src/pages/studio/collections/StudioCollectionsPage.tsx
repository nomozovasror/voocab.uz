import { useState } from "react";
import { Link } from "react-router-dom";
import { Library, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useStudioCrumbs } from "@/components/studio/breadcrumbs";
import { getErrorMessage } from "@/lib/api";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import {
  useCreateCollection,
  useMyCollections,
} from "@/features/listening/queries";
import type { AuthorCollection } from "@/features/listening/types";

/**
 * The author's collections.
 *
 * A collection is a list of references, not a container: nothing here owns a
 * material, so nothing here can lose one. That is what makes this page as
 * light as it is — no drafts to reconcile, no publishing pipeline, no
 * autosave. A title, a line, and an order.
 *
 * Creating one takes a title and nothing else. An author starts by naming the
 * thing they are about to build, and a create form that demanded its contents
 * up front is a form nobody can fill in.
 */
export default function StudioCollectionsPage() {
  useStudioCrumbs([{ label: "collections" }]);
  const { data, isLoading, isError, error, refetch } = useMyCollections();
  const create = useCreateCollection();
  const [title, setTitle] = useState("");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const name = title.trim();
    if (!name) return;
    create.mutate(
      { title: name },
      {
        onSuccess: () => setTitle(""),
        onError: (err) => toast(getErrorMessage(err)),
      },
    );
  };

  return (
    <div className="mx-auto w-full max-w-3xl py-8">
      <h1 className="flex items-center gap-2 text-2xl font-semibold text-foreground">
        <Library className="size-5 text-muted-foreground" aria-hidden />
        Collections
      </h1>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
        An order to work through. The catalogue says what exists; a collection
        says what to do first, and what after that.
      </p>

      <form onSubmit={submit} className="mt-6 flex gap-2">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Name a new collection"
          aria-label="New collection title"
          maxLength={200}
          className="h-9 min-w-0 flex-1 rounded-lg border border-border bg-card px-3 text-sm text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
        />
        <Button type="submit" disabled={!title.trim() || create.isPending}>
          <Plus className="size-4" aria-hidden />
          Create
        </Button>
      </form>

      {isError ? (
        <div className="mt-8 rounded-xl border border-dashed border-border px-5 py-12 text-center">
          <p className="text-sm text-muted-foreground">
            {getErrorMessage(error) || "Couldn't load your collections."}
          </p>
          <Button
            variant="outline"
            size="sm"
            className="mt-4"
            onClick={() => void refetch()}
          >
            Try again
          </Button>
        </div>
      ) : isLoading ? (
        <ul className="mt-6">
          {[0, 1, 2].map((i) => (
            <li key={i} className="border-b border-border-subtle py-4 last:border-b-0">
              <Skeleton className="inline-block h-[0.8em] w-56 max-w-full" />
              <p className="mt-1.5 text-xs">
                <Skeleton className="inline-block h-[0.8em] w-40" />
              </p>
            </li>
          ))}
        </ul>
      ) : data && data.length > 0 ? (
        <ul className="mt-6">
          {data.map((collection) => (
            <li
              key={collection.id}
              className="border-b border-border-subtle last:border-b-0"
            >
              <Row collection={collection} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-8 rounded-xl border border-dashed border-border px-5 py-12 text-center text-sm text-muted-foreground">
          Nothing yet. Name one above and start putting materials in it.
        </p>
      )}
    </div>
  );
}

function Row({ collection }: { collection: AuthorCollection }) {
  const published = collection.visibility === "public";
  const hidden = collection.item_count - collection.public_item_count;

  return (
    <Link
      to={`/studio/collections/${collection.id}`}
      className="flex items-start gap-4 rounded-lg px-3 py-4 transition-colors duration-fast hover:bg-surface-hover focus-visible:bg-surface-hover focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      <div className="min-w-0 flex-1">
        <p className="truncate text-base text-foreground">{collection.title}</p>
        <p className="mt-1 text-xs text-muted-foreground">
          <span className="tabular-nums">{collection.item_count}</span> material
          {collection.item_count === 1 ? "" : "s"}
          {/* The gap between what they put in and what a learner can see,
              said out loud. It is a normal state to be in halfway through
              building a course and a confusing one to discover afterwards,
              when somebody asks why it looks short. */}
          {hidden > 0 && (
            <>
              {" · "}
              <span className="text-attention">
                <span className="tabular-nums">{hidden}</span> still a draft
              </span>
            </>
          )}
          {/* Why it cannot go out yet, in the author's words rather than as a
              disabled button they have to hover to understand. */}
          {!published && collection.blocker && (
            <>
              {" · "}
              {collection.blocker}
            </>
          )}
        </p>
      </div>
      <span
        className={cn(
          "shrink-0 rounded-full border px-2.5 py-0.5 text-xs font-medium",
          published
            ? "border-published/40 bg-published/10 text-published"
            : "border-border-subtle text-muted-foreground",
        )}
      >
        {published ? "Published" : "Draft"}
      </span>
    </Link>
  );
}
