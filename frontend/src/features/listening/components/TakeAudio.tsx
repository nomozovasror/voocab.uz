import { FastForward, Pause, Play, Redo2, RotateCcw, Undo2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { fmtClock } from "@/lib/time";
import { useMediaQuery } from "@/hooks/use-media-query";
import type { Opening } from "@/components/layout/HeaderGround";
import {
  PartStrip,
  Waveform,
  currentPart,
  type WavePart,
} from "@/features/listening/components/Waveform";
import { NUDGE_MS, type AudioEngine } from "@/features/listening/use-audio-engine";
import type { WaveShape } from "@/features/listening/use-waveform";

/**
 * The recording, and the only controls over it the rules allow.
 *
 * Not `<audio controls>`. The browser's own bar has a seek handle, a speed
 * menu and a download button welded to it, and exam mode has to be able to
 * take those away — a page that shows the native control and then asks
 * candidates not to use it is not enforcing anything. Every control here is
 * drawn only if its rule permits it, and the rules arrive as a value (see
 * take-config.ts).
 *
 * ## The shape of it
 *
 * The recording is at the top, its parts named underneath it, and the
 * controls below that with **play in the middle** — the arrangement every
 * music player has, because it is the arrangement a hand reaches into without
 * looking. The clock sits out on the left with the part it is currently in;
 * speed and Loop, which are set once and forgotten, sit out on the right.
 *
 * ## One player, two sizes, and a movement between them
 *
 * Scrolled past, the player shrinks into a strip in the header — the same
 * journey the catalogue's search field makes, and for the same reason: a
 * control somebody needs the whole way down a four-screen paper cannot be at
 * the top of it. Nothing is re-parented and nothing is duplicated. A copy
 * appearing where another disappears is a cut, and a cut reads as two things
 * swapping rather than one thing going somewhere.
 *
 * So every difference between the two sizes is a NUMBER on the same element
 * (`BIG` and `DOCK` below) and every number is transitioned. **Nothing moves
 * sideways**: the clock stays left, play stays centred, speed stays right,
 * and the waveform stays across the top. Only heights change, plus the
 * handful of things that have no smaller version and fade. That is what keeps
 * the movement legible — and it is why the shrunken player keeps the
 * waveform at all, which is the whole point of it: somebody four screens down
 * can still see how much recording is left.
 *
 * It happens in two beats. First the part labels and the controls that do not
 * survive the shrink go; then, with room made, the box collapses. Reversed on
 * the way back out.
 *
 * ## Two more things that are not obvious
 *
 * The geometry is written down rather than measured. Measuring means reading
 * boxes that are themselves mid-transition, which is the one moment they
 * cannot be read.
 *
 * And the card is out of the flow. Height is a layout property: animating it
 * on an element in the flow re-lays-out everything after it sixty times a
 * second, and after this element comes a forty-question paper. So the
 * component is two boxes — an outer shell holding a constant `PLAYER_H` (it
 * is what sticks), and the card absolutely positioned inside it. A constant
 * outer height is a constant document, so the paper below cannot slide.
 */

/** The tallest the player ever is — a material with parts to name. What the
 *  skeleton holds open, and the ceiling everything else is measured against;
 *  the card works out its own height from what it has to show (see the note
 *  on PARTS_H below). */
export const PLAYER_H = 184;
export const PLAYER_DOCK_H = 48;

/**
 * How wide the strip is once it has landed in the header.
 *
 * Three steps, because the room it lands in has three shapes. The islands sit
 * at the ends of a rail that stops growing at 1280, so past that the gap only
 * widens; below it, the brand island binds on the left and the account menu
 * on the right. Each number is the space between them at that width, less a
 * comfortable margin.
 */
const DOCK_W = { md: 428, lg: 492, xl: 700 } as const;

function useDockWidth(): number {
  const lg = useMediaQuery("(min-width: 64rem)");
  const xl = useMediaQuery("(min-width: 80rem)");
  return xl ? DOCK_W.xl : lg ? DOCK_W.lg : DOCK_W.md;
}

/** Beat one: what fades. Beat two: what moves.
 *
 *  They OVERLAP by design. Run strictly one after the other, the player sat
 *  still for a sixth of a second after it had stopped climbing and then set
 *  off again — two events where the reader is watching one movement. */
const FADE_MS = 180;
const MORPH_MS = 320;
const OVERLAP_MS = 90;

/**
 * Every dimension that differs between the two states.
 *
 * **Everything inside the card is absolutely positioned**, and that is not
 * fashion. The two states are not the same arrangement at two sizes: full
 * size, the recording is across the top with its parts named under it and the
 * controls below; shrunk, it is one row — play, the nudges, the waveform, the
 * clock, the speed. Pieces genuinely change places, and the only way for that
 * to be a MOVEMENT rather than one layout dissolving into another is for each
 * piece to have a coordinate in both and travel between them.
 *
 * Coordinates are given from whichever edge does not depend on the card's
 * width, so nothing here has to know how wide the card is — except the clock,
 * which crosses from one side to the other and is therefore placed with a
 * `calc()` off the far edge.
 *
 * Vertical numbers are measured from just inside the border, because that is
 * where an absolutely positioned child's `top` starts. Full size: 12 of air,
 * 72 of waveform, 4, 20 of labels, 10, then a 50px control row ending at 168
 * inside 182. Docked: one 24px row at 11, centred in 46.
 */
const BIG = {
  waveTop: 12,
  waveH: 72,
  rowH: 50,
  play: 44,
  nudge: 52,
  nudgeLabel: 16,
  ctl: 28,
  speed: 44,
  skip: 68,
  skipLabel: 31,
  clockW: 224,
} as const;

/** The three heights the card is built from, and the two ways they add up.
 *
 *  A single-part material has nothing to name, so the strip under the
 *  waveform is not drawn — and then the card must not hold twenty pixels of
 *  air where it would have been. 12 of top, 72 of waveform, (4 + 20 of
 *  labels), 10, a 50px control row, 14 of slack and 2 of border: 184 with the
 *  labels, 160 without. */
const PARTS_H = 20;
const PARTS_GAP = 4;
const ROW_GAP = 10;

const DOCK = {
  waveTop: 11,
  waveH: 24,
  rowH: 24,
  play: 24,
  // Icon only, like the skip beside it: the width is clipped from the
  // label's side, so the mark stays put and only the word goes.
  nudge: 32,
  nudgeLabel: 0,
  ctl: 24,
  // Speed is the one that goes. Between the two, skipping dead air is what a
  // learner reaches for WHILE working — which is exactly when the player is
  // shrunk — and the speed they set once at the top and leave alone.
  speed: 0,
  // Icon only down here: the width is clipped from the label's side, so the
  // mark stays put and only the word goes.
  skip: 32,
  skipLabel: 0,
  clockW: 116,
} as const;

/** The gutter, and the gaps between the pieces of the shrunken row. Constants
 *  because the waveform's docked span is worked out from them — it lands in
 *  the room the controls leave, so something has to know how much that is. */
const PAD = 12;
const GAP = 10;

/**
 * The window the ground has to hold open behind the docked player, and the
 * clock to open it on.
 *
 * The pane is glass, and glass over an opaque colour is an opaque colour — so
 * the band behind it stops short and the paper shows through. The opening is
 * narrower than the pane by twelve pixels a side, which is enough that its
 * rounded corners never let anything past. It travels on the same clock as
 * the width it is making room for, so the two are never out of step.
 */
export function useDockOpening(docked: boolean): Opening {
  const width = useDockWidth();
  return {
    width: docked ? width - 24 : 0,
    style: {
      transitionDuration: `${MORPH_MS}ms`,
      transitionDelay: `${docked ? OVERLAP_MS : 0}ms`,
    },
  };
}

export function TakePlayer({
  engine,
  shape,
  parts,
  docked = false,
  settled = false,
  className,
}: {
  engine: AudioEngine;
  /** Peaks and silences, from one decode — see use-waveform.ts. */
  shape: WaveShape;
  /** Empty where the author never marked the boundaries. */
  parts?: WavePart[];
  /** Shrunk into the header. The page decides when — see ListeningTakePage. */
  docked?: boolean;
  /**
   * This player never travels: it is small where it is, and as wide as its
   * column.
   *
   * The review screen's, and the reason it is a flag rather than a second
   * component. There is nothing continuous to listen to on a marked paper —
   * every play is somebody going back to one sentence — so the big state has
   * nothing to offer and the shrunken one is the whole player. Same engine,
   * same waveform, same controls; what it drops is the morph, which is the
   * only complicated thing here and exists solely because the take screen's
   * player has somewhere to go.
   */
  settled?: boolean;
  className?: string;
}) {
  const { config } = engine;
  const dockW = useDockWidth();
  const small = docked || settled;
  const m = small ? DOCK : BIG;
  const marked = parts ?? [];

  // With nothing to name, the strip is not drawn AND the card is shorter by
  // exactly what it would have taken. A row held open for a label that never
  // comes is the empty space this was meant to close.
  const partsH = marked.length > 0 ? PARTS_H : 0;
  const partsTop = BIG.waveTop + BIG.waveH + (partsH > 0 ? PARTS_GAP : 0);
  const bigRowTop = partsTop + partsH + ROW_GAP;
  const bigH = bigRowTop + BIG.rowH + 16;
  // The shell holds the tallest the card will ever be, so the document below
  // it never moves as the card shrinks. A settled player never grows, so its
  // shell is the card.
  const shellH = settled ? PLAYER_DOCK_H : bigH;

  // Going in, the fading happens first and the movement follows it; coming
  // back out, the movement goes first and the detail arrives after. Either
  // way the two beats are in the order that makes room before something needs
  // it.
  const fadeAt = docked ? 0 : MORPH_MS - OVERLAP_MS;
  const morphAt = docked ? OVERLAP_MS : 0;
  // The movement eases in AND out, because it starts from rest: the player
  // has just stopped climbing. `ease-out` alone leaves at full speed from a
  // standing start, which is a flinch. The fading group keeps `ease-out` —
  // opacity has no momentum to read.
  const fade = {
    transitionDuration: `${FADE_MS}ms`,
    transitionDelay: `${fadeAt}ms`,
  };
  const morph = {
    transitionDuration: `${MORPH_MS}ms`,
    transitionDelay: `${morphAt}ms`,
  };

  if (engine.failed) {
    return (
      <div className={cn("rounded-xl border border-border bg-card p-4", className)}>
        <p className="text-sm text-foreground">
          The recording didn&apos;t load.
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          The questions still work — you can answer what you already know and
          try the audio again.
        </p>
        <button
          type="button"
          onClick={engine.retry}
          className="mt-3 inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors duration-fast hover:bg-surface-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <RotateCcw className="size-3.5" aria-hidden />
          Try again
        </button>
      </div>
    );
  }

  // The transport — a nudge, the button, a nudge — measured rather than
  // assumed, because a config that forbids seeking has no nudges and the
  // cluster is then the button alone. Full size it is centred by half its own
  // width; docked it sits at the gutter, and the waveform starts where it
  // ends.
  const cluster =
    m.play + 16 + (config.allowSeek ? 2 * m.nudge : 0);
  const rightOf =
    (config.allowSpeed && m.speed > 0 ? m.speed + 6 : 0) +
    (config.allowSeek ? m.skip + 8 : 0) +
    m.clockW;

  const here = marked.length > 0 ? marked[currentPart(marked, engine.atMs)] : null;
  const row = {
    top: small ? DOCK.waveTop : bigRowTop,
    height: m.rowH,
    ...morph,
  };

  /**
   * Whether the skip button has anything to do, and is therefore lit.
   *
   * A listening paper is largely dead air — the twenty and thirty second
   * stretches where a candidate is meant to be reading ahead — and on a
   * second pass through the same paper that is time spent watching a
   * playhead. Nobody goes looking for a control to fix that, so the control
   * asks: it catches the light a few seconds before the quiet arrives and
   * STAYS lit for the whole of it. Going dark at the moment the silence
   * started was the one moment it had a job.
   *
   * Off entirely when the reader has set every silence to be skipped anyway
   * — there is then never a silence to sit through — and off between times,
   * when a press could only be a click that did nothing.
   */
  const offering = !!engine.skippable && !engine.autoSkip;

  return (
    // The shell: a constant block of space, and the thing that sticks. It is
    // transparent and inert — the paper below it is visible and clickable
    // through the part the shrunken card has left behind.
    <div
      className={cn("pointer-events-none relative", className)}
      style={{ height: shellH }}
    >
      <div
        className={cn(
          // Not `overflow-hidden`: the play button fills its row, and its
          // focus ring is drawn outside the border box. The one child that
          // actually collapses clips itself.
          "pointer-events-auto absolute inset-x-0 top-0 mx-auto border border-border ease-in-out",
          // Its size animates, so the browser is told outright that nothing
          // inside it can affect the layout of anything outside — already
          // true (it is absolutely positioned) but worth saying where the
          // work happens sixty times a second. Layout only, not paint: paint
          // containment and `backdrop-filter` are a pairing not worth finding
          // out about the hard way, and the glass matters more than the hint.
          "[contain:layout]",
          "transition-[height,max-width,background-color,border-radius,box-shadow]",
          "motion-reduce:transition-none",
          // Landed, it dresses as one of the header's islands: same corner,
          // same lift, same frost. The paper goes on scrolling underneath it,
          // which is the only reason glass means anything here — a pane over
          // a flat colour is just a flat colour.
          //
          // `docked` and not `small`: the frost is about being IN the header
          // band among the other islands. A settled player is a card sitting
          // below the band on the page's own colour, and glass there would be
          // a pane over a flat colour — which is a flat colour, drawn the
          // expensive way.
          docked
            ? "rounded-2xl bg-background/70 shadow-sm backdrop-blur-md supports-[backdrop-filter]:bg-background/60"
            : "rounded-xl bg-card",
        )}
        style={{
          height: small ? PLAYER_DOCK_H : bigH,
          // A ceiling rather than `none`, so the narrowing is a transition and
          // not a jump. The column is 768 wide, so 1024 is "as wide as it
          // goes".
          maxWidth: docked ? dockW : 1024,
          ...morph,
        }}
      >
        {/* The recording. Across the top full size; docked, it travels down
            into the row and settles into the gap the controls leave. It is
            the reason the shrunken player is worth keeping at all: somebody
            four screens down can still see how much is left. */}
        <div
          className="absolute ease-in-out transition-[top,left,right,height] motion-reduce:transition-none"
          style={{
            top: m.waveTop,
            height: m.waveH,
            left: small ? PAD + cluster + GAP : PAD,
            right: small ? PAD + rightOf + GAP : PAD,
            ...morph,
          }}
        >
          <Waveform
            peaks={shape.peaks}
            atMs={engine.atMs}
            lengthMs={engine.lengthMs}
            parts={small ? undefined : marked}
            onSeek={config.allowSeek ? engine.seekTo : undefined}
          />
        </div>

        {/* The part names. The one thing with no smaller version — a label
            over a strip 80px wide would name nothing — so it goes first and
            comes back last. */}
        <div
          className="absolute overflow-hidden ease-out transition-[top,height,opacity] motion-reduce:transition-none"
          style={{
            top: small ? DOCK.waveTop : partsTop,
            height: small ? 0 : partsH,
            left: PAD,
            right: PAD,
            opacity: small ? 0 : 1,
            ...fade,
          }}
        >
          <PartStrip
            parts={marked}
            lengthMs={engine.lengthMs}
            atMs={engine.atMs}
            onJump={
              config.allowSeek
                ? (part) => engine.seekTo(part.startMs)
                : undefined
            }
            className="h-full"
          />
        </div>

        {/* The clock is the one piece that crosses the card: out on the left
            full size, in beside the speed once the row closes up. Placed off
            the far edge with a `calc()`, because the near one moves. */}
        <div
          className="absolute flex items-center overflow-hidden ease-in-out transition-[top,left,width,height] motion-reduce:transition-none"
          style={{
            ...row,
            width: m.clockW,
            left: small
              ? `calc(100% - ${PAD + rightOf}px)`
              : PAD,
          }}
        >
          {/* Clipped by the box above rather than truncated: an ellipsis here
              would appear the moment the part name goes transparent, and the
              reader would watch "1:52 / 6:06" grow a tail for no reason. */}
          <span className="font-mono text-sm whitespace-nowrap tabular-nums text-foreground">
            {fmtClock(engine.atMs)}
            <span className="text-muted-foreground">
              {" / "}
              {fmtClock(engine.lengthMs)}
            </span>
            {/* Which part is playing, beside the clock rather than only in the
                strip: at a glance the answer to "where am I" is a time and a
                part, and they belong in the same breath. */}
            {here && (
              <span
                className="text-muted-foreground ease-out transition-opacity motion-reduce:transition-none"
                style={{ opacity: small ? 0 : 1, ...fade }}
              >
                {" · "}
                {here.label}
              </span>
            )}
          </span>
        </div>

        {/* The transport. Centred full size — the arrangement every music
            player has, because it is the one a hand reaches into without
            looking — and at the gutter once the row closes up. Centred by
            half its own width rather than by a grid, so the same two numbers
            carry it the whole way across.

            No flex gap in here: the spacing belongs to the button that never
            leaves, or a gap left standing where a control used to be would
            push play off centre by half of it. */}
        <div
          className="absolute flex items-center ease-in-out transition-[top,left,margin-left,height] motion-reduce:transition-none"
          style={{
            ...row,
            left: small ? PAD : "50%",
            marginLeft: small ? 0 : -cluster / 2,
          }}
        >
          {config.allowSeek && (
            <Control
              label={`Back ${NUDGE_MS / 1000} seconds`}
              onClick={() => engine.nudge(-NUDGE_MS)}
              width={m.nudge}
              height={m.ctl}
              gap={0}
              duration={MORPH_MS}
              delay={morphAt}
            >
              <Undo2 className="size-3.5" aria-hidden />
              <Nudged label={m.nudgeLabel} style={morph} />
            </Control>
          )}
          <PlayButton
            engine={engine}
            size={m.play}
            style={{ marginLeft: 8, marginRight: 8, ...morph }}
          />
          {config.allowSeek && (
            <Control
              label={`Forward ${NUDGE_MS / 1000} seconds`}
              onClick={() => engine.nudge(NUDGE_MS)}
              width={m.nudge}
              height={m.ctl}
              gap={0}
              duration={MORPH_MS}
              delay={morphAt}
            >
              <Nudged label={m.nudgeLabel} style={morph} />
              <Redo2 className="size-3.5" aria-hidden />
            </Control>
          )}
        </div>

        {/* Set once and forgotten, so they sit out of the way — and they are
            the only group that never moves. */}
        <div
          className="absolute flex items-center justify-end gap-1.5 ease-in-out transition-[top,height] motion-reduce:transition-none"
          style={{ ...row, right: PAD }}
        >
          {config.allowSpeed && (
            <Control
              label="Playback speed"
              onClick={engine.cycleSpeed}
              width={m.speed}
              height={m.ctl}
              gone={small}
              duration={FADE_MS}
              delay={fadeAt}
            >
              {engine.speed}×
            </Control>
          )}
          {/* An action, not a switch: it skips THIS silence, the one happening
              or about to. Skipping all of them, for a reader who has decided
              that is how they work, is a setting rather than a second control
              on a player that is already full — see
              PREFERENCES.skipSilence. */}
          {config.allowSeek && (
            <Control
              label={
                engine.autoSkip
                  ? "Silences are skipped for you"
                  : offering
                    ? "Skip this silence"
                    : "Nothing to skip just here"
              }
              onClick={engine.skipAhead}
              disabled={!offering}
              shine={offering}
              width={m.skip}
              height={m.ctl}
              duration={MORPH_MS}
              delay={morphAt}
            >
              <FastForward className="size-3.5" aria-hidden />
              <Collapsing width={m.skipLabel} style={morph}>
                Skip
              </Collapsing>
            </Control>
          )}
        </div>
      </div>
    </div>
  );
}

/** A word inside a control that goes when the player shrinks, leaving the
 *  icon behind. Collapsed by width rather than removed, so the mark it sits
 *  beside never jumps. */
function Collapsing({
  width,
  style,
  children,
}: {
  width: number;
  style?: React.CSSProperties;
  children: React.ReactNode;
}) {
  return (
    <span
      className="overflow-hidden ease-in-out transition-[width] motion-reduce:transition-none"
      style={{ width, ...style }}
    >
      {children}
    </span>
  );
}

/** The "3s" on a nudge button. */
function Nudged({
  label,
  style,
}: {
  label: number;
  style?: React.CSSProperties;
}) {
  return (
    <Collapsing width={label} style={style}>
      {NUDGE_MS / 1000}s
    </Collapsing>
  );
}

function PlayButton({
  engine,
  size,
  style,
}: {
  engine: AudioEngine;
  size: number;
  style?: React.CSSProperties;
}) {
  const { playing, config } = engine;
  // With pausing forbidden the button stays visible and goes inert rather
  // than disappearing mid-play: a control that vanishes under the cursor
  // reads as a bug, not as a rule.
  const inert = playing ? !config.allowPause : !engine.canPlay;
  const mark = Math.round(size * 0.4);
  const glyph = { width: mark, height: mark, ...style };
  return (
    <button
      type="button"
      onClick={engine.toggle}
      aria-label={playing ? "Pause" : "Play"}
      title={
        playing
          ? config.allowPause
            ? "Pause"
            : "The recording plays through"
          : engine.finished && !config.allowReplay
            ? "The recording plays once"
            : "Play"
      }
      style={{ width: size, height: size, ...style }}
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground ease-in-out",
        "transition-[width,height,opacity] motion-reduce:transition-none",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card focus-visible:outline-none",
        inert && "pointer-events-none opacity-40",
      )}
    >
      {/* Filled, not outlined. A hollow triangle is a drawing of a play
          button; a solid one is a play button, and at this size the outline
          was the thinnest thing on the card.

          The mark scales with the circle, or a forty-four pixel one and a
          twenty-four pixel one end up with the same glyph in them and one of
          the two looks wrong. */}
      {playing ? (
        <Pause fill="currentColor" style={glyph} aria-hidden />
      ) : (
        <Play
          fill="currentColor"
          className="translate-x-px"
          style={glyph}
          aria-hidden
        />
      )}
    </button>
  );
}

