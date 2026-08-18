import { Check, ImageUp, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { MediaDropzone } from "@/features/listening/components/MediaDropzone";
import { TaskPicture } from "@/features/listening/components/TaskPicture";
import type { GroupImage } from "@/features/listening/types";

/**
 * The picture a map or diagram group is answered on, as the author works with
 * it: dropped in, looked at, fitted to the page, replaced, taken away.
 *
 * It sits above the list of labels because that is where the paper prints it,
 * and because the labels are written while looking at it. Which is also why
 * the drawn picture here is the same component the candidate meets
 * (TaskPicture) rather than a preview of it: this block IS the preview, and a
 * second copy of the rendering rules is somewhere for the two to disagree.
 *
 * The author draws the letters on the picture themselves, before uploading —
 * there is no pin editor here and there shouldn't be. Every map an author has
 * already has its A–H on it, in the position the person who drew it meant, and
 * a tool for placing markers over an image would be asking them to do that work
 * again, worse, in a browser.
 */

interface GroupPictureProps {
  image: GroupImage | null;
  onUpload: (file: File) => void;
  onRemove: () => void;
  uploading: boolean;
  /** What went wrong with the last attempt, in the server's words — the file
   *  was refused for a reason the author can act on ("upload a PNG, JPEG or
   *  WebP", "scale it down"), so the reason is worth showing. */
  error?: string | null;
  adapt: boolean;
  onAdaptChange: (v: boolean) => void;
  /** "map" or "diagram", for the prompts and the alt text. */
  noun: string;
}

export function GroupPicture({
  image,
  onUpload,
  onRemove,
  uploading,
  error,
  adapt,
  onAdaptChange,
  noun,
}: GroupPictureProps) {
  if (!image) {
    return (
      <div className="mb-3">
        <MediaDropzone
          size="inline"
          accept="image/png,image/jpeg,image/webp"
          prompt={`drop the ${noun} here, or click to browse`}
          hint="png, jpeg or webp — with its letters already on it"
          onUpload={onUpload}
          busy={uploading}
          busyLabel="uploading…"
        />
        {error && <p className="mt-2 text-center text-xs text-warning">{error}</p>}
      </div>
    );
  }

  return (
    <div className="mb-3 rounded-lg border border-border p-3">
      <TaskPicture
        url={image.url}
        width={image.width}
        height={image.height}
        adapt={adapt}
        alt={`The ${noun} this task is labelled on`}
      />

      {/* Under the picture rather than over it: a control strip floated on top
          covers part of the thing the author is looking at, and this one has
          words in it. */}
      <div className="mt-2.5 flex flex-wrap items-center gap-2 border-t border-border pt-2.5">
        <button
          type="button"
          role="switch"
          aria-checked={adapt}
          onClick={() => onAdaptChange(!adapt)}
          title={
            adapt
              ? "Drawn in the page's own colours"
              : "Drawn exactly as uploaded"
          }
          className={cn(
            "flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-xs transition-colors",
            adapt
              ? "bg-primary/12 text-primary"
              : "text-muted-foreground/70 hover:bg-foreground/6 hover:text-foreground",
          )}
        >
          <span
            aria-hidden
            className={cn(
              "flex size-3.5 shrink-0 items-center justify-center rounded-[3px] border transition-colors",
              adapt ? "border-primary bg-primary/20" : "border-border",
            )}
          >
            {adapt && <Check className="size-2.5" aria-hidden />}
          </span>
          fit to the page's colours
        </button>

        <span className="ml-auto flex items-center gap-1">
          <label
            title={`Replace the ${noun}`}
            className={cn(
              "flex cursor-pointer items-center gap-1.5 rounded-md px-1.5 py-0.5 text-xs text-muted-foreground/70 transition-colors hover:bg-foreground/6 hover:text-foreground",
              uploading && "pointer-events-none opacity-60",
            )}
          >
            <ImageUp className="size-3.5" aria-hidden />
            {uploading ? "uploading…" : "replace"}
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              disabled={uploading}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onUpload(f);
                e.target.value = "";
              }}
            />
          </label>
          <button
            type="button"
            onClick={onRemove}
            title={`Remove the ${noun}`}
            aria-label={`Remove the ${noun}`}
            className="flex size-6 items-center justify-center rounded-md text-muted-foreground/70 transition-colors hover:text-destructive"
          >
            <X className="size-3.5" aria-hidden />
          </button>
        </span>
      </div>

      {error && <p className="mt-2 text-xs text-warning">{error}</p>}
    </div>
  );
}
