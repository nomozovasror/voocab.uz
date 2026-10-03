import { useQuery } from "@tanstack/react-query";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { vocabularyApi, wordListsKey } from "@/features/vocabulary/api";
import { BackLink } from "@/features/vocabulary/components/WordListControls";
import {
  WordListCards,
  WordListCardsSkeleton,
} from "@/features/vocabulary/components/WordListCards";

/**
 * Every Word list, with why each is worth learning. Starting a list
 * subscribes to it; it adds no words to "Your words" until the learner
 * answers one — see `features/vocabulary/CLAUDE.md`.
 */
export default function VocabularyListsPage() {
  const { data, isPending, isError } = useQuery({
    queryKey: wordListsKey,
    queryFn: () => vocabularyApi.lists(),
  });

  if (isPending) return <ListsSkeleton />;

  return (
    <div className="mx-auto w-full max-w-xl pb-24 pt-2">
      <BackLink />
      <header className="mt-2 pb-6">
        <h1 className="text-2xl font-semibold text-foreground">Word lists</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Ready-made lists of the words that matter most in a field. Start one
          and its words join your daily practice, most useful first.
        </p>
      </header>
      {isError || !data ? (
        <p className="text-sm text-destructive">
          The word lists couldn&apos;t be loaded.
        </p>
      ) : (
        <WordListCards lists={data} describe />
      )}
    </div>
  );
}

function ListsSkeleton() {
  return (
    <SkeletonBlock
      label="Loading word lists"
      className="mx-auto w-full max-w-xl pb-24 pt-2"
    >
      <span className="inline-flex items-center gap-1 text-xs">
        <Skeleton className="inline-block h-[0.8em] w-20" />
      </span>
      <header className="mt-2 pb-6">
        <h1 className="text-2xl font-semibold">
          <Skeleton className="inline-block h-[0.8em] w-32" />
        </h1>
        <p className="mt-1 text-sm">
          <Skeleton className="inline-block h-[0.8em] w-80 max-w-full" />
        </p>
      </header>
      <WordListCardsSkeleton rows={5} />
    </SkeletonBlock>
  );
}
