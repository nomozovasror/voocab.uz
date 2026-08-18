import { cn } from "@/lib/utils";
import { mediaUrl } from "@/features/listening/api";

/**
 * The picture a map or diagram task is labelled on, drawn the same way in the
 * editor and on the take page — which is the point of it being one component.
 * What the author fits to the page is what the candidate sits.
 *
 * Two things it does beyond showing an image.
 *
 * It holds the picture's box before the bytes arrive. The dimensions come from
 * the file's own header at upload, so the aspect ratio is known: without it,
 * every take begins with the questions jumping down the screen as the map
 * lands, and every autosave in the editor does the same.
 *
 * And it can fit the picture to the page's colours. Almost every map an author
 * has is black line art on white, which in dark mode is a lit sheet punched
 * into a dark page — the one bright rectangle on the screen, in a test someone
 * is reading for half an hour. Inverting it turns the ink light and the sheet
 * black; blending it out with `screen` then drops the black entirely, so what
 * is left is our own background with the drawing on it, hue-rotated back so a
 * blue title stays blue. In a light theme there is nothing to invert and
 * `multiply` does the same job for the sheet, dropping the white.
 *
 * Which is not always wanted — a coloured plan, a photograph — and the bytes
 * cannot tell us which this is. So it is the author's switch, stored per
 * picture, and this only obeys it.
 */

interface TaskPictureProps {
  /** As stored: relative to the API for local media, absolute for R2. */
  url: string;
  width: number;
  height: number;
  /** Fit it to the page's colours rather than print it as uploaded. */
  adapt: boolean;
  /** What it is, for anyone who can't see it. The picture carries the
   *  answers, so there is a real limit to what alt text can do here — but
   *  "map" beats an empty string, and the instruction line above says more. */
  alt: string;
  className?: string;
}

export function TaskPicture({
  url,
  width,
  height,
  adapt,
  alt,
  className,
}: TaskPictureProps) {
  return (
    <img
      src={mediaUrl(url)}
      alt={alt}
      width={width}
      height={height}
      // The intrinsic size is on the element, so the box is right from the
      // first paint; the styles then let it shrink to the column it is in
      // while keeping the shape.
      style={{ aspectRatio: `${width} / ${height}` }}
      className={cn(
        "mx-auto block h-auto w-full max-w-2xl rounded-md",
        adapt &&
          "mix-blend-multiply dark:mix-blend-screen dark:[filter:invert(1)_hue-rotate(180deg)_brightness(0.92)]",
        className,
      )}
    />
  );
}
