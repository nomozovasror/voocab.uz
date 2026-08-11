import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { CircleQuestionMark, Loader2 } from "lucide-react";
import { useStudioCrumbs } from "@/components/studio/breadcrumbs";
import { toast } from "@/lib/toast";
import { getErrorMessage } from "@/lib/api";
import { timeAgo } from "@/lib/time";
import { listeningApi } from "@/features/listening/api";
import { useAudioAsset, useListeningMaterial } from "@/features/listening/queries";
import {
  answerMarks,
  checkMarks,
  findAnswerOccurrences,
  type AnswerOccurrence,
} from "@/features/listening/marks";
import {
  docFromGroup,
  docGaps,
  docPublishIssues,
  docToGroup,
  isDocEmpty,
  isGroupPersistable,
  newDoc,
  type DocBlock,
} from "@/features/listening/form-syntax";
import {
  AudioEditorPane,
  type AudioEditorHandle,
  type MarkRange,
} from "@/features/listening/components/AudioEditorPane";
import { QuestionFormEditor } from "@/features/listening/components/QuestionFormEditor";
import { FormHelpCard } from "@/features/listening/components/FormHelpCard";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { PartsPicker } from "@/features/listening/components/PartsPicker";
import { ANSWER_RUBRICS } from "@/features/listening/rubric";
import type {
  AnswerRubric,
  AudioSegment,
  Visibility,
} from "@/features/listening/types";

// Parts 2 and 3 (map/plan labelling, MCQ/matching) don't have an authorable
// question type yet — only form_completion exists. Their questions can still
// be authored as form completion; the section just carries a note that it's
// the only type available there.
const UNSUPPORTED_TYPICAL_TYPE_ORDER_INDICES = new Set([1, 2]);
const UNSUPPORTED_TYPICAL_TYPE_NOTE =
  "only form completion is available here — map/plan labelling and multiple choice/matching aren't built yet.";

// The structure is fixed at creation by the picker (§1): a single part
// (Part 1 or Part 4) trims the shared recording to its range; a full test
// has no trimming at all — the four parts are purely question groupings
// over one recording that already runs them in sequence.
function hasPartRange(parts: PartState[]): boolean {
  return parts.length === 1;
}

interface PartState {
  /** Stable identity for UI + in-flight autosave tracking, independent of
   *  whether the part has a server id yet. `order_index` is unique per
   *  material (server-enforced), so it doubles as the key. */
  key: string;
  partId: string | null;
  orderIndex: number;
  title: string;
  audioStartMs: number | null;
  audioEndMs: number | null;
  groupId: string | null;
  instructions: string;
  wordLimit: number | null;
  rubric: AnswerRubric | null;
  doc: DocBlock[];
}

interface EditorState {
  materialId: string | null;
  title: string;
  visibility: Visibility;
  audioAssetId: string | null;
  audioUrl: string | null;
  durationMs: number | null;
  parts: PartState[];
}

const EMPTY_STATE: EditorState = {
  materialId: null,
  title: "",
  visibility: "private",
  audioAssetId: null,
  audioUrl: null,
  durationMs: null,
  parts: [],
};

const AUTOSAVE_DELAY_MS = 1500;

function newPart(orderIndex: number): PartState {
  return {
    key: String(orderIndex),
    partId: null,
    orderIndex,
    title: `Part ${orderIndex + 1}`,
    audioStartMs: null,
    audioEndMs: null,
    groupId: null,
    instructions: "",
    wordLimit: null,
    rubric: null,
    doc: newDoc(),
  };
}

