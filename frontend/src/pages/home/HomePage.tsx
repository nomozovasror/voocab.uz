import { Link } from "react-router-dom";
import {
  BookOpen,
  Headphones,
  Keyboard,
  PenLine,
  SpellCheck,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ShootingStars } from "@/components/ShootingStars";
import { useTheme } from "@/theme/useTheme";

interface Section {
  title: string;
  description: string;
  icon: LucideIcon;
  to?: string;
}

const SECTIONS: Section[] = [
  {
    title: "Reading",
    description: "Timed passages with comprehension questions.",
    icon: BookOpen,
    to: "/reading",
  },
  {
    title: "Listening",
    description: "Audio exercises that train your ear.",
    icon: Headphones,
    to: "/listening",
  },
  {
    title: "Dictation",
    description: "Listen and type, segment by segment.",
    icon: Keyboard,
    to: "/dictation",
  },
  {
    title: "Writing",
    description: "Task 1 & 2 practice with structured feedback.",
    icon: PenLine,
  },
  {
    title: "Grammar",
    description: "Targeted drills on the rules that trip you up.",
    icon: SpellCheck,
  },
  {
    title: "Vocabulary",
    description: "Spaced-repetition word building.",
    icon: Sparkles,
  },
];

const STATS = [
  { value: "6", label: "Skill areas" },
  { value: "1,200+", label: "Practice items" },
  { value: "9.0", label: "Target band" },
];

export default function HomePage() {
  const { theme } = useTheme();

  return (
    <div className="relative z-10 space-y-16 pb-16">
      {/* Shooting-stars background: fixed layer behind all content. */}
      <ShootingStars className="fixed inset-0 -z-10" />

      {/* Hero */}
      <section className="space-y-5 pt-8">
        <span className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-muted-foreground">
          <Sparkles className="size-3.5 text-primary" />
          IELTS-focused practice
        </span>
        <h1 className="max-w-3xl text-4xl font-semibold tracking-tight text-foreground sm:text-5xl">
          Learn English, your way
        </h1>
        <p className="max-w-2xl text-lg text-muted-foreground">
          Reading, listening, dictation and more — one focused platform to move
          your band score up. Currently themed{" "}
          <span className="font-medium text-primary">{theme.label}</span>.
        </p>
        <div className="flex flex-wrap gap-3 pt-2">
          <Button asChild size="lg">
            <Link to="/dictation">Start practicing</Link>
          </Button>
          <Button asChild size="lg" variant="outline">
            <Link to="/vocabulary">Build vocabulary</Link>
          </Button>
        </div>
      </section>

      {/* Stats */}
      <section className="grid grid-cols-3 gap-4">
        {STATS.map((s) => (
          <div
            key={s.label}
            className="rounded-lg border border-border bg-card px-4 py-6 text-center"
          >
            <div className="text-3xl font-semibold text-primary">{s.value}</div>
            <div className="mt-1 text-sm text-muted-foreground">{s.label}</div>
          </div>
        ))}
      </section>

      {/* Practice sections */}
      <section className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold text-foreground">
            Practice sections
          </h2>
          <p className="text-muted-foreground">
            Pick a skill to drill. More sections are on the way.
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {SECTIONS.map((section) => {
            const Icon = section.icon;
            const card = (
              <Card className="h-full transition-colors hover:border-primary/50">
                <CardHeader>
                  <div className="flex size-10 items-center justify-center rounded-md bg-primary/10 text-primary">
                    <Icon className="size-5" />
                  </div>
                  <CardTitle className="flex items-center gap-2">
                    {section.title}
                    {!section.to && (
                      <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-normal text-muted-foreground">
                        soon
                      </span>
                    )}
                  </CardTitle>
                  <CardDescription>{section.description}</CardDescription>
                </CardHeader>
              </Card>
            );

            return section.to ? (
              <Link key={section.title} to={section.to} className="block">
                {card}
              </Link>
            ) : (
              <div key={section.title} className="opacity-70">
                {card}
              </div>
            );
          })}
        </div>
      </section>

      {/* Token showcase — every color below is theme-driven, so switching the
          theme repaints all of it. No hardcoded colors anywhere. */}
      <section className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold text-foreground">
            Fully themeable
          </h2>
          <p className="text-muted-foreground">
            Switch the theme in the header and watch every element recolor.
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Theme tokens</CardTitle>
            <CardDescription>
              Buttons and swatches below are driven entirely by design tokens.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="flex flex-wrap gap-3">
              <Button>Primary</Button>
              <Button variant="secondary">Secondary</Button>
              <Button variant="outline">Outline</Button>
              <Button variant="ghost">Ghost</Button>
              <Button variant="destructive">Destructive</Button>
              <Button variant="link">Link</Button>
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Swatch
                label="primary"
                className="bg-primary text-primary-foreground"
              />
              <Swatch
                label="success"
                className="bg-success text-success-foreground"
              />
              <Swatch
                label="warning"
                className="bg-warning text-warning-foreground"
              />
              <Swatch
                label="destructive"
                className="bg-destructive text-destructive-foreground"
              />
            </div>
          </CardContent>
        </Card>
      </section>

      {/* Closing CTA */}
      <section className="rounded-xl border border-border bg-card px-6 py-12 text-center">
        <h2 className="text-2xl font-semibold text-foreground">
          Ready to raise your band score?
        </h2>
        <p className="mx-auto mt-2 max-w-xl text-muted-foreground">
          Jump into a dictation drill and get instant, segment-level feedback.
        </p>
        <Button asChild size="lg" className="mt-6">
          <Link to="/dictation">Start a dictation</Link>
        </Button>
      </section>
    </div>
  );
}

function Swatch({ label, className }: { label: string; className: string }) {
  return (
    <div
      className={`flex h-16 items-center justify-center rounded-md text-sm font-medium ${className}`}
    >
      {label}
    </div>
  );
}
