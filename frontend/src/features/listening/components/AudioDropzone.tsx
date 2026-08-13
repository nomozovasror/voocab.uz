import { useState } from "react";
import { Loader2, Upload } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Where the recording comes in.
 *
 * Two places ask for it and they are the same ask: the opening step, where
 * it is the only thing on the page, and the player pane, which shows this
 * instead of a waveform until there is something to draw. The difference
 * between them is how much room they have, which is `size` and nothing else.
 */

interface AudioDropzoneProps {
  onUpload: (file: File) => void;
  /** Anything in flight — the upload itself, or the save that attaches it.
   *  Both leave the author with nothing to do but wait, so both look alike. */
  busy: boolean;
  /** What the waiting is, when it is worth naming. */
  busyLabel?: string;
  /** `stage` is the opening step's version: the page has nothing else on it,
   *  so the target is worth the height. */
  size?: "pane" | "stage";
}

export function AudioDropzone({
  onUpload,
  busy,
  busyLabel,
  size = "pane",
}: AudioDropzoneProps) {
  const [dragOver, setDragOver] = useState(false);

  return (
    <label
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        const f = e.dataTransfer.files?.[0];
        if (f) onUpload(f);
      }}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 text-center text-muted-foreground transition-colors",
        size === "stage" ? "py-20" : "py-14",
        dragOver ? "border-primary text-foreground" : "border-border",
        busy && "pointer-events-none opacity-60",
      )}
    >
      {busy ? (
        <Loader2 className="size-5 animate-spin text-primary" aria-hidden />
      ) : (
        <Upload className="size-5" aria-hidden />
      )}
      <span>
        {busy && busyLabel ? busyLabel : "drop audio here, or click to browse"}
      </span>
      <span className="text-xs text-muted-foreground">mp3, wav, m4a</span>
      <input
        type="file"
        accept="audio/*"
        className="hidden"
        disabled={busy}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onUpload(f);
          e.target.value = "";
        }}
      />
    </label>
  );
}
