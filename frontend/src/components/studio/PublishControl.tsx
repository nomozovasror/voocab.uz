import { useState } from "react";
import { Globe, Loader2, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { getErrorMessage } from "@/lib/api";
import { toast } from "@/lib/toast";
import type { Visibility } from "@/features/listening/types";

/**
 * Publish or return a material to draft.
 *
 * Replaces the private/public toggle these editors used to carry. The toggle
 * read as a preference — two words, pick one — when it is the one action here
 * that decides whether strangers can take the material, and it implied the
 * choice was always available. It isn't: the server keeps a set of
 * requirements (a title, the audio, the questions and their answers) and
 * refuses to publish anything that doesn't meet them.
 *
 * So this shows the state the material is in and the one move available from
 * it, and when that move is refused it says why, in the server's words —
 * which name what is missing, rather than a generic failure.
 */

interface PublishControlProps {
  visibility: Visibility;
  /** Persists the change. Rejects with the server's reason when refused. */
  onChange: (next: Visibility) => Promise<unknown>;
  className?: string;
}

export function PublishControl({
  visibility,
  onChange,
  className,
}: PublishControlProps) {
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const isPublic = visibility === "public";

  const move = async (next: Visibility) => {
    setBusy(true);
    setRefusal(null);
    try {
      await onChange(next);
      toast({
        title: next === "public" ? "Published" : "Back to draft",
        message:
          next === "public"
            ? "Anyone with the link can take this material now."
            : "Only you can see this material now.",
        kind: next === "public" ? "success" : "info",
      });
    } catch (e) {
      // Kept on the page as well as in the toast: this is a list of things
      // to go and fix, and it should still be there once the toast is gone.
      setRefusal(getErrorMessage(e));
      toast({
        title: next === "public" ? "Not published" : "Not saved",
        message: getErrorMessage(e),
        kind: "warning",
        duration: 0,
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex flex-wrap items-center gap-3">
        <span
          className={cn(
            "inline-flex items-center gap-1.5 text-sm",
            isPublic ? "text-success" : "text-muted-foreground",
          )}
        >
          {isPublic ? (
            <Globe className="size-4" aria-hidden />
          ) : (
            <Lock className="size-4" aria-hidden />
          )}
          {isPublic ? "Public" : "Draft"}
        </span>

        <Button
          type="button"
          variant={isPublic ? "outline" : "default"}
          size="sm"
          disabled={busy}
          onClick={() => void move(isPublic ? "private" : "public")}
        >
          {busy && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
          {isPublic ? "Back to draft" : "Publish"}
        </Button>
      </div>

      {refusal && <p className="text-sm text-warning">{refusal}</p>}
    </div>
  );
}
