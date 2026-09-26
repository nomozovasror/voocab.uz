import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import { Skeleton, SkeletonBlock } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { toast } from "@/lib/toast";
import { getErrorMessage } from "@/lib/api";
import { vocabularyApi } from "@/features/vocabulary/api";
import { AUTOMATIC_LABEL, EXERCISE_LABEL } from "@/features/vocabulary/status";
import type { ExerciseType, VocabularySettings } from "@/features/vocabulary/types";

const MINUTES_OPTIONS: VocabularySettings["daily_minutes"][] = [5, 10, 15, 20];
const EXERCISE_TYPES: ExerciseType[] = ["recognise", "recall", "produce"];

/**
 * `/vocabulary/settings` — the plan's screen 6, and the whole reason this
 * page's three fields ARE three fields rather than one form.
 *
 * Each writes through `vocabularyApi.updateSettings` on its own, patched
 * into the cache from the server's own response rather than assumed —
 * `direction` and `exercise_types` interact server-side in ways this page
 * does not have to model (a `both` toggle changing what `exercise_types`
 * defaults to, say), so the source of truth after every write is what the
 * server sends back, not what was clicked.
 *
 * No pronunciation control, per the spec — the field still travels on the
 * wire (`VocabularySettings.pronunciation`) because stage 3 will want the
 * row it already occupies, but nothing here reads or writes it.
 *
 * `PUT /vocabulary/settings` takes `daily_minutes` and `direction` as
 * REQUIRED fields, a plain replace saved together per the server's own
 * docstring, so every control below sends the full triple rather than a
 * lone field the server has no default for.
 */
