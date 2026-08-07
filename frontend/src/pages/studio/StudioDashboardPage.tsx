import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  PanelRightClose,
  PanelRightOpen,
  X,
  Headphones,
  Keyboard,
  BookOpen,
  PenLine,
  Sparkles,
  Target,
  Trophy,
  Lock,
  Pencil,
  FilePlus,
  ArrowUpRight,
  Share2,
  Settings2,
  ArrowRight,
  type LucideIcon,
} from "lucide-react";
import { MagicBento } from "@/components/ui/magic-bento";
import { PageLoader } from "@/components/ui/spinner";
import { UserAvatar } from "@/auth/UserAvatar";
import { useCurrentUser } from "@/auth/useCurrentUser";
import { useMediaQuery } from "@/hooks/use-media-query";
import { cn } from "@/lib/utils";
import { getErrorMessage } from "@/lib/api";
import { timeAgo } from "@/lib/time";
import { useStudioStats } from "@/features/studio/queries";
import type { StudioRecentItem, StudioTypeStat } from "@/features/studio/types";

// ── Card surfaces ────────────────────────────────────────────────────────
// "glass" = translucent card + blur + hairline, per the approved mockup;
// "deep" = a denser/more opaque variant for the activity panel. Both built
// only from existing token classes (bg-card, border-foreground/10) — no
// hardcoded colors.
// `magic-card` opts each surface into the cursor glow (see globals.css +
// components/ui/magic-bento.tsx).
const glass =
  "magic-card relative flex flex-col rounded-xl border border-foreground/10 bg-card/60 shadow-lg backdrop-blur-md backdrop-saturate-150";
const deep =
  "magic-card relative flex flex-col rounded-xl border border-foreground/10 bg-card/90 shadow-lg backdrop-blur-md backdrop-saturate-150";

const DASH = "—"; // em dash — the "no data source yet" marker (never 0, never invented)

// Whether the "Recent work" column is shown. Persisted so the choice survives
// reloads — a panel that silently reappears every visit is worse than none.
const RECENT_KEY = "studio:recent-work";

function formatContentHours(ms: number): string {
  const hours = ms / 3_600_000;
  if (hours < 0.05) return "0h";
  return `${hours.toFixed(1)}h`;
}

function itemCountLabel(type: string): string {
  if (type === "listening") return "gaps";
  if (type === "dictation") return "segments";
  return "items";
}

function editorHref(item: { id: string; type: string }): string {
  return item.type === "listening"
    ? `/studio/materials/${item.id}/edit`
    : `/materials/${item.id}/edit`;
}

// ── Small building blocks ────────────────────────────────────────────────

function Stat({ value, label }: { value: string; label: string }) {
  const dashed = value === DASH;
  return (
    <div className="text-center">
      <div
        className={cn(
          "text-stat tabular-nums",
          dashed ? "text-muted-foreground" : "text-foreground",
        )}
      >
        {value}
      </div>
      <div className="mt-0.5 text-micro text-muted-foreground">{label}</div>
    </div>
  );
}

function SoonChip() {
  return (
    <span className="rounded-full bg-foreground/8 px-1.5 py-0.5 text-micro font-bold tracking-wider text-muted-foreground uppercase">
      Soon
    </span>
  );
}

interface TileProps {
  gridArea: string;
  icon: LucideIcon;
  title: string;
  description: string;
  stats: { value: string; label: string }[];
  available: boolean;
  isTool?: boolean;
  href: string;
  ctaLabel: string;
}

