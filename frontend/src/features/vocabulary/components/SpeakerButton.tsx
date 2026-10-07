import { useState } from "react";
import { Volume2, VolumeX } from "lucide-react";
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { playClip } from "@/features/vocabulary/audio";

/**
 * The speaker: press, hear the word. Used by the practice reveal and the word
 * page; the listen card draws its own button (a big one, with the slow toggle
 * beside it).
 *
 * A file that cannot be played turns the button into a quiet "not available"
 * rather than hiding it (the row would reflow) or toasting (a missing
 * pronunciation is not an event worth interrupting somebody for). It tries
 * again on the next press, since a render that was still being made a moment
 * ago may be there now.
 *
 * `needsTap` is the parent saying "I tried to play this by myself and the
 * browser refused" (autoplay policy). The button then pulses and says "Tap to
 * play" in text, so a refused autoplay is never silently nothing. Any press
 * calls `onPlay` so the parent can clear it.
 */
export function SpeakerButton({
  url,
  label = "Play pronunciation",
  className,
  needsTap = false,
  onPlay,
}: {
  url: string;
  label?: string;
  className?: string;
  needsTap?: boolean;
  onPlay?: () => void;
}) {
  const [failed, setFailed] = useState(false);

  async function play() {
    onPlay?.();
    const result = await playClip(url);
    if (result === "failed") setFailed(true);
    else if (result === "started") setFailed(false);
  }

  const text = failed ? "Audio isn't available" : needsTap ? "Tap to play" : label;
  return (
    <>
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
            needsTap && "animate-pulse bg-primary/20 text-primary-ink",
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
    {needsTap && (
      <span className="text-xs text-muted-foreground" aria-hidden>
        Tap to play
      </span>
    )}
    </>
  );
}
