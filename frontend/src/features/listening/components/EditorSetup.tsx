import { useState, type CSSProperties } from "react";
import { AudioLines, Check, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatClock } from "@/features/studio/format";
import { AudioDropzone } from "@/features/listening/components/AudioDropzone";
import { PartsPicker } from "@/features/listening/components/PartsPicker";
import { QuestionTypeChoices } from "@/features/listening/components/QuestionTypeChoices";
import {
  QUESTION_TYPE_ICON,
  QUESTION_TYPE_LABEL,
} from "@/features/listening/parts";
import type {
  AudioTranscriptStatus,
  QuestionGroupType,
} from "@/features/listening/types";

/**
 * Opening a listening material, one question at a time.
 *
 * A blank editor asks for everything at once: which parts, a recording, a
 * kind of question, the questions themselves. But it is not an "at once"
 * job — the parts decide what kinds of question are even on offer, and the
 * recording has to exist before anything can be written against it. The
 * editor used to show all of it anyway, greyed out, which said "not yet"
 * without saying what would make it yet.
 *
 * So the order is made explicit and asked for in one panel, a step at a
 * time: the parts, the recording, then what each part asks. Only ever at the
 * start — the moment anything has been written, the editor is what the author
 * came for and the steps do not come back.
 *
 * Lives inside a DialogContent and owns its title, because the title is one
 * of the things that changes between steps.
 */

export interface SetupChoice {
  /** The group this settles. */
  groupKey: string;
  partLabel: string;
  types: QuestionGroupType[];
  /** What the part is known for that isn't built yet. */
  note?: string;
  /** Already settled, either by the author just now or because the part only
   *  takes one kind. */
  chosen: QuestionGroupType | null;
}

export type SetupStep = "parts" | "audio" | "types";

interface EditorSetupProps {
  step: SetupStep;
  /** Whether this material's opening has a type step at all. A lone Part 1
   *  takes one kind of question, so it is never asked — and a rail with a
   *  step that never happens is a rail that lies. */
  hasTypeStep: boolean;
  /** The step is on its way out; the next one takes its place after this. */
  leaving: boolean;

  /** 0-based order indices to seed as parts. */
  onPickParts: (orderIndices: number[]) => void;

  // The recording.
  onUpload: (file: File) => void;
  uploading: boolean;
  /** Uploaded, and now being attached to the material. */
  attaching: boolean;
  /** Whatever stopped it, so the step isn't a dead end with a spinner on it. */
  error?: string | null;
  recording: {
    title: string | null;
    durationMs: number | null;
    status: AudioTranscriptStatus | null;
  } | null;

  // What each part asks.
  choices: SetupChoice[];
  onChoose: (groupKey: string, type: QuestionGroupType) => void;
  /** Straight into the editor, leaving the parts unsettled. They keep their
   *  inline chooser there, so this loses nothing. */
  onSkip: () => void;
}

const STEP_TITLE: Record<SetupStep, string> = {
  parts: "What are you building?",
  audio: "Add the recording",
  types: "What does each part ask?",
};

const STEP_BLURB: Record<SetupStep, string> = {
  parts:
    "One part on its own, or the whole test. This is settled here — parts can't be added to a material later.",
  audio:
    "Everything else is written against it — the transcript it comes back with, the answers, and the moment each one is said.",
  types:
    "One set of questions per part to begin with. More can be added to any part once the editor opens.",
};

/** What the recording is doing, in the words the transcript pane uses. */
function transcriptLine(status: AudioTranscriptStatus | null): string {
  if (status === "ready") return "transcript ready";
  if (status === "failed") return "transcript failed — the editor can still be used";
  return "transcribing…";
}

/** A part whose question is answered: what it says, and the way back to the
 *  question. Compact, so the ones still to answer are the ones with weight. */
function SettledChoice({
  partLabel,
  chosen,
  onChange,
}: {
  partLabel: string;
  chosen: QuestionGroupType;
  onChange?: () => void;
}) {
  const Icon = QUESTION_TYPE_ICON[chosen];
  return (
    <div className="setup-settled flex items-center gap-3 rounded-lg border border-border px-4 py-3">
      <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
        <Check className="size-3" aria-hidden />
      </span>
      <span className="text-sm text-foreground">{partLabel}</span>
      <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
        <Icon className="size-3.5 shrink-0" aria-hidden />
        <span className="truncate">{QUESTION_TYPE_LABEL[chosen]}</span>
      </span>
      {onChange && (
        <button
          type="button"
          onClick={onChange}
          className="ml-auto shrink-0 text-[11px] text-muted-foreground underline underline-offset-2 transition-colors hover:text-foreground"
        >
          change
        </button>
      )}
    </div>
  );
}

