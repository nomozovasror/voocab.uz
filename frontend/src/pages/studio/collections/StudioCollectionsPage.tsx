import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useStudioCrumbs } from "@/components/studio/breadcrumbs";
import { NewCollectionDialog } from "@/components/studio/NewCollectionDialog";
import { getErrorMessage } from "@/lib/api";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { StudioCollectionCover } from "@/components/studio/StudioCollectionCover";
import { coverKeyOf } from "@/features/listening/cover";
import {
  useCreateCollection,
  useMyCollections,
} from "@/features/listening/queries";
import type { AuthorCollection } from "@/features/listening/types";

/**
 * The author's collections — the second half of the listening studio, under
 * the same header and the same tabs as the materials it is built out of.
 *
 * A collection is a list of references, not a container: nothing here owns a
 * material, so nothing here can lose one. That is what makes this page as
 * light as it is — no drafts to reconcile, no publishing pipeline, no
 * autosave. A title, an order, and a cover it never had to be given.
 *
 * **It is a shelf, not a list.** The cover is derived from the id
 * (`cover.ts`), so the same collection is the same book forever — which is
 * the whole reason a shelf beats a column of titles: the author finds the
 * course they were building by recognising it, from across the page, before
 * they have read a word. The learner already sees these as books, and an
 * author who lays out a course as rows and then meets it as a shelf has to
 * learn the same shelf twice.
 */
export default function StudioCollectionsPage() {
  useStudioCrumbs([
    { label: "listening", to: "/studio/listening" },
    { label: "collections" },
  ]);
  const { data, isLoading, isError, error, refetch } = useMyCollections();
  const create = useCreateCollection();
  const navigate = useNavigate();
  const [naming, setNaming] = useState(false);

  const createCollection = (title: string) =>
    create.mutate(
      { title },
      {
        onSuccess: (collection) => {
          setNaming(false);
          navigate(`/studio/collections/${collection.id}`);
        },
        // The dialog stays open on failure, keeping what was typed: it is
        // where the button that failed is, and closing it would leave the
        // author guessing whether anything happened.
        onError: (err) =>
          toast({
            title: "not created",
            message: getErrorMessage(err),
            kind: "error",
          }),
      },
    );

  const total = data?.length ?? 0;

  // The panel, and only the panel: the header above it belongs to the layout
  // route and stays put across the navigation, so the entrance animation
  // here can never drag the tab bar's sliding pill along with it.
  return (
    <>
      <div className="studio-panel">
        {isError ? (
          <div className="rounded-lg border border-dashed border-border px-5 py-10 text-center">
            <p className="text-sm text-muted-foreground">
              {getErrorMessage(error) || "couldn't load your collections."}
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
        ) : (
          <>
            {/* Four across a 900px column, not five. The cover's foot has to
                hold a count and a plate side by side on one line, and at five
                the line is wider than the book — which is what put "2
                materials" on two rows and threw the plate out of line with
                it. A column width here is a constraint on the type. */}
            <div className="grid grid-cols-2 gap-x-5 gap-y-6 sm:grid-cols-3 lg:grid-cols-4">
              {/* First on the shelf, always — the gap where the next book goes
                  is where an author's eye already is, and a create control
                  pushed below a shelf that grows is a control that walks off
                  the page. */}
              <NewBook onClick={() => setNaming(true)} />
              {isLoading
                ? Array.from({ length: 3 }, (_, i) => <BookSkeleton key={i} />)
                : data?.map((collection) => (
                    <StudioBook key={collection.id} collection={collection} />
                  ))}
            </div>

            {!isLoading && total === 0 && (
              <p className="mt-8 text-center text-xs text-muted-foreground">
                nothing yet — name one and start putting materials in it.
              </p>
            )}
          </>
        )}
      </div>

      <NewCollectionDialog
        open={naming}
        onOpenChange={setNaming}
        onCreate={createCollection}
        creating={create.isPending}
      />
    </>
  );
}

/**
 * One collection, as a book — and nothing under it.
 *
 * Everything the author needs is printed ON the cover, which is what makes
 * the shelf a shelf: every card is exactly one portrait rectangle, so the
 * rows are level without anything having to be measured or clamped. A strip
 * of meta underneath had the opposite effect — a title repeated from the
 * cover, a count that wrapped to two lines in a narrow column, and a
 * publishing warning that made one card taller than its neighbours and put a
 * kink in the row.
 *
 * So the cover carries the title at the top and one line across the foot:
 * how much is in it on the left, whether it is out on the right. Anything
 * that is an INSTRUCTION rather than a fact — what is blocking publication —
 * belongs where the fixing happens, which is the collection's own page.
 */
function StudioBook({ collection }: { collection: AuthorCollection }) {
  return (
    <Link
      to={`/studio/collections/${collection.id}`}
      className="group/book block rounded-md focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      <StudioCollectionCover
        coverKey={coverKeyOf(collection)}
        title={collection.title}
        count={collection.item_count}
        published={collection.visibility === "public"}
        className={cn(
          "transition-[translate,box-shadow] duration-base ease-out motion-reduce:transition-none",
          "group-hover/book:-translate-y-1 group-hover/book:shadow-[0_12px_22px_rgba(0,0,0,0.4)]",
          "group-focus-visible/book:-translate-y-1",
        )}
      />
    </Link>
  );
}

/**
 * The next book, before it exists.
 *
 * A shape on the shelf rather than a control beside it: the gap where the
 * next book goes is where the author's eye already is, and a create button
 * above a shelf that grows is a button that walks off the page. It keeps the
 * shelf's ratio so the row it is in is the height it will be once the book
 * is real.
 *
 * The naming is asked for in a dialog (`NewCollectionDialog`) rather than in
 * the tile: a field in a 165px column is a field the title does not fit in,
 * and the tile would have to stop being a book to hold one.
 */
function NewBook({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex aspect-[156/214] w-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border",
        "text-xs text-muted-foreground transition-colors duration-fast",
        "hover:border-primary hover:text-foreground focus-visible:border-primary focus-visible:text-foreground focus-visible:outline-none",
      )}
    >
      <span aria-hidden className="text-2xl leading-none text-primary">
        +
      </span>
      new collection
    </button>
  );
}

/** A book, waiting. One rectangle, because a loaded book is one rectangle —
 *  nothing shifts when the shelf arrives. */
function BookSkeleton() {
  return (
    <div
      aria-hidden
      className="aspect-[156/214] w-full rounded-l-sm rounded-r-md bg-foreground/10"
    />
  );
}