/**
 * One control, at a width it is told.
 *
 * The width is a prop rather than the button's own business because the
 * waveform's docked padding is worked out from these numbers — the strip
 * lands in the gap the controls leave, so something has to know how wide that
 * gap is. `gone` collapses one to nothing and takes its gap with it, so a
 * control that has left leaves no hole where it was.
 */
function Control({
  label,
  onClick,
  on,
  width,
  height,
  gone,
  shine,
  disabled,
  gap = 6,
  duration,
  delay,
  children,
}: {
  label: string;
  onClick: () => void;
  on?: boolean;
  width: number;
  height: number;
  gone?: boolean;
  /** Catch the light — a control asking to be used. See `.shine` in
   *  globals.css. */
  shine?: boolean;
  /** Nothing for it to do. Really disabled rather than dimmed and clickable:
   *  a control that answers a press by doing nothing is worse than one that
   *  says it cannot. */
  disabled?: boolean;
  /** The row's own gap, cancelled when this control collapses so nothing is
   *  left standing where it was. Zero where the row has no gap. */
  gap?: number;
  /** The beat this control belongs to. */
  duration: number;
  delay: number;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-pressed={on}
      aria-hidden={gone}
      disabled={disabled}
      tabIndex={gone ? -1 : undefined}
      title={label}
      style={{
        width,
        height,
        opacity: gone ? 0 : 1,
        // Cancels the row's own gap, so nothing is left standing where the
        // control was.
        marginLeft: gone ? -gap : 0,
        // Two clocks on one element: the shape follows the beat this control
        // belongs to, and hover stays at the interface's own speed. A colour
        // that took a quarter of a second to answer the pointer would feel
        // broken to fix a problem nobody has.
        transitionDuration: `${duration}ms, ${duration}ms, ${duration}ms, ${duration}ms, 100ms, 100ms`,
        transitionDelay: `${delay}ms, ${delay}ms, ${delay}ms, ${delay}ms, 0ms, 0ms`,
      }}
      className={cn(
        "flex shrink-0 items-center justify-center gap-1 overflow-hidden rounded-md font-mono text-xs whitespace-nowrap ease-out",
        "transition-[width,opacity,margin-left,height,background-color,color] motion-reduce:transition-none",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        gone && "pointer-events-none",
        on
          ? "bg-primary/10 text-primary"
          : "bg-surface-sunken text-muted-foreground",
        !disabled && !on && "hover:bg-surface-hover hover:text-foreground",
        // The ground stays neutral: only the type takes the accent, so this
        // can never be mistaken for a switch that is on.
        shine && !on && "shine text-primary",
        disabled && "opacity-40",
      )}
    >
      {children}
    </button>
  );
}