function StepRail({
  steps,
  current,
}: {
  steps: { key: SetupStep; label: string }[];
  current: SetupStep;
}) {
  const at = steps.findIndex((s) => s.key === current);
  return (
    <ol className="flex items-center justify-center gap-3 text-[11px]">
      {steps.map((s, i) => {
        const done = i < at;
        const here = i === at;
        return (
          <li key={s.key} className="flex items-center gap-3">
            <span
              className={cn(
                "flex items-center gap-2 transition-colors duration-300",
                here
                  ? "text-foreground"
                  : done
                    ? "text-muted-foreground"
                    : "text-muted-foreground/50",
              )}
            >
              <span
                className={cn(
                  "flex size-5 items-center justify-center rounded-full border transition-colors duration-300",
                  done
                    ? "border-primary bg-primary/15 text-primary"
                    : here
                      ? "border-primary text-primary"
                      : "border-border",
                )}
              >
                {done ? <Check className="size-3" aria-hidden /> : i + 1}
              </span>
              {s.label}
            </span>
            {i < steps.length - 1 && (
              <span
                aria-hidden
                className={cn(
                  "h-px w-10 transition-colors duration-300",
                  done ? "bg-primary/50" : "bg-border",
                )}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}

export function EditorSetup({
  step,
  hasTypeStep,
  leaving,
  onPickParts,
  onUpload,
  uploading,
  attaching,
  error,
  recording,
  choices,
  onChoose,
  onSkip,
}: EditorSetupProps) {
  // Rows the author has asked to change their mind about. Local, because
  // nothing about the material changes by reopening the question — only by
  // answering it differently.
  const [reopened, setReopened] = useState<string[]>([]);

  const steps: { key: SetupStep; label: string }[] = [
    { key: "parts", label: "parts" },
    { key: "audio", label: "recording" },
    ...(hasTypeStep ? [{ key: "types" as const, label: "questions" }] : []),
  ];

  return (
    <>
      <StepRail steps={steps} current={step} />

      {/* Keyed on the step so the entrance replays: this is one panel working
          through its questions, not three panels in a row. */}
      <div key={step} className="setup-step" data-leaving={leaving}>
        <DialogTitle className="setup-rise mb-1 text-center text-lg font-medium">
          {STEP_TITLE[step]}
        </DialogTitle>
        <DialogDescription
          className="setup-rise mb-6 text-center text-xs leading-relaxed"
          style={{ "--i": 1 } as CSSProperties}
        >
          {STEP_BLURB[step]}
        </DialogDescription>

        {step === "parts" && (
          <div className="setup-rise" style={{ "--i": 2 } as CSSProperties}>
            <PartsPicker onPick={onPickParts} />
          </div>
        )}

        {step === "audio" && (
          <div className="setup-rise" style={{ "--i": 2 } as CSSProperties}>
            <AudioDropzone
              size="stage"
              onUpload={onUpload}
              busy={uploading || attaching}
              busyLabel={uploading ? "uploading…" : "attaching it…"}
            />
            {error && (
              <p className="mt-3 text-center text-xs text-warning">{error}</p>
            )}
          </div>
        )}

        {step === "types" && (
          <>
            {recording && (
              <div
                className="setup-rise mb-5 flex items-center gap-2.5 rounded-lg bg-foreground/5 px-3.5 py-2.5 text-[11px] text-muted-foreground"
                style={{ "--i": 2 } as CSSProperties}
              >
                {recording.status === "ready" ||
                recording.status === "failed" ? (
                  <AudioLines className="size-3.5 shrink-0" aria-hidden />
                ) : (
                  <Loader2
                    className="size-3.5 shrink-0 animate-spin text-primary"
                    aria-hidden
                  />
                )}
                <span className="min-w-0 truncate text-foreground">
                  {recording.title ?? "recording attached"}
                </span>
                {recording.durationMs != null && (
                  <span>{formatClock(recording.durationMs)}</span>
                )}
                <span className="ml-auto shrink-0">
                  {transcriptLine(recording.status)}
                </span>
              </div>
            )}

            <div className="space-y-3">
              {choices.map((choice, index) => {
                const fixed = choice.types.length === 1;
                return (
                  <div
                    key={choice.groupKey}
                    className="setup-rise"
                    style={{ "--i": index + 3 } as CSSProperties}
                  >
                    {choice.chosen === null ||
                    reopened.includes(choice.groupKey) ? (
                      <div className="rounded-lg border border-dashed border-border p-4">
                        <div className="mb-3 flex items-baseline gap-2">
                          <h4 className="text-sm font-medium text-foreground">
                            {choice.partLabel}
                          </h4>
                        </div>
                        <QuestionTypeChoices
                          types={choice.types}
                          onChoose={(type) => {
                            setReopened((keys) =>
                              keys.filter((k) => k !== choice.groupKey),
                            );
                            onChoose(choice.groupKey, type);
                          }}
                        />
                        {choice.note && (
                          <p className="mt-3 text-[11px] text-muted-foreground">
                            {choice.note}
                          </p>
                        )}
                      </div>
                    ) : (
                      <SettledChoice
                        // Re-keyed on the answer so the confirmation replays
                        // when the author changes it.
                        key={choice.chosen}
                        partLabel={choice.partLabel}
                        chosen={choice.chosen}
                        // Only where there was a choice to make. Part 1 takes
                        // one kind of question, so "change" would open a menu
                        // of the thing it already is.
                        onChange={
                          fixed
                            ? undefined
                            : () =>
                                setReopened((keys) => [
                                  ...keys,
                                  choice.groupKey,
                                ])
                        }
                      />
                    )}
                  </div>
                );
              })}
            </div>

            <div
              className="setup-rise mt-6 text-center"
              style={{ "--i": choices.length + 3 } as CSSProperties}
            >
              <button
                type="button"
                onClick={onSkip}
                className="text-[11px] text-muted-foreground underline underline-offset-2 transition-colors hover:text-foreground"
              >
                decide in the editor
              </button>
            </div>
          </>
        )}
      </div>
    </>
  );
}
