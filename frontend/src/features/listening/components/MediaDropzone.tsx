import { useState } from "react";
import { Loader2, Upload } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Where an uploaded file comes in.
 *
 * Three places ask for one and they are the same ask: the opening step, where
 * the recording is the only thing on the page; the player pane, which shows
 * this instead of a waveform until there is something to draw; and a map or
 * diagram task, which shows it instead of the picture. What differs between
 * them is what they accept, what they say, and how much room they have — so
 * those are props and the rest is shared.
 */

interface MediaDropzoneProps {
  onUpload: (file: File) => void;
  /** Anything in flight — the upload itself, or the save that attaches it.
   *  Both leave the author with nothing to do but wait, so both look alike. */
  busy: boolean;
  /** What the waiting is, when it is worth naming. */
  busyLabel?: string;
  /** The file input's filter. Only ever a filter: what a file actually IS is
   *  decided by the server, from its header for a picture and from its
   *  container for a recording. */
  accept: string;
  /** What to drop here. */
  prompt: string;
  /** Which formats, in the words an author uses for them. */
  hint: string;
  /** `stage` is the opening step's version: the page has nothing else on it,
   *  so the target is worth the height. `inline` sits inside a block that
   *  already has other things in it. */
  size?: "pane" | "stage" | "inline";
}

export function MediaDropzone({
  onUpload,
  busy,
  busyLabel,
  accept,
  prompt,
  hint,
  size = "pane",
}: MediaDropzoneProps) {
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
        size === "stage" ? "py-20" : size === "pane" ? "py-14" : "py-8",
        dragOver ? "border-primary text-foreground" : "border-border",
        busy && "pointer-events-none opacity-60",
      )}
    >
      {busy ? (
        <Loader2 className="size-5 animate-spin text-primary" aria-hidden />
      ) : (
        <Upload className="size-5" aria-hidden />
      )}
      <span>{busy && busyLabel ? busyLabel : prompt}</span>
      <span className="text-xs text-muted-foreground">{hint}</span>
      <input
        type="file"
        accept={accept}
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