function TypeTile({
  gridArea,
  icon: Icon,
  title,
  description,
  stats,
  available,
  isTool,
  href,
  ctaLabel,
}: TileProps) {
  const inner = (
    <>
      <Icon
        aria-hidden
        className={cn(
          "pointer-events-none absolute top-1/2 -right-11 -translate-y-1/2 stroke-[1.2] text-foreground opacity-[0.08] transition-all duration-300 ease-out",
          available && "group-hover:-translate-x-1 group-hover:text-primary group-hover:opacity-20",
        )}
        style={{ width: "11.5rem", height: "11.5rem" }}
      />
      <div className="relative z-10 flex items-center justify-between gap-2">
        <h3 className="text-tile text-foreground">{title}</h3>
        {!available && <SoonChip />}
      </div>
      <p className="relative z-10 line-clamp-1 flex-1 text-label text-muted-foreground">
        {description}
      </p>
      <div className="relative z-10 grid grid-cols-3 gap-1.5">
        {stats.map((s) => (
          <Stat key={s.label} value={s.value} label={s.label} />
        ))}
      </div>
      {/* Bordered, full-width and centred so every tile ends on the same
          affordance. Neutral at rest — colour arrives on hover, matching the
          watermark, so a grid of six tiles stays calm. */}
      <span
        className={cn(
          // Negative margins pull the button's border to within ~6px of the
          // card's own border on all three sides, so it reads as a footer
          // action rather than a control floating in the middle.
          "relative z-10 -mx-2 -mb-2 flex items-center justify-center gap-1 rounded-md border px-3 py-1.5 text-micro font-semibold transition-all duration-200 ease-out",
          // Lighter than the card's own border (foreground/10) so the card
          // edge stays the dominant line and the button reads as secondary.
          available
            ? "border-foreground/6 text-muted-foreground group-hover:border-primary/50 group-hover:bg-primary/10 group-hover:text-primary"
            : "border-foreground/5 text-muted-foreground",
        )}
      >
        {ctaLabel}
        {available && <ArrowRight className="size-3.5" />}
      </span>
    </>
  );

  const className = cn(
    glass,
    "group min-h-0 gap-2 overflow-hidden p-3.5",
    isTool && "border-dashed border-foreground/15",
    "transition-all duration-200 ease-out",
    available
      ? "cursor-pointer hover:-translate-y-0.5 hover:border-primary/45"
      : "cursor-default opacity-50",
  );

  if (!available) {
    return (
      <div style={{ gridArea }} className={className} aria-disabled="true">
        {inner}
      </div>
    );
  }

  return (
    <Link to={href} style={{ gridArea }} className={className}>
      {inner}
    </Link>
  );
}

const ACHIEVEMENTS = [
  "First material",
  "10 learners",
  "100 completions",
  "First follower",
  "5 published",
  "1h content",
  "Weekly streak",
  "Top author",
  "50 saves",
];

function ActivityRow({ item }: { item: StudioRecentItem }) {
  const edited = item.updated_at > item.created_at;
  const EventIcon = edited ? Pencil : FilePlus;
  const tint =
    item.type === "listening"
      ? "bg-primary/14 text-primary"
      : item.type === "dictation"
        ? "bg-success/14 text-success"
        : "bg-foreground/8 text-muted-foreground";

  return (
    <Link
      to={editorHref(item)}
      className="group grid grid-cols-[auto_1fr] items-start gap-2.5 border-t border-foreground/7 py-2 first:border-t-0"
    >
      <span
        className={cn(
          "flex size-7.5 shrink-0 items-center justify-center rounded-lg",
          tint,
        )}
        aria-hidden
      >
        <EventIcon className="size-3.5" />
      </span>
      <div className="min-w-0">
        <div className="truncate text-body text-foreground group-hover:text-primary">
          {edited ? "Edited " : "Created "}
          <b className="font-semibold">{item.title}</b>
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-micro tabular-nums text-muted-foreground">
          <span className="capitalize">{item.type}</span>
          <span>·</span>
          <span>
            {item.item_count} {itemCountLabel(item.type)}
          </span>
          <span>·</span>
          <span>{timeAgo(item.updated_at)}</span>
          <span
            className={cn(
              "font-bold tracking-wide uppercase",
              item.visibility === "public" ? "text-success" : "text-muted-foreground",
            )}
          >
            {item.visibility === "public" ? "Public" : "Private"}
          </span>
        </div>
      </div>
    </Link>
  );
}

