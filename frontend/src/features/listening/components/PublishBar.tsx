import { Check, Circle, Globe, Loader2, Lock } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { Visibility } from "@/features/listening/types";

/**
 * Where the material stands, and the one move available from it.
 *
 * This replaces a pair of plain "draft" and "publish" links that sat side by
 * side. Two problems with that: neither said which one the material currently
 * was — "draft" read as a state, so a published material looked like it was
 * offering to show you the draft — and the requirements for publishing only
 * appeared as a red line *after* you pressed the button, one at a time.
 *
 * So: the state is stated, the action is a verb, and what is still missing is
 * listed before it is asked for. The publish button stays enabled when things
 * are outstanding — pressing it opens the list rather than refusing silently,
 * because "why is this disabled" is a worse question than a checklist.
 */

export interface PublishRequirement {
  label: string;
  done: boolean;
  /** What is missing, when it helps to be specific ("Questions 3, 7"). */
  detail?: string;
}

interface PublishBarProps {
  visibility: Visibility;
  requirements: PublishRequirement[];
  /** The server's own reason for refusing, when it refused. It keeps the
   *  same requirements, so this only appears if the two ever disagree —
   *  which is exactly when it is worth reading. */
  refusal?: string | null;
  busy?: boolean;
  onPublish: () => void;
  onUnpublish: () => void;
}

export function PublishBar({
  visibility,
  requirements,
  refusal,
  busy,
  onPublish,
  onUnpublish,
}: PublishBarProps) {
  const isPublic = visibility === "public";
  const outstanding = requirements.filter((r) => !r.done);
  const ready = outstanding.length === 0 && !refusal;

  if (isPublic) {
    return (
      <div className="flex items-center gap-2.5">
        <span className="flex items-center gap-1.5 text-xs text-success">
          <Globe className="size-3.5" aria-hidden />
          Public
        </span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={onUnpublish}
        >
          {busy && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
          Unpublish
        </Button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2.5">
      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Lock className="size-3.5" aria-hidden />
        Draft
      </span>

      {/* Ready: a plain button that publishes. Not ready: the same button
          opens the list instead, so one press always tells you something —
          better than a disabled control and the question of why. */}
      {ready ? (
        <Button type="button" size="sm" disabled={busy} onClick={onPublish}>
          {busy && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
          Publish
        </Button>
      ) : (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button type="button" size="sm" variant="secondary">
              Publish
              {outstanding.length > 0 && (
                <span className="ml-0.5 rounded-full bg-foreground/12 px-1.5 text-[10px] tabular-nums">
                  {outstanding.length}
                </span>
              )}
            </Button>
          </DropdownMenuTrigger>

          <DropdownMenuContent align="end" className="w-72 p-3">
            {refusal && outstanding.length === 0 ? (
              <p className="mb-2 text-xs text-warning">{refusal}</p>
            ) : (
              <p className="mb-2 text-xs text-muted-foreground">
                {outstanding.length === 1
                  ? "One thing left before this can be published:"
                  : `${outstanding.length} things left before this can be published:`}
              </p>
            )}
            <ul className="space-y-1.5">
              {requirements.map((requirement) => (
                <li
                  key={requirement.label}
                  className={cn(
                    "flex items-start gap-2 text-xs",
                    requirement.done ? "text-muted-foreground" : "text-foreground",
                  )}
                >
                  {requirement.done ? (
                    <Check className="mt-0.5 size-3.5 shrink-0 text-success" aria-hidden />
                  ) : (
                    <Circle
                      className="mt-0.5 size-3.5 shrink-0 text-muted-foreground/50"
                      aria-hidden
                    />
                  )}
                  <span className={cn(requirement.done && "line-through decoration-1")}>
                    {requirement.label}
                    {!requirement.done && requirement.detail && (
                      <span className="block text-muted-foreground">
                        {requirement.detail}
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  );
}
