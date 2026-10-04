import { useState } from "react";
import { Volume2, VolumeX } from "lucide-react";
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { playClip } from "@/features/vocabulary/audio";

/**
 * The speaker: press, hear the word. Used by the practice reveal and the word
 * page; the listen card draws its own button because it says which clip it
 * will play.
 *
 * A file that cannot be played turns the button into a quiet "not available"
 * rather than hiding it (the row would reflow) or toasting (a missing
 * pronunciation is not an event worth interrupting somebody for). It tries
 * again on the next press, since a clip that was still being cut a moment ago
 * may be there now.
 */
export function SpeakerButton({
  url,
  label = "Play pronunciation",
  className,
}: {
  url: string;
  label?: string;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);

  async function play() {
    const result = await playClip(url);
    if (result === "failed") setFailed(true);
    else if (result === "started") setFailed(false);
  }

  const text = failed ? "Audio isn't available" : label;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          // Tells the practice page's Enter-to-advance listener that Enter
          // here is this button's own, so pressing it does not also skip the
          // reveal.
          data-no-advance
          onClick={() => void play()}
          aria-label={text}
          className={cn(
            "inline-flex size-7 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors duration-fast hover:bg-surface-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
            className,
          )}
        >
          {failed ? (
            <VolumeX className="size-4" aria-hidden />
          ) : (
            <Volume2 className="size-4" aria-hidden />
          )}
        </button>
      </TooltipTrigger>
      <TooltipContent side="top" className="px-2 py-1 text-xs">
        {text}
      </TooltipContent>
    </Tooltip>
  );
}