export default function StudioDashboardPage() {
  const { user } = useCurrentUser();
  const { data: stats, isLoading, isError, error } = useStudioStats();
  const isNarrow = useMediaQuery("(max-width: 1180px)");
  const [showRecent, setShowRecent] = useState(
    () => localStorage.getItem(RECENT_KEY) !== "off",
  );

  useEffect(() => {
    localStorage.setItem(RECENT_KEY, showRecent ? "on" : "off");
  }, [showRecent]);

  if (isLoading) return <PageLoader />;
  if (isError || !stats) {
    return (
      <p className="text-sm text-destructive">
        {getErrorMessage(error) || "Couldn't load your Studio stats."}
      </p>
    );
  }

  const isEmpty = stats.materials_total === 0;
  const byType = (type: string): StudioTypeStat | undefined =>
    stats.by_type.find((t) => t.type === type);

  const listening = byType("listening");
  const dictation = byType("dictation");

  // Hiding "Recent work" drops its column entirely so the tiles widen into the
  // freed space, rather than leaving a gap.
  const boardStyle = isNarrow
    ? {
        display: "grid",
        gap: "0.85rem",
        gridTemplateColumns: "1fr 1fr",
        gridTemplateAreas: `"author author" "achv achv" "t1 t2" "t3 t4" "t5 t6"${
          showRecent ? ' "activity activity"' : ""
        }`,
      }
    : {
        display: "grid",
        gap: "0.85rem",
        gridTemplateColumns: showRecent
          ? "305px repeat(3, 1fr) 330px"
          : "305px repeat(3, 1fr)",
        gridTemplateRows: "1fr 1fr",
        gridTemplateAreas: showRecent
          ? '"author t1 t2 t3 activity" "achv t4 t5 t6 activity"'
          : '"author t1 t2 t3" "achv t4 t5 t6"',
      };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3.5">
      {/* Welcome + top KPIs */}
      <div className="flex flex-none flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-h1 text-foreground">
            Welcome back{user ? `, ${user.display_name}` : ""}
          </h1>
          <p className="mt-0.5 text-body text-muted-foreground">
            {isEmpty
              ? "Let's publish your first practice material."
              : "Here's how your material is doing."}
          </p>
        </div>
        <div className="flex items-center gap-5">
          <div className="text-right">
            <div className="text-kpi tabular-nums text-foreground">
              {stats.materials_total}
            </div>
            <div className="mt-0.5 text-micro text-muted-foreground">Materials</div>
          </div>
          <div className="text-right">
            <div className="text-kpi tabular-nums text-foreground">
              {stats.learners}
            </div>
            <div className="mt-0.5 text-micro text-muted-foreground">
              Learners reached
            </div>
          </div>
          <div className="text-right">
            <div className="text-kpi tabular-nums text-foreground">
              {isEmpty ? DASH : formatContentHours(stats.content_ms)}
            </div>
            <div className="mt-0.5 text-micro text-muted-foreground">
              Content hours
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowRecent((v) => !v)}
            aria-pressed={showRecent}
            aria-label={showRecent ? "Hide recent work" : "Show recent work"}
            title={showRecent ? "Hide recent work" : "Show recent work"}
            className="flex size-9 items-center justify-center rounded-md border border-foreground/10 text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            {showRecent ? (
              <PanelRightClose className="size-4" />
            ) : (
              <PanelRightOpen className="size-4" />
            )}
          </button>
        </div>
      </div>

      {/* Board — one screen; only the activity feed / achievements scroll
          internally above ~1180px, everything stacks (and the page may
          scroll) below it. */}
      <MagicBento className="min-h-0 flex-1" style={boardStyle}>
        {/* Profile */}
        <div style={{ gridArea: "author" }} className={cn(glass, "min-h-0 overflow-hidden p-0")}>
          {/* Fixed band — tall enough for the name that sits on the seam. Spare
              height goes to the stats row below, not into the gradient. */}
          <div className="relative h-[5.5rem] flex-none bg-gradient-to-br from-primary/25 via-transparent to-foreground/10">
            <button
              type="button"
              aria-label="Edit profile"
              title="Edit profile"
              className="absolute top-2 right-2 flex size-6.5 items-center justify-center rounded-full border border-foreground/15 bg-background/40 text-foreground backdrop-blur-sm transition-colors hover:border-primary/45 hover:text-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              <Pencil className="size-3" />
            </button>
          </div>
          {/* Pulled up by half the avatar (5.3rem / 2) so the avatar's centre
              sits exactly on the cover seam. The right column matches the
              avatar's height and splits with justify-between, which puts the
              name in the upper half (over the cover) and the level in the
              lower half (below the seam). */}
          <div className="relative z-10 -mt-[2.65rem] flex flex-none gap-3 px-3.5 pb-3">
            {user && (
              <UserAvatar
                user={user}
                className="size-[5.3rem] flex-none text-2xl ring-4 ring-card/80"
              />
            )}
            <div className="flex h-[5.3rem] min-w-0 flex-1 flex-col">
              {/* Two equal halves split by the seam: the name bottom-aligns
                  onto it, the handle + level sit just under it. */}
              <div className="flex h-[2.65rem] min-w-0 items-end pb-1">
                <div className="truncate text-[1.25rem] leading-none font-semibold tracking-tight text-foreground">
                  {user?.display_name ?? "—"}
                </div>
              </div>
              {/* justify-start (not centre): keeps the handle + level bar tucked
                  up close under the seam rather than floating mid-half. */}
              <div className="flex h-[2.65rem] flex-col justify-start pt-1">
                <div className="mb-1 flex items-baseline justify-between gap-2 text-micro text-muted-foreground">
                  <span className="truncate">
                    {user?.email ? `@${user.email.split("@")[0]}` : ""}
                  </span>
                  <b className="shrink-0 text-label font-bold tabular-nums text-muted-foreground">
                    Lvl {DASH}
                  </b>
                </div>
                <div className="flex gap-0.5" aria-hidden>
                  {Array.from({ length: 7 }).map((_, i) => (
                    <i key={i} className="h-1.5 flex-1 rounded-sm bg-foreground/14" />
                  ))}
                </div>
              </div>
            </div>
          </div>
          {/* Takes the card's spare height and centres the row in it, so the
              labels never end up flush against the divider below. */}
          <div className="grid flex-1 grid-cols-3 content-center px-1 pb-3">
            <Stat value={DASH} label="Subscribers" />
            <Stat value={String(stats.learners)} label="Learners" />
            <Stat
              value={isEmpty ? DASH : formatContentHours(stats.content_ms)}
              label="Content"
            />
          </div>
          <div className="flex-none grid grid-cols-3 border-t border-foreground/9">
            {[
              { icon: ArrowUpRight, label: "View public profile" },
              { icon: Share2, label: "Share profile" },
              { icon: Settings2, label: "Studio settings" },
            ].map(({ icon: Icon, label }) => (
              <button
                key={label}
                type="button"
                aria-label={label}
                title={label}
                className="flex items-center justify-center py-2 text-muted-foreground transition-colors hover:text-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                <Icon className="size-4" />
              </button>
            ))}
          </div>
        </div>

        {/* Achievements */}
        <div style={{ gridArea: "achv" }} className={cn(glass, "min-h-0 p-3.5")}>
          <div className="mb-2.5 flex flex-none items-center justify-between">
            <h2 className="flex items-center gap-1.5 text-panel text-foreground">
              <Trophy className="size-4" aria-hidden />
              Achievements
            </h2>
            <SoonChip />
          </div>
          <div className="grid min-h-0 flex-1 auto-rows-fr grid-cols-3 gap-2 overflow-y-auto">
            {ACHIEVEMENTS.map((label) => (
              <div
                key={label}
                className="flex flex-col items-center justify-center gap-1 opacity-45"
              >
                <div className="flex size-11 items-center justify-center rounded-full border border-dashed border-foreground/18 bg-foreground/7 text-muted-foreground">
                  <Lock className="size-4" aria-hidden />
                </div>
                <div className="text-center text-micro leading-tight text-muted-foreground">
                  {label}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-2 flex-none border-t border-dashed border-foreground/12 pt-1.5 text-micro text-muted-foreground">
            Badges unlock once levelling &amp; achievements ship.
          </div>
        </div>

        {/* Material-type tiles */}
        <TypeTile
          gridArea="t1"
          icon={Headphones}
          title="Listening"
          description="Form completion — graded the moment a learner submits."
          available
          stats={[
            { value: String(listening?.total ?? 0), label: "materials" },
            {
              value: listening ? String(listening.completions) : "0",
              label: "completed",
            },
            { value: DASH, label: "saves" },
          ]}
          href={
            (listening?.total ?? 0) > 0 ? "/studio/materials" : "/studio/materials/new"
          }
          ctaLabel={(listening?.total ?? 0) > 0 ? "Manage" : "Create your first"}
        />
        <TypeTile
          gridArea="t2"
          icon={Keyboard}
          title="Dictation"
          description="Listen and type, segment by segment, with word-level feedback."
          available
          stats={[
            { value: String(dictation?.total ?? 0), label: "materials" },
            {
              value: dictation ? String(dictation.completions) : "0",
              label: "completed",
            },
            { value: DASH, label: "saves" },
          ]}
          href={(dictation?.total ?? 0) > 0 ? "/materials" : "/materials/new"}
          ctaLabel={(dictation?.total ?? 0) > 0 ? "Manage" : "Create your first"}
        />
        <TypeTile
          gridArea="t3"
          icon={BookOpen}
          title="Reading"
          description="Timed passages with comprehension questions."
          available={false}
          stats={[
            { value: DASH, label: "materials" },
            { value: DASH, label: "completed" },
            { value: DASH, label: "saves" },
          ]}
          href="#"
          ctaLabel="Coming soon"
        />
        <TypeTile
          gridArea="t4"
          icon={PenLine}
          title="Writing"
          description="Task 1 & 2 prompts with structured feedback."
          available={false}
          stats={[
            { value: DASH, label: "materials" },
            { value: DASH, label: "completed" },
            { value: DASH, label: "saves" },
          ]}
          href="#"
          ctaLabel="Coming soon"
        />
        <TypeTile
          gridArea="t5"
          icon={Sparkles}
          title="Vocabulary"
          description="Spaced-repetition word building."
          available={false}
          stats={[
            { value: DASH, label: "materials" },
            { value: DASH, label: "completed" },
            { value: DASH, label: "saves" },
          ]}
          href="#"
          ctaLabel="Coming soon"
        />
        <TypeTile
          gridArea="t6"
          icon={Target}
          title="Mock builder"
          description="Assemble a full mock test from your material."
          available={false}
          isTool
          stats={[
            { value: DASH, label: "mocks" },
            { value: DASH, label: "taken" },
            { value: DASH, label: "saves" },
          ]}
          href="#"
          ctaLabel="Coming soon"
        />

        {/* Recent work — collapsible; hidden state persists in localStorage. */}
        {showRecent && (
        <div style={{ gridArea: "activity" }} className={cn(deep, "min-h-0 p-3.5")}>
          <div className="mb-1.5 flex flex-none items-center justify-between">
            {/* Named for what it actually is: the author's own recent work, so
                you can resume it. Learner activity (completions, saves,
                subscribers) doesn't exist yet — see the footer note. */}
            <h2 className="text-panel text-foreground">Recent work</h2>
            <div className="flex items-center gap-2">
              {!isEmpty && (
                <span className="text-micro text-muted-foreground">
                  tap to continue
                </span>
              )}
              <button
                type="button"
                onClick={() => setShowRecent(false)}
                aria-label="Hide recent work"
                title="Hide recent work"
                className="flex size-5 items-center justify-center rounded text-muted-foreground transition-colors hover:text-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                <X className="size-3.5" />
              </button>
            </div>
          </div>

          {stats.recent.length > 0 ? (
            <>
              <div className="min-h-0 flex-1 overflow-y-auto pr-0.5">
                {stats.recent.map((item) => (
                  <ActivityRow key={item.id} item={item} />
                ))}
              </div>
              <div className="mt-1.5 flex-none border-t border-dashed border-foreground/12 pt-1.5 text-micro text-muted-foreground">
                Learner activity — completions, saves, subscribers — appears
                here once it ships.
              </div>
            </>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 p-4 text-center text-muted-foreground">
              <Headphones className="size-6 opacity-50" aria-hidden />
              <p className="max-w-52 text-body">
                Nothing here yet. Create your first material and it&apos;ll show
                up here.
              </p>
              <Link
                to="/studio/materials/new"
                className="text-label font-semibold text-primary hover:underline"
              >
                Create your first material
              </Link>
            </div>
          )}
        </div>
        )}
      </MagicBento>
    </div>
  );
}