export default function VocabularySettingsPage() {
  const qc = useQueryClient();
  const { data, isPending, isError } = useQuery({
    queryKey: ["vocabulary", "settings"],
    queryFn: () => vocabularyApi.settings(),
  });

  const update = useMutation({
    mutationFn: (settings: Parameters<typeof vocabularyApi.updateSettings>[0]) =>
      vocabularyApi.updateSettings(settings),
    onSuccess: (settings) => {
      qc.setQueryData(["vocabulary", "settings"], settings);
      // Every number this settings row feeds — the home screen's due count,
      // the mode picker's preview — is stale the moment any of these three
      // change, so the whole `summary` family goes rather than one `tz`.
      void qc.invalidateQueries({ queryKey: ["vocabulary", "practice", "summary"] });
    },
    onError: (e) => toast(getErrorMessage(e)),
  });

  // Every control below calls this rather than `update.mutate` directly —
  // one place that merges a single change into the full triple the server
  // requires, so no button here has to remember the other two fields.
  function patch(
    change: Partial<Parameters<typeof vocabularyApi.updateSettings>[0]>,
  ) {
    if (!data) return;
    update.mutate({
      daily_minutes: data.daily_minutes,
      direction: data.direction,
      exercise_types: data.exercise_types,
      ...change,
    });
  }

  if (isPending) return <SettingsSkeleton />;

  if (isError || !data) {
    return (
      <div className="mx-auto w-full max-w-xl py-16">
        <h1 className="text-2xl font-semibold text-foreground">Settings</h1>
        <p className="mt-2 text-sm text-destructive">
          Your settings couldn&apos;t be loaded.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-xl pb-24 pt-2">
      <header className="pb-6">
        <Link
          to="/vocabulary"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <ChevronLeft className="size-3.5" aria-hidden />
          Vocabulary
        </Link>
        <h1 className="mt-2 text-2xl font-semibold text-foreground">Settings</h1>
      </header>

      <section className="rounded-xl border border-border px-4 py-3">
        <p className="text-sm text-foreground">Daily practice</p>
        <p className="text-xs text-muted-foreground">
          How much time this buys in new words each day.
        </p>
        <div
          role="radiogroup"
          aria-label="Daily practice time, in minutes"
          className="mt-3 flex gap-1 rounded-full border border-border bg-surface-sunken p-1"
        >
          {MINUTES_OPTIONS.map((minutes) => {
            const on = data.daily_minutes === minutes;
            return (
              <button
                key={minutes}
                type="button"
                role="radio"
                aria-checked={on}
                disabled={update.isPending}
                onClick={() => patch({ daily_minutes: minutes })}
                className={cn(
                  "flex-1 rounded-full px-2.5 py-1 text-xs font-medium tabular-nums transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50",
                  on
                    ? "bg-primary/20 text-primary"
                    : "text-muted-foreground hover:bg-surface-hover hover:text-foreground",
                )}
              >
                {minutes}
              </button>
            );
          })}
        </div>
      </section>

      <section className="mt-4 rounded-xl border border-border px-4 py-3">
        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            checked={data.direction === "both"}
            disabled={update.isPending}
            onChange={(e) =>
              patch({ direction: e.target.checked ? "both" : "passive" })
            }
            className="mt-0.5 size-4 shrink-0 rounded border-border bg-surface-sunken accent-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          />
          {/* The spec's exact wording — not paraphrased, because "active
           *  practice" and "producing words" read as two different features
           *  to somebody deciding whether to turn either on. */}
          <span className="text-sm text-foreground">
            Also practise producing words — harder, for writing and speaking.
          </span>
        </label>
        {data.direction === "both" && data.active_in_progress > 0 && (
          // Turning the toggle off pauses these words rather than resetting
          // them — server-side, with no extra confirm here — but nothing
          // else on this row would tell a learner there is anything TO
          // pause before they press it.
          <p className="mt-2 pl-7 text-xs text-muted-foreground">
            {data.active_in_progress}{" "}
            {data.active_in_progress === 1 ? "word is" : "words are"} being
            practised actively — they&apos;ll pause, not reset.
          </p>
        )}
      </section>

      <section className="mt-4 rounded-xl border border-border px-4 py-3">
        <p className="text-sm text-foreground">Exercise type</p>
        <p className="text-xs text-muted-foreground">
          Automatic lets the ladder pick. Choosing one limits every session
          to just that task, taken only from words already at that rung —
          never skipping ahead — until changed back.
        </p>
        <div
          role="radiogroup"
          aria-label="Exercise type"
          className="mt-3 flex flex-wrap gap-1.5"
        >
          <ExercisePill
            on={data.exercise_types === null}
            disabled={update.isPending}
            onClick={() => patch({ exercise_types: null })}
          >
            {AUTOMATIC_LABEL}
          </ExercisePill>
          {EXERCISE_TYPES.map((type) => (
            <ExercisePill
              key={type}
              on={data.exercise_types?.[0] === type}
              disabled={update.isPending}
              onClick={() => patch({ exercise_types: [type] })}
            >
              {EXERCISE_LABEL[type]}
            </ExercisePill>
          ))}
        </div>
      </section>
    </div>
  );
}

function ExercisePill({
  on,
  disabled,
  onClick,
  children,
}: {
  on: boolean;
  disabled: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={on}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "rounded-full px-3 py-1 text-xs font-medium transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50",
        on
          ? "bg-primary/20 text-primary"
          : "bg-surface-hover text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function SettingsSkeleton() {
  return (
    <SkeletonBlock
      label="Loading your settings"
      className="mx-auto w-full max-w-xl pb-24 pt-2"
    >
      <header className="pb-6">
        <p className="text-xs">
          <Skeleton className="inline-block h-[0.8em] w-20" />
        </p>
        <h1 className="mt-2 text-2xl font-semibold">
          <Skeleton className="inline-block h-[0.8em] w-28" />
        </h1>
      </header>
      {[0, 1, 2].map((i) => (
        <div key={i} className="mt-4 h-16 rounded-xl border border-border first:mt-0" />
      ))}
    </SkeletonBlock>
  );
}