export default function StudioListeningEditorPage() {
  const { id: routeId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data: existing, isLoading: hydrating } = useListeningMaterial(routeId);
  const loadedRef = useRef(false);

  const [state, setState] = useState<EditorState>(() => ({
    ...EMPTY_STATE,
    materialId: routeId ?? null,
  }));
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const [saving, setSaving] = useState(false);
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [badPartKey, setBadPartKey] = useState<string | null>(null);
  // Sections are stacked vertically now (no part switcher) — publish
  // validation failures scroll the offending section into view instead.
  const partSectionRefs = useRef<Record<string, HTMLDivElement | null>>({});

  // Client-side clamping in AudioEditorPane should make this unreachable in
  // practice, but if a part-range save error still arrives, never surface
  // the raw server field name — humanize it and show it right by the part
  // block instead of the generic top banner (§ review: fix the cause, not
  // the symptom; no toast system here, that's a separate project task).
  const partSaveError = useMemo(() => {
    if (!saveError) return null;
    return /audio_start_ms|audio_end_ms/i.test(saveError)
      ? "a part's end must be after its start — adjust the times below."
      : null;
  }, [saveError]);
  // Re-renders every 30s purely so the "saved Xm ago" trace stays fresh
  // without the author having to do anything.
  const [, forceTick] = useState(0);

  // Trail is rendered by the layout header. Declared here (before any early
  // return) so the hook order stays stable across loading/loaded renders.
  useStudioCrumbs([
    { label: "listening", to: "/studio/listening" },
    {
      label: state.materialId
        ? state.title.trim() || "untitled listening"
        : "new",
    },
  ]);

  const audioPaneRef = useRef<AudioEditorHandle>(null);
  // Marking where an answer is said spans both panes: the gap is in the right
  // one, the moment is in the left. The page holds the half-finished request
  // — which gap asked — until the transcript answers it.
  const [picking, setPicking] = useState(false);
  const [suggestions, setSuggestions] = useState<AnswerOccurrence[]>([]);
  const pendingMark = useRef<((range: MarkRange) => void) | null>(null);
  const transcriptRef = useRef<AudioSegment[]>([]);

  const requestMark = useCallback(
    (answers: string[], apply: (range: MarkRange) => void) => {
      const target = audioPaneRef.current?.pickTarget();
      if (!target) return;
      if (target.kind === "selection" || target.kind === "playhead") {
        apply(target.range);
        return;
      }
      pendingMark.current = apply;
      // The answer is already written down and the transcript already knows
      // when it was said, so offer the timestamp instead of asking the author
      // to go and find it. Only ever offered — the wrong line is easy to make
      // when a word is said twice, so the choice stays theirs.
      setSuggestions(findAnswerOccurrences(transcriptRef.current, answers));
      setPicking(true);
    },
    [],
  );

  const cancelMark = useCallback(() => {
    pendingMark.current = null;
    setSuggestions([]);
    setPicking(false);
  }, []);
  const saveTimerRef = useRef<number | undefined>(undefined);
  const savingRef = useRef(false);
  const rerunNeededRef = useRef(false);

  const update = useCallback((patch: Partial<EditorState>) => {
    setState((prev) => ({ ...prev, ...patch }));
  }, []);

  const updatePart = useCallback((key: string, patch: Partial<PartState>) => {
    setState((prev) => ({
      ...prev,
      parts: prev.parts.map((p) => (p.key === key ? { ...p, ...patch } : p)),
    }));
  }, []);

  // --- Hydrate from the author endpoint (existing material only) ----------
  useEffect(() => {
    if (!existing || loadedRef.current) return;
    loadedRef.current = true;
    const parts: PartState[] = existing.parts.map((p) => {
      const group = p.question_groups[0];
      const doc = group
        ? docFromGroup(group.config.template, group.questions)
        : newDoc();
      return {
        key: String(p.order_index),
        partId: p.id,
        orderIndex: p.order_index,
        title: p.title,
        audioStartMs: p.audio_start_ms,
        audioEndMs: p.audio_end_ms,
        groupId: group?.id ?? null,
        instructions: group?.instructions ?? "",
        wordLimit: group?.word_limit ?? null,
        rubric: group?.config.answer_rubric ?? null,
        doc,
      };
    });
    setState({
      materialId: existing.id,
      title: existing.title,
      visibility: existing.visibility,
      audioAssetId: existing.audio_asset_id,
      audioUrl: existing.audio_url,
      durationMs: existing.duration_ms,
      parts,
    });
  }, [existing]);

  // --- Picker (brand-new material only, before any part is chosen). The
  // structure is fixed from here on — no add/remove-part in the editor. -----
  const handlePick = (orderIndices: number[]) => {
    update({ parts: orderIndices.map(newPart) });
  };

  // --- Autosave -------------------------------------------------------------
  // ensure material -> for each part, ensure/PATCH it + its question group ->
  // PATCH material. Each part is saved independently (its own try/catch) so
  // one part's validation failure never drops another part's edits — errors
  // are collected per part and surfaced together, naming the part.

  const runSave = useCallback(async () => {
    if (savingRef.current) {
      rerunNeededRef.current = true;
      return;
    }
    savingRef.current = true;
    setSaving(true);
    try {
      const s = stateRef.current;
      const effectiveTitle = s.title.trim() || "untitled listening";
      let materialId = s.materialId;

      if (!materialId) {
        const created = await listeningApi.materials.create({
          title: effectiveTitle,
          type: "listening",
          visibility: s.visibility,
          audio_asset_id: s.audioAssetId,
        });
        materialId = created.id;
        update({
          materialId,
          audioUrl: created.audio_url,
          durationMs: created.duration_ms,
        });
        navigate(`/studio/listening/${materialId}`, { replace: true });
      }

      // Re-read after the material-create await: the author may have edited
      // while it was in flight.
      const partsSnapshot = stateRef.current.parts;
      const persisted = new Map<string, { partId: string; groupId: string | null }>();
      const partErrors: string[] = [];

      for (const part of partsSnapshot) {
        const label = part.title.trim() || `Part ${part.orderIndex + 1}`;
        try {
          let partId = part.partId;
          if (!partId) {
            const created = await listeningApi.parts.create(materialId, {
              order_index: part.orderIndex,
              title: label,
              audio_start_ms: part.audioStartMs,
              audio_end_ms: part.audioEndMs,
            });
            partId = created.id;
          } else {
            await listeningApi.parts.update(partId, {
              title: label,
              audio_start_ms: part.audioStartMs,
              audio_end_ms: part.audioEndMs,
            });
          }

          let groupId = part.groupId;
          if (isGroupPersistable(part.doc, part.instructions)) {
            const { template, questions } = docToGroup(part.doc);
            const payload = {
              type: "form_completion" as const,
              instructions: part.instructions.trim(),
              word_limit: part.wordLimit,
              config: { template, answer_rubric: part.rubric },
              questions,
            };
            if (!groupId) {
              const group = await listeningApi.questionGroups.create(partId, payload);
              groupId = group.id;
            } else {
              await listeningApi.questionGroups.update(groupId, payload);
            }
          }

          persisted.set(part.key, { partId, groupId });
        } catch (e) {
          partErrors.push(`${label}: ${getErrorMessage(e)}`);
        }
      }

      // Merge persisted ids back in without clobbering edits made to other
      // fields (or other parts) while the loop above was awaiting network
      // calls — only patch what this save round actually touched.
      setState((prev) => ({
        ...prev,
        parts: prev.parts.map((p) => {
          const ids = persisted.get(p.key);
          return ids ? { ...p, partId: ids.partId, groupId: ids.groupId } : p;
        }),
      }));

      const updated = await listeningApi.materials.update(materialId, {
        title: effectiveTitle,
        visibility: s.visibility,
        audio_asset_id: s.audioAssetId,
      });
      update({ audioUrl: updated.audio_url, durationMs: updated.duration_ms });

      setLastSavedAt(new Date());
      setSaveError(partErrors.length > 0 ? partErrors.join(" · ") : null);
      void qc.invalidateQueries({ queryKey: ["studio-listening"] });
      void qc.invalidateQueries({ queryKey: ["studio-stats"] });
    } catch (e) {
      setSaveError(getErrorMessage(e));
    } finally {
      savingRef.current = false;
      setSaving(false);
      if (rerunNeededRef.current) {
        rerunNeededRef.current = false;
        window.clearTimeout(saveTimerRef.current);
        saveTimerRef.current = window.setTimeout(() => void runSave(), 0);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reads live state via stateRef by design
  }, [navigate, qc, update]);

  const scheduleSave = useCallback(
    (immediate = false) => {
      window.clearTimeout(saveTimerRef.current);
      if (immediate) void runSave();
      else saveTimerRef.current = window.setTimeout(() => void runSave(), AUTOSAVE_DELAY_MS);
    },
    [runSave],
  );

  // Any edit to persisted fields schedules a debounced save. Skipped while
  // still hydrating an existing material, and while a brand-new material
  // hasn't been through the picker yet (nothing to save — no parts).
  useEffect(() => {
    if (!loadedRef.current && routeId) return;
    if (!routeId && state.parts.length === 0) return;
    scheduleSave(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- state fields are the deps, scheduleSave is stable
  }, [state.title, state.visibility, state.audioAssetId, state.parts]);

  useEffect(() => () => window.clearTimeout(saveTimerRef.current), []);

  useEffect(() => {
    const t = window.setInterval(() => forceTick((v) => v + 1), 30_000);
    return () => window.clearInterval(t);
  }, []);

  // --- Keyboard: space play/pause (never while typing), ⌘s/Ctrl+s save ----
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      const isTyping =
        tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target?.isContentEditable;

      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        scheduleSave(true);
        return;
      }
      if (e.code === "Space" && !isTyping) {
        e.preventDefault();
        audioPaneRef.current?.togglePlay();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [scheduleSave]);

  // --- Actions --------------------------------------------------------------

  const handleUpload = async (file: File) => {
    setUploading(true);
    try {
      const asset = await listeningApi.uploadAudio(file);
      update({ audioAssetId: asset.asset_id });
      scheduleSave(true);
    } catch (e) {
      toast(getErrorMessage(e));
    } finally {
      setUploading(false);
    }
  };

  // Every part that has questions needs instructions + a non-empty answer
  // per gap; the material needs at least one part with at least one gap.
  // "Has questions" = the author has touched it (typed instructions or a
  // label/answer) — an untouched, still-empty part is fine to leave alone.
  const validateForPublish = (): {
    ok: boolean;
    message?: string;
    badPartKey?: string;
  } => {
    const s = stateRef.current;
    let anyPartHasGap = false;

    for (const part of s.parts.slice().sort((a, b) => a.orderIndex - b.orderIndex)) {
      const label = part.title.trim() || `Part ${part.orderIndex + 1}`;
      const touched =
        part.instructions.trim() !== "" || !isDocEmpty(part.doc);
      if (!touched) continue;

      if (!part.instructions.trim()) {
        return { ok: false, message: `${label}: add instructions before publishing.`, badPartKey: part.key };
      }
      // The syntax module owns what "complete" means, so the publish gate and
      // the editor's own inline warnings can never disagree.
      const issues = docPublishIssues(part.doc);
      if (issues.length > 0) {
        return {
          ok: false,
          message: `${label} — ${issues[0]}`,
          badPartKey: part.key,
        };
      }
      anyPartHasGap = true;
    }

    if (!anyPartHasGap) {
      return { ok: false, message: "add at least one part with at least one gap before publishing." };
    }
    return { ok: true };
  };

  const handlePublish = () => {
    const v = validateForPublish();
    if (!v.ok) {
      setPublishError(v.message ?? "can't publish yet.");
      setBadPartKey(v.badPartKey ?? null);
      // No part to switch to anymore — everything's on one page, so scroll
      // the offending section into view instead.
      if (v.badPartKey) {
        partSectionRefs.current[v.badPartKey]?.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
      }
      return;
    }
    setPublishError(null);
    setBadPartKey(null);
    update({ visibility: "public" });
    scheduleSave(true);
  };

  const handleDraft = () => {
    setPublishError(null);
    setBadPartKey(null);
    update({ visibility: "private" });
    scheduleSave(true);
  };

  const hasAudioEverAttached = !!state.audioAssetId;
  // The transcript is already loaded for the player; reading it here (the
  // same cached query) lets the editor say whether each mark actually holds.
  const { data: audioAsset } = useAudioAsset(state.audioAssetId ?? undefined);
  const transcriptSegments = useMemo(
    () => (audioAsset?.transcript_status === "ready" ? audioAsset.segments : []),
    [audioAsset],
  );
  // Read through a ref: the mark request is a callback held across renders,
  // and a stale transcript would search yesterday's words.
  transcriptRef.current = transcriptSegments;

  const marksForTranscript = useMemo(
    () => state.parts.flatMap((part) => answerMarks(part.doc)),
    [state.parts],
  );
  const markChecksByPart = useMemo(() => {
    const byPart = new Map<string, ReturnType<typeof checkMarks>>();
    for (const part of state.parts) {
      byPart.set(part.key, checkMarks(part.doc, transcriptSegments));
    }
    return byPart;
  }, [state.parts, transcriptSegments]);

  // Gaps with an answer written: the nearest thing to evidence that the
  // author has understood how this is done, which is when the help retires.
  const authoredGapCount = useMemo(
    () =>
      state.parts.reduce(
        (total, part) =>
          total +
          docGaps(part.doc).filter((g) => g.answers.some((a) => a.trim()))
            .length,
        0,
      ),
    [state.parts],
  );

  // The help card lives at the foot of the questions pane and steps aside as
  // soon as the form is tall enough to reach it: past that point the space is
  // the author's, and a card floating over their work is in the way.
  const questionsPaneRef = useRef<HTMLDivElement>(null);
  const sectionsRef = useRef<HTMLDivElement>(null);
  const [helpFits, setHelpFits] = useState(true);
  // Dismissing the card is permanent until asked for again, so there has to be
  // an "again" — otherwise the × is a one-way door.
  const [helpForced, setHelpForced] = useState(false);

  useEffect(() => {
    const pane = questionsPaneRef.current;
    const sections = sectionsRef.current;
    if (!pane || !sections) return;

    // ~120px covers the card plus the gap above it. Measuring the card itself
    // would be circular — it isn't rendered when it doesn't fit.
    const measure = () =>
      setHelpFits(
        pane.clientHeight === 0 ||
          sections.offsetHeight + 120 <= pane.clientHeight,
      );

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(pane);
    observer.observe(sections);
    return () => observer.disconnect();
  }, []);

  const sortedParts = state.parts.slice().sort((a, b) => a.orderIndex - b.orderIndex);
  const singlePart = hasPartRange(state.parts) ? state.parts[0] : null;
  const showPicker = !routeId && state.parts.length === 0;

  if (routeId && hydrating && !loadedRef.current) {
    return (
      <div className="mx-auto w-full max-w-[75rem] px-2 py-16 text-center font-mono text-sm text-muted-foreground">
        <Loader2 className="mx-auto mb-2 size-5 animate-spin" aria-hidden />
        loading material…
      </div>
    );
  }

  if (showPicker) {
    return (
      // Dismissing without choosing means there's nothing to edit, so it
      // returns to the list rather than leaving an empty editor behind.
      <Dialog
        open
        onOpenChange={(open) => {
          if (!open) navigate("/studio/listening");
        }}
      >
        <DialogContent className="modal-stagger gap-6 p-6 font-mono duration-200 sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle className="text-center text-lg font-medium">
              New listening material
            </DialogTitle>
            <DialogDescription className="text-center text-xs">
              Which part are you authoring?
            </DialogDescription>
          </DialogHeader>
          <PartsPicker onPick={handlePick} />
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col font-mono">
      {/* Top bar — title and the actions that apply to it share one line. No
          rule under it: the layout header already draws one just above, and
          the audio label's rule follows shortly after. */}
      <div className="flex flex-none flex-wrap items-center justify-between gap-3 pt-1 pb-2">
        <input
          type="text"
          value={state.title}
          onChange={(e) => update({ title: e.target.value })}
          placeholder="untitled listening"
          aria-label="Material title"
          className="min-w-0 flex-1 border-b-2 border-transparent bg-transparent pb-1 text-xl font-medium text-foreground placeholder:text-muted-foreground hover:border-border focus:border-primary focus:outline-none"
        />

        <div className="flex shrink-0 items-center gap-3.5">
          <span className="text-xs text-muted-foreground">
            {saving ? "saving…" : lastSavedAt ? `saved ${timeAgo(lastSavedAt.toISOString())}` : ""}
          </span>
          <button
            type="button"
            onClick={() => setHelpForced((v) => !v)}
            title="How to build the form"
            aria-label="How to build the form"
            className="flex size-6 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-foreground"
          >
            <CircleQuestionMark className="size-4" aria-hidden />
          </button>
          <button
            type="button"
            onClick={handleDraft}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            draft
          </button>
          <button
            type="button"
            onClick={handlePublish}
            className="rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground transition-[filter] hover:brightness-[1.06]"
          >
            publish
          </button>
        </div>
      </div>

      {(publishError || (saveError && !partSaveError)) && (
        <p className="flex-none pb-2 text-xs text-destructive">
          {publishError ?? saveError}
        </p>
      )}

      {/* Panes. min-h-0 caps the grid at the height left over from the title
          bar; without it the row sizes to its tallest child and pushes the
          editor past the bottom of the screen, which is what put a second
          scrollbar on the page. */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-8 md:grid-cols-[minmax(340px,46%)_1fr]">
        {/* The player column fills the grid row rather than a hand-computed
            slice of the viewport. The old calc() guessed at everything above
            it — header, padding, title bar — guessed high, and overflowed the
            page by the difference. `h-full` can't be wrong about it.
            Only from md up: on a narrow screen the panes stack and the page
            scrolls normally. */}
        <div className="min-w-0 md:h-full md:min-h-0 md:border-r md:border-border md:pr-8">
          <AudioEditorPane
            ref={audioPaneRef}
            audioAssetId={state.audioAssetId}
            audioUrl={state.audioUrl}
            durationMsHint={state.durationMs}
            hasPartRange={!!singlePart}
            picking={picking}
            onPickSegment={(range) => {
              // Applied as it goes, and picking stays open: the author may
              // still shift-click another line to reach the rest of the
              // phrase, and closing here would make that a fresh start.
              pendingMark.current?.(range);
            }}
            onCancelPick={cancelMark}
            marks={marksForTranscript}
            suggestions={suggestions}
            partNumber={singlePart ? singlePart.orderIndex + 1 : null}
            partAudioStart={singlePart?.audioStartMs ?? null}
            partAudioEnd={singlePart?.audioEndMs ?? null}
            onSetPartStart={
              singlePart
                ? (ms) => updatePart(singlePart.key, { audioStartMs: Math.round(ms) })
                : undefined
            }
            onSetPartEnd={
              singlePart
                ? (ms) => updatePart(singlePart.key, { audioEndMs: Math.round(ms) })
                : undefined
            }
            onResetPart={
              singlePart
                ? () => updatePart(singlePart.key, { audioStartMs: null, audioEndMs: null })
                : undefined
            }
            onUpload={handleUpload}
            uploading={uploading}
            partError={partSaveError}
          />
        </div>

        {/* Questions — one section per part, stacked top to bottom. A
            single-part material still gets a heading, so the layout reads
            consistently whether there's one part or four.

            This pane owns its scroll from md up, so however many parts it
            grows to it never scrolls the page out from under the player. */}
        <div
          ref={questionsPaneRef}
          className="scrollbar-quiet min-w-0 md:flex md:min-h-0 md:flex-col md:overflow-y-auto md:pr-1"
        >
          <div ref={sectionsRef} className="space-y-8">
          {sortedParts.map((part) => {
            const label = part.title.trim() || `Part ${part.orderIndex + 1}`;
            return (
              <div
                key={part.key}
                ref={(el) => {
                  partSectionRefs.current[part.key] = el;
                }}
              >
                <QuestionFormEditor
                  doc={part.doc}
                  onChange={(doc) => updatePart(part.key, { doc })}
                  instructions={part.instructions}
                  onInstructionsChange={(instructions) =>
                    updatePart(part.key, { instructions })
                  }
                  rubric={part.rubric}
                  onRubricChange={(rubric) =>
                    updatePart(part.key, {
                      rubric,
                      // The old numeric field is kept in step so nothing that
                      // still reads it starts disagreeing with the sentence.
                      wordLimit:
                        ANSWER_RUBRICS.find((r) => r.value === rubric)?.words ??
                        null,
                    })
                  }
                  partLabel={label}
                  showIssues={badPartKey === part.key}
                  markChecks={markChecksByPart.get(part.key)}
                  onMarkAudio={hasAudioEverAttached ? requestMark : undefined}
                  disabled={!hasAudioEverAttached}
                  note={
                    UNSUPPORTED_TYPICAL_TYPE_ORDER_INDICES.has(part.orderIndex)
                      ? UNSUPPORTED_TYPICAL_TYPE_NOTE
                      : undefined
                  }
                />
              </div>
            );
          })}

          </div>

          {/* The little the editor has to teach, at the foot of it, retiring
              once it's been learned. The keys that used to sit here loose are
              inside it — one of them, "tab: next gap", was never implemented
              and is gone rather than restated. */}
          <FormHelpCard
            authoredGaps={authoredGapCount}
            visible={helpFits}
            forceOpen={helpForced}
            onDismiss={() => setHelpForced(false)}
          />
        </div>
      </div>
    </div>
  );
}
