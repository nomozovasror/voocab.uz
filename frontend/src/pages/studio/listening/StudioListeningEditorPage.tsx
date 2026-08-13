import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CircleQuestionMark, Loader2 } from "lucide-react";
import { useStudioHeader } from "@/components/studio/header-slots";
import { PublishCelebration } from "@/components/studio/PublishCelebration";
import {
  publishMilestone,
  type PublishMilestone,
} from "@/features/studio/milestones";
import {
  PublishBar,
  type PublishRequirement,
} from "@/features/listening/components/PublishBar";
import { dismissToast, toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { ApiError, getErrorMessage } from "@/lib/api";
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
  newId,
  type DocBlock,
} from "@/features/listening/form-syntax";
import {
  choiceIssues,
  choiceQuestionsFromApi,
  choiceQuestionsToApi,
  isChoiceGroupEmpty,
  newChoiceQuestions,
  type ChoiceIssue,
  type ChoiceQuestion,
} from "@/features/listening/mcq";
import { questionRangeLabel } from "@/features/listening/numbering";
import {
  missingTypeNote,
  questionTypesForPart,
} from "@/features/listening/parts";
import {
  AudioEditorPane,
  type AudioEditorHandle,
  type MarkRange,
} from "@/features/listening/components/AudioEditorPane";
import { AddGroupButton } from "@/features/listening/components/BuilderTools";
import { ChoiceGroupEditor } from "@/features/listening/components/ChoiceGroupEditor";
import { GroupTypeChooser } from "@/features/listening/components/GroupTypeChooser";
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
import { ANSWER_RUBRICS, deriveRubric } from "@/features/listening/rubric";
import type {
  AnswerRubric,
  AudioSegment,
  QuestionGroupIn,
  QuestionGroupType,
  Visibility,
} from "@/features/listening/types";

// The structure is fixed at creation by the picker (§1): a single part
// (Part 1 or Part 4) trims the shared recording to its range; a full test
// has no trimming at all — the four parts are purely question groupings
// over one recording that already runs them in sequence.
function hasPartRange(parts: PartState[]): boolean {
  return parts.length === 1;
}

/** What every group has, whichever kind it is. */
interface GroupStateBase {
  /** Stable identity for UI + in-flight autosave tracking, independent of
   *  whether the group has a server id yet. */
  key: string;
  groupId: string | null;
  instructions: string;
}

interface FormGroupState extends GroupStateBase {
  type: "form_completion";
  wordLimit: number | null;
  rubric: AnswerRubric | null;
  doc: DocBlock[];
}

interface ChoiceGroupState extends GroupStateBase {
  type: "multiple_choice";
  questions: ChoiceQuestion[];
}

/** A group whose kind hasn't been settled yet. It exists so the question can
 *  be asked in the part it is about — Part 2 has no map labelling to offer,
 *  Part 1 has nothing to ask — rather than once, in a dialog, for a whole
 *  test. Nothing about it is sent anywhere until it becomes one of the two
 *  above. */
interface PendingGroupState extends GroupStateBase {
  type: null;
}

type GroupState = FormGroupState | ChoiceGroupState | PendingGroupState;

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
  /** In the order they are asked. A part is one or more of these: "Questions
   *  1–6, form completion" then "Questions 7–10, multiple choice". */
  groups: GroupState[];
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
/** One toast for the state of saving, replaced rather than repeated. */
const SAVE_TOAST_ID = "listening-editor-save";

// What gets sent for each resource, in one place. Hydration records these as
// "already on the server" and the save round compares against that record, so
// the two must build byte-identical payloads — computing them separately is
// how the comparison would quietly start reporting a difference on every
// round and send everything anyway.

function materialSignature(
  title: string,
  visibility: Visibility,
  audioAssetId: string | null,
): string {
  return JSON.stringify([title, visibility, audioAssetId]);
}

function partLabel(part: PartState): string {
  return part.title.trim() || `Part ${part.orderIndex + 1}`;
}

/** Concrete rather than `PartUpdate`: with every field optional, a spread of
 *  it can't stand in for the create payload, which requires the title. */
function partPayload(part: PartState): {
  title: string;
  audio_start_ms: number | null;
  audio_end_ms: number | null;
} {
  return {
    title: partLabel(part),
    audio_start_ms: part.audioStartMs,
    audio_end_ms: part.audioEndMs,
  };
}

/** The group payload, or null when there is nothing the API would accept.
 *
 *  The two kinds draw the line in different places, and both lines are the
 *  server's. A form can't be stored with a gap nobody can answer, so a
 *  half-written one waits. A multiple-choice group can: a question with no
 *  text and no answer marked is exactly what a group looks like a second
 *  after it was added, and holding it back until it was finished would mean
 *  autosaving nothing for as long as it takes to write four questions. */
function groupPayload(group: GroupState): QuestionGroupIn | null {
  if (group.type === null) return null;
  if (!group.instructions.trim()) return null;

  if (group.type === "multiple_choice") {
    // The builder keeps at least one question, and the API insists on it.
    if (group.questions.length === 0) return null;
    return {
      type: "multiple_choice",
      instructions: group.instructions.trim(),
      config: {},
      questions: choiceQuestionsToApi(group.questions),
    };
  }

  if (!isGroupPersistable(group.doc, group.instructions)) return null;
  const { template, questions } = docToGroup(group.doc);
  return {
    type: "form_completion",
    instructions: group.instructions.trim(),
    word_limit: group.wordLimit,
    config: {
      template,
      // Left on auto, the rubric the answers imply is stored: the take page
      // has no answers to work it out from.
      answer_rubric: group.rubric ?? deriveRubric(group.doc),
    },
    questions,
  };
}

/** The part's saved groups, in order, as one string to compare against. Only
 *  the ones the server knows about: a group with no id yet has no place in an
 *  order the server could be told. */
function groupOrderSignature(part: PartState): string {
  return part.groups
    .map((group) => group.groupId)
    .filter(Boolean)
    .join(",");
}

/** How many questions a group holds, whichever kind it is — which is what
 *  numbers everything after it. A group with no kind holds none, so the
 *  numbering runs straight through it. */
function groupQuestionCount(group: GroupState): number {
  if (group.type === "form_completion") return docGaps(group.doc).length;
  if (group.type === "multiple_choice") return group.questions.length;
  return 0;
}

/** Whether the author has put anything of their own into this group. */
function isGroupEmpty(group: GroupState): boolean {
  if (group.type === "form_completion") return isDocEmpty(group.doc);
  if (group.type === "multiple_choice") return isChoiceGroupEmpty(group.questions);
  return true;
}

function newGroup(type: QuestionGroupType | null): GroupState {
  const base = { key: newId(), groupId: null, instructions: "" };
  if (type === null) return { ...base, type };
  return type === "multiple_choice"
    ? { ...base, type, questions: newChoiceQuestions() }
    : { ...base, type, wordLimit: null, rubric: null, doc: newDoc() };
}

/** A part's first group. Where the part has only one kind of question it can
 *  hold — Part 1 is a completion task and nothing else — that is what it
 *  gets, with nothing to answer first: a choice of one is a question not
 *  worth asking. */
function firstGroup(orderIndex: number): GroupState {
  const types = questionTypesForPart(orderIndex);
  return newGroup(types.length === 1 ? types[0] : null);
}

function newPart(orderIndex: number): PartState {
  return {
    key: String(orderIndex),
    partId: null,
    orderIndex,
    title: `Part ${orderIndex + 1}`,
    audioStartMs: null,
    audioEndMs: null,
    groups: [firstGroup(orderIndex)],
  };
}

/** Every group in the order it is asked, with the number its first question
 *  carries on the page. One walk of the material, since a group's numbering
 *  depends on everything before it — including groups in earlier parts. */
function groupRun(
  parts: PartState[],
): { part: PartState; group: GroupState; startNumber: number }[] {
  const run: { part: PartState; group: GroupState; startNumber: number }[] = [];
  let seen = 0;
  for (const part of parts.slice().sort((a, b) => a.orderIndex - b.orderIndex)) {
    for (const group of part.groups) {
      run.push({ part, group, startNumber: seen + 1 });
      seen += groupQuestionCount(group);
    }
  }
  return run;
}

/** What a group is called when it has to be named in a message: the part it
 *  is in, and the questions it covers. */
function groupLabel(part: PartState, group: GroupState, startNumber: number): string {
  const range = questionRangeLabel(startNumber - 1, groupQuestionCount(group));
  return range ? `${partLabel(part)} · ${range}` : partLabel(part);
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
  // What the save loop reads — never `state` itself, and never a render
  // behind it. A save started from an event handler (publish, an upload
  // finishing, ⌘S) runs before React has committed the edit that triggered
  // it, so a ref filled in from an effect still held the previous values:
  // publish saved `private`, an upload saved no audio, and both only came
  // right 1.5s later when the debounce caught up. Every write goes through
  // `commit`, which moves the ref first and the render after.
  const stateRef = useRef(state);
  const commit = useCallback((edit: (prev: EditorState) => EditorState) => {
    const next = edit(stateRef.current);
    // Returning the same object is how a no-op edit says so — React bails
    // out of the render, which is what keeps autosave from re-triggering
    // itself when it writes back what it just persisted.
    if (next === stateRef.current) return;
    stateRef.current = next;
    setState(next);
  }, []);

  const [saving, setSaving] = useState(false);
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);
  const [unsavedGroups, setUnsavedGroups] = useState<string[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  // The server's own refusal, which can name things the local checklist
  // can't know about. Shown on the publish button's list.
  const [publishError, setPublishError] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [milestone, setMilestone] = useState<PublishMilestone | null>(null);
  const [badGroupKey, setBadGroupKey] = useState<string | null>(null);
  // Sections are stacked vertically now (no part switcher) — publish
  // validation failures scroll the offending group into view instead.
  const groupSectionRefs = useRef<Record<string, HTMLDivElement | null>>({});

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

  // This page fills the header itself rather than leaving a trail there.
  // Claimed here — before any early return — so the hook order stays stable
  // across the loading and loaded renders.
  const Header = useStudioHeader(["lead", "actions"]);

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

  // The phrase highlighted in the transcript, remembered rather than read
  // when it's wanted: clicking into a field in the questions pane collapses
  // the window selection, so by the time the author reaches for it the
  // browser no longer knows what they had picked out. Only the transcript's
  // own selection changes it — including to nothing, when they click a line
  // — so working over here leaves it alone.
  const [transcriptSelection, setTranscriptSelection] = useState("");
  useEffect(() => {
    const onSelectionChange = () => {
      const picked = audioPaneRef.current?.selectedText();
      if (picked != null) setTranscriptSelection(picked);
    };
    document.addEventListener("selectionchange", onSelectionChange);
    return () =>
      document.removeEventListener("selectionchange", onSelectionChange);
  }, []);
  const saveTimerRef = useRef<number | undefined>(undefined);
  const savingRef = useRef(false);
  const rerunNeededRef = useRef(false);
  /** An edit is waiting out the debounce. Together with the two refs above,
   *  this is "the server does not have everything yet". */
  const pendingRef = useRef(false);
  const mountedRef = useRef(true);
  const inFlightRef = useRef<Promise<boolean> | null>(null);
  /** Whether the toast currently under SAVE_TOAST_ID is a failure of ours. */
  const errorToastRef = useRef(false);

  // --- Optimistic concurrency ---------------------------------------------
  // The material's version as this editor last saw it. Sent with every write;
  // the server answers 409 if the material has moved on, which is the whole
  // point — two windows open on the same material autosave over each other
  // otherwise, and the loser finds their work gone with nothing to explain it.
  const versionRef = useRef<number | null>(null);
  /** Set by a write whose reply says the material has gone back to draft. */
  const demotedRef = useRef(false);
  // Both, because the save loop reads it synchronously and the banner renders
  // from it.
  const conflictRef = useRef(false);
  const [conflict, setConflict] = useState(false);
  /** Request options carrying the version out and reading the new one back. */
  const versioned = useCallback(
    () => ({
      headers:
        versionRef.current == null
          ? undefined
          : { "X-Material-Version": String(versionRef.current) },
      onHeaders: (h: Headers) => {
        const next = h.get("X-Material-Version");
        if (next) versionRef.current = Number(next);
        // The server re-checks a public material after every write and puts
        // it back to draft when an edit leaves it unpublishable. Noted here
        // and acted on once the round is over, so the author isn't told
        // three times for one save.
        if (h.get("X-Material-Visibility") === "private") {
          demotedRef.current = true;
        }
      },
    }),
    [],
  );
  /** What the server last accepted, per resource. A save round compares
   *  against these and sends only what differs — a form edit is one request,
   *  not one per part plus the material. */
  const sentRef = useRef({
    material: "",
    parts: new Map<string, string>(),
    groups: new Map<string, string>(),
    /** Per part: the order its saved groups are in, as the server has them.
     *  Moving a group changes nothing about the groups themselves, so it
     *  would otherwise go unsent — every payload would still match. */
    order: new Map<string, string>(),
  });
  /** Groups the author has deleted that the server still has. Held here
   *  rather than acted on immediately so a delete goes out with the same
   *  debounce as everything else, and so one that fails can be retried on
   *  the next round instead of vanishing with the click. */
  const removedGroupsRef = useRef<string[]>([]);
  const hasPendingWork = () =>
    pendingRef.current || savingRef.current || rerunNeededRef.current;

  /** Returns the previous state untouched when the patch changes nothing, so
   *  React bails out of the render. Autosave writes what it just persisted
   *  back into state, and a new object every time — even an identical one —
   *  re-fires the effect that schedules the save. */
  const update = useCallback(
    (patch: Partial<EditorState>) => {
      commit((prev) => {
        const changed = (Object.keys(patch) as (keyof EditorState)[]).some(
          (key) => prev[key] !== patch[key],
        );
        return changed ? { ...prev, ...patch } : prev;
      });
    },
    [commit],
  );

  const updatePart = useCallback(
    (key: string, patch: Partial<PartState>) => {
      commit((prev) => ({
        ...prev,
        parts: prev.parts.map((p) => (p.key === key ? { ...p, ...patch } : p)),
      }));
    },
    [commit],
  );

  const updateGroup = useCallback(
    (key: string, edit: (group: GroupState) => GroupState) => {
      commit((prev) => ({
        ...prev,
        parts: prev.parts.map((part) => ({
          ...part,
          groups: part.groups.map((g) => (g.key === key ? edit(g) : g)),
        })),
      }));
    },
    [commit],
  );

  /** Applies an edit to a group's form against the freshest copy of it. The
   *  editor hands over the change rather than the result, so two edits landing
   *  between renders can't overwrite each other — which they did when Enter
   *  was held down: rows that had just been deleted came back. */
  const editGroupDoc = useCallback(
    (key: string, edit: (current: DocBlock[]) => DocBlock[]) => {
      updateGroup(key, (group) =>
        group.type === "form_completion"
          ? { ...group, doc: edit(group.doc) }
          : group,
      );
    },
    [updateGroup],
  );

  const editGroupQuestions = useCallback(
    (key: string, edit: (current: ChoiceQuestion[]) => ChoiceQuestion[]) => {
      updateGroup(key, (group) =>
        group.type === "multiple_choice"
          ? { ...group, questions: edit(group.questions) }
          : group,
      );
    },
    [updateGroup],
  );

  // --- Hydrate from the author endpoint (existing material only) ----------
  useEffect(() => {
    if (!existing || loadedRef.current) return;
    loadedRef.current = true;
    const parts: PartState[] = existing.parts.map((p) => ({
      key: String(p.order_index),
      partId: p.id,
      orderIndex: p.order_index,
      title: p.title,
      audioStartMs: p.audio_start_ms,
      audioEndMs: p.audio_end_ms,
      // A part with no groups at all is one the author emptied; it gets a
      // fresh form to write into rather than nothing to click.
      groups:
        p.question_groups.length > 0
          ? p.question_groups
              .slice()
              .sort((a, b) => a.order_index - b.order_index)
              .map((group): GroupState => {
                const base = {
                  key: newId(),
                  groupId: group.id,
                  instructions: group.instructions,
                };
                if (group.type === "multiple_choice") {
                  return {
                    ...base,
                    type: "multiple_choice",
                    questions: choiceQuestionsFromApi(group.questions),
                  };
                }
                // Anything else is read as a form: it is the only other type
                // that exists, and a type this build doesn't know is better
                // shown as its template than dropped.
                return {
                  ...base,
                  type: "form_completion",
                  wordLimit: group.word_limit,
                  rubric: group.config.answer_rubric ?? null,
                  doc: docFromGroup(group.config.template ?? "", group.questions),
                };
              })
          : [firstGroup(p.order_index)],
    }));
    versionRef.current = existing.version;
    // Everything just loaded is, by definition, what the server has. Recording
    // it here is what stops merely opening a material from PATCHing all of it
    // straight back: hydration lands in state, the autosave effect sees the
    // change and schedules a round like any other edit.
    sentRef.current = {
      material: materialSignature(
        existing.title,
        existing.visibility,
        existing.audio_asset_id,
      ),
      parts: new Map(
        parts.map((p) => [p.key, JSON.stringify(partPayload(p))]),
      ),
      groups: new Map(
        parts.flatMap((p) =>
          p.groups.flatMap((group) => {
            const forGroup = group.groupId ? groupPayload(group) : null;
            return forGroup
              ? [[group.key, JSON.stringify(forGroup)] as const]
              : [];
          }),
        ),
      ),
      order: new Map(parts.map((p) => [p.key, groupOrderSignature(p)])),
    };
    commit(() => ({
      materialId: existing.id,
      title: existing.title,
      visibility: existing.visibility,
      audioAssetId: existing.audio_asset_id,
      audioUrl: existing.audio_url,
      durationMs: existing.duration_ms,
      parts,
    }));
  }, [existing, commit]);

  // --- Picker (brand-new material only, before any part is chosen). The
  // structure is fixed from here on — no add/remove-part in the editor. -----
  const handlePick = (orderIndices: number[]) => {
    update({ parts: orderIndices.map(newPart) });
  };

  // --- Groups within a part -------------------------------------------------

  /** A new group, right after the one whose toolbar was used. A part is
   *  written top to bottom, so "after this one" is where the next set of
   *  questions goes; appending to the end would be wrong the moment a part
   *  has three of them. */
  const addGroup = useCallback(
    (partKey: string, afterKey: string | null, type: QuestionGroupType) => {
      const group = newGroup(type);
      commit((prev) => ({
        ...prev,
        parts: prev.parts.map((part) => {
          if (part.key !== partKey) return part;
          const at = afterKey
            ? part.groups.findIndex((g) => g.key === afterKey)
            : -1;
          const groups = part.groups.slice();
          groups.splice(at < 0 ? groups.length : at + 1, 0, group);
          return { ...part, groups };
        }),
      }));
    },
    [commit],
  );

  /** Settles what a group is. The key survives, so the autosave signatures
   *  and the section ref that were already keyed to it stay pointed at the
   *  same block — this is the same group answering a question, not a new
   *  one. There is nothing to unsettle it afterwards: an empty group is
   *  nothing to lose by deleting and adding the other kind, and one with
   *  work in it shouldn't be quietly emptied by a dropdown. */
  const chooseGroupType = useCallback(
    (groupKey: string, type: QuestionGroupType) => {
      updateGroup(groupKey, (group) =>
        group.type === null ? { ...newGroup(type), key: group.key } : group,
      );
    },
    [updateGroup],
  );

  const removeGroup = useCallback(
    (partKey: string, groupKey: string) => {
      const group = stateRef.current.parts
        .find((part) => part.key === partKey)
        ?.groups.find((g) => g.key === groupKey);
      // Queued rather than deleted here and now, so it goes out on the same
      // debounce as everything else and can be retried if it fails.
      if (group?.groupId) removedGroupsRef.current.push(group.groupId);
      sentRef.current.groups.delete(groupKey);
      commit((prev) => ({
        ...prev,
        parts: prev.parts.map((part) =>
          part.key === partKey
            ? { ...part, groups: part.groups.filter((g) => g.key !== groupKey) }
            : part,
        ),
      }));
    },
    [commit],
  );

  const moveGroup = useCallback(
    (partKey: string, groupKey: string, delta: number) => {
      commit((prev) => ({
        ...prev,
        parts: prev.parts.map((part) => {
          if (part.key !== partKey) return part;
          const index = part.groups.findIndex((g) => g.key === groupKey);
          const to = index + delta;
          if (index < 0 || to < 0 || to >= part.groups.length) return part;
          const groups = part.groups.slice();
          const [moved] = groups.splice(index, 1);
          groups.splice(to, 0, moved);
          return { ...part, groups };
        }),
      }));
    },
    [commit],
  );

  // --- Autosave -------------------------------------------------------------
  // ensure material -> for each part, ensure/PATCH it + its question group ->
  // PATCH material. Each part is saved independently (its own try/catch) so
  // one part's validation failure never drops another part's edits — errors
  // are collected per part and surfaced together, naming the part.

  /** Whether anything differs from what the server last accepted. Opening a
   *  material lands in state like any other change, so without this the
   *  editor started a save round on arrival — sending nothing, thanks to the
   *  per-resource comparison, but still flashing "saving…" and stamping
   *  "saved just now" over a material nobody had touched. */
  const hasUnsentChanges = useCallback(() => {
    const s = stateRef.current;
    if (!s.materialId) return true;
    if (removedGroupsRef.current.length > 0) return true;
    if (
      materialSignature(
        s.title.trim() || "untitled listening",
        s.visibility,
        s.audioAssetId,
      ) !== sentRef.current.material
    ) {
      return true;
    }
    return s.parts.some((part) => {
      if (!part.partId) return true;
      if (JSON.stringify(partPayload(part)) !== sentRef.current.parts.get(part.key)) {
        return true;
      }
      if (groupOrderSignature(part) !== sentRef.current.order.get(part.key)) {
        return true;
      }
      return part.groups.some((group) => {
        const forGroup = groupPayload(group);
        if (forGroup) {
          return (
            JSON.stringify(forGroup) !== sentRef.current.groups.get(group.key)
          );
        }
        // Nothing the API would take. That is either a group emptied out —
        // which means deleting the server's copy — or one the author has
        // left unfinished, which the save round has to look at so the status
        // line can say it isn't saved.
        //
        // Answering "nothing to do" here for an unfinished group is how
        // clearing the instructions on a saved one came to be lost in
        // silence: the round never ran, so the group was never listed as
        // unsaved, and "saved just now" stood over an edit the server had
        // never been told about.
        return Boolean(group.groupId) || groupQuestionCount(group) > 0;
      });
    });
  }, []);

  const doSave = useCallback(async (): Promise<boolean> => {
    // A conflict is not something to retry into: the material on the server
    // is no longer the one this editor was built from, so every further save
    // would be refused, and forcing them through would overwrite whatever the
    // other window wrote. Autosave stops until the page is reloaded.
    if (conflictRef.current) return false;
    pendingRef.current = false;
    // Nothing to do is a successful save, silently: no request, no spinner,
    // and no claim about when the material was last written.
    if (!hasUnsentChanges()) return true;
    savingRef.current = true;
    setSaving(true);
    let sentAnything = false;
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
        sentAnything = true;
        materialId = created.id;
        versionRef.current = created.version;
        // This editor is now the material's source of truth. Without saying
        // so, the route change below started a fetch of what was just
        // created, and hydration — still thinking it had never run — replaced
        // everything typed since with the server's copy. A title edited in
        // the seconds after creation simply reverted. It also gated autosave
        // off, so nothing typed in that window was saved at all.
        loadedRef.current = true;
        sentRef.current.material = materialSignature(
          effectiveTitle,
          s.visibility,
          s.audioAssetId,
        );
        update({
          materialId,
          audioUrl: created.audio_url,
          durationMs: created.duration_ms,
        });
        // Not when this save is the one flushing on the way out: the editor
        // is already gone, and pushing it a url would fight whatever the
        // author navigated to.
        if (mountedRef.current) {
          navigate(`/studio/listening/${materialId}`, { replace: true });
        }
      }

      // Groups the author deleted. Sent before anything else: the reorder
      // below tells the server the part's whole running order, and one that
      // still names a group being removed is an order the server refuses.
      // Taken off the queue as each one succeeds, so a failure is retried
      // rather than lost.
      const partErrors: string[] = [];
      /** A conflict is not a problem with one group: the material this editor
       *  was built from is gone, so every later request in the round would be
       *  refused too. It goes up to the round's own handler, which says so
       *  once and stops autosave — reported per group it would arrive as a
       *  list of failures with no explanation among them. */
      const rethrowConflict = (e: unknown) => {
        if (e instanceof ApiError && e.status === 409) throw e;
      };

      for (const groupId of removedGroupsRef.current.slice()) {
        try {
          await listeningApi.questionGroups.remove(groupId, versioned());
          sentAnything = true;
        } catch (e) {
          rethrowConflict(e);
          // Already gone is the outcome we wanted; anything else is worth
          // saying, and worth keeping in the queue.
          if (!(e instanceof ApiError && e.status === 404)) {
            partErrors.push(getErrorMessage(e));
            continue;
          }
        }
        removedGroupsRef.current = removedGroupsRef.current.filter(
          (id) => id !== groupId,
        );
      }

      // Re-read after the material-create await: the author may have edited
      // while it was in flight.
      const partsSnapshot = stateRef.current.parts;
      const persistedParts = new Map<string, string>();
      const persistedGroups = new Map<string, string | null>();
      // Groups holding questions the server can't be given yet — a gap with
      // no answer typed in, or missing instructions, both of which the API
      // rejects outright. Collected so the status line can stop claiming the
      // material is saved when part of it isn't.
      const unsaved: string[] = [];
      const numberedGroups = groupRun(partsSnapshot);
      const startNumberOf = new Map(
        numberedGroups.map((entry) => [entry.group.key, entry.startNumber]),
      );

      for (const part of partsSnapshot) {
        try {
          const forPart = partPayload(part);
          const partSignature = JSON.stringify(forPart);

          let partId = part.partId;
          const partIsNew = !partId;
          if (!partId) {
            const created = await listeningApi.parts.create(
              materialId,
              { order_index: part.orderIndex, ...forPart },
              versioned(),
            );
            partId = created.id;
            sentAnything = true;
            sentRef.current.parts.set(part.key, partSignature);
          } else if (sentRef.current.parts.get(part.key) !== partSignature) {
            // Only when it actually differs from what was last accepted.
            // Every round used to PATCH every part and every group whatever
            // had changed, so typing one letter into a form sent three
            // requests — one of them the whole question set.
            await listeningApi.parts.update(partId, forPart, versioned());
            sentAnything = true;
            sentRef.current.parts.set(part.key, partSignature);
          }
          persistedParts.set(part.key, partId);

          for (const group of part.groups) {
            const label = groupLabel(
              part,
              group,
              startNumberOf.get(group.key) ?? 1,
            );
            try {
              let groupId = group.groupId;
              const forGroup = groupPayload(group);
              if (forGroup) {
                const groupSignature = JSON.stringify(forGroup);
                if (!groupId) {
                  const created = await listeningApi.questionGroups.create(
                    partId,
                    forGroup,
                    versioned(),
                  );
                  groupId = created.id;
                  sentAnything = true;
                  sentRef.current.groups.set(group.key, groupSignature);
                } else if (
                  sentRef.current.groups.get(group.key) !== groupSignature
                ) {
                  await listeningApi.questionGroups.update(
                    groupId,
                    forGroup,
                    versioned(),
                  );
                  sentAnything = true;
                  sentRef.current.groups.set(group.key, groupSignature);
                }
              } else if (groupId && isGroupEmpty(group)) {
                // Cleared out. A group can't exist server-side with no
                // questions, so emptying it means deleting it — skipping the
                // write instead left the old questions in the database, and
                // they came back the next time the material was opened.
                await listeningApi.questionGroups.remove(groupId, versioned());
                groupId = null;
                sentAnything = true;
                sentRef.current.groups.delete(group.key);
              } else if (groupQuestionCount(group) > 0) {
                unsaved.push(label);
              }
              persistedGroups.set(group.key, groupId);
            } catch (e) {
              rethrowConflict(e);
              partErrors.push(`${label}: ${getErrorMessage(e)}`);
            }
          }

          // Last, and only once every group in this part has an id: the
          // server is told the whole running order, so it has to be an order
          // it can recognise.
          // `has` rather than `??`: a group this round deleted is recorded as
          // null, and falling back to the id it used to have would name a
          // group that no longer exists in the order — which the server
          // refuses outright, taking the rest of the round's work with it.
          const order = part.groups
            .map((group) =>
              persistedGroups.has(group.key)
                ? persistedGroups.get(group.key)
                : group.groupId,
            )
            .filter((id): id is string => Boolean(id));
          const signature = order.join(",");
          const known = sentRef.current.order.get(part.key);
          if (
            order.length === part.groups.length &&
            signature !== known &&
            // Not while a delete is still queued: the order below is the
            // local one, which no longer names the group the server still
            // has, and the server refuses an order that isn't the part's.
            // The retry that clears the queue will send it.
            removedGroupsRef.current.length === 0
          ) {
            if (known === undefined && partIsNew) {
              // The part was created a moment ago and its groups were POSTed
              // in this order, so the server appended them in it. Nothing to
              // correct — every new material would otherwise open with a
              // reorder that changed nothing.
              sentRef.current.order.set(part.key, signature);
            } else {
              await listeningApi.questionGroups.reorder(
                partId,
                order,
                versioned(),
              );
              sentAnything = true;
              sentRef.current.order.set(part.key, signature);
            }
          }
        } catch (e) {
          rethrowConflict(e);
          partErrors.push(`${partLabel(part)}: ${getErrorMessage(e)}`);
        }
      }

      // Merge persisted ids back in without clobbering edits made to other
      // fields (or other parts) while the loop above was awaiting network
      // calls — only patch what this save round actually touched.
      // Rebuilt only if an id actually arrived. Rebuilding regardless handed
      // back a new parts array on every save, and the autosave effect watches
      // that array — so each save scheduled the next one and the editor
      // PATCHed in a loop for as long as it was open.
      commit((prev) => {
        let changed = false;
        const parts = prev.parts.map((p) => {
          const partId = persistedParts.get(p.key) ?? p.partId;
          let groupsChanged = false;
          const groups = p.groups.map((group) => {
            if (!persistedGroups.has(group.key)) return group;
            const groupId = persistedGroups.get(group.key) ?? null;
            if (group.groupId === groupId) return group;
            groupsChanged = true;
            return { ...group, groupId };
          });
          if (p.partId === partId && !groupsChanged) return p;
          changed = true;
          return { ...p, partId, groups };
        });
        return changed ? { ...prev, parts } : prev;
      });

      // Read once more rather than reuse the opening snapshot: the loop above
      // awaited a request per part, and clicking publish during a save is
      // ordinary. Taken from the snapshot, that click was written a whole
      // debounce later — or not at all, if the author left first.
      const latest = stateRef.current;
      const materialTitle = latest.title.trim() || "untitled listening";
      const materialSig = materialSignature(
        materialTitle,
        latest.visibility,
        latest.audioAssetId,
      );
      if (materialSig !== sentRef.current.material) {
        const updated = await listeningApi.materials.update(
          materialId,
          {
            title: materialTitle,
            visibility: latest.visibility,
            audio_asset_id: latest.audioAssetId,
          },
          versioned(),
        );
        sentAnything = true;
        sentRef.current.material = materialSig;
        update({ audioUrl: updated.audio_url, durationMs: updated.duration_ms });
      }

      // Only when a write actually went out. A round that found nothing to
      // send hasn't saved anything, and saying it has is how the editor came
      // to greet every author with "saved just now".
      if (sentAnything) setLastSavedAt(new Date());
      if (demotedRef.current) {
        demotedRef.current = false;
        update({ visibility: "private" });
        toast({
          id: SAVE_TOAST_ID,
          title: "Back to draft",
          message:
            "That edit left the material unpublishable, so it isn't public any more. Publish again once it's complete.",
          kind: "warning",
          duration: 0,
        });
      }
      setUnsavedGroups(unsaved);
      setSaveError(partErrors.length > 0 ? partErrors.join(" · ") : null);
      // Only clears a failure that is now untrue. Dismissing unconditionally
      // meant the next save round — which runs a second after a publish and
      // usually has nothing to send — took the "Published" toast down with
      // it, since both share the id.
      if (errorToastRef.current) {
        errorToastRef.current = false;
        dismissToast(SAVE_TOAST_ID);
      }
      // Only when something actually moved. The studio list and the dashboard
      // counters don't change because a save round ran and found nothing to
      // do.
      if (sentAnything) {
        void qc.invalidateQueries({ queryKey: ["studio-listening"] });
        void qc.invalidateQueries({ queryKey: ["studio-stats"] });
      }
      return partErrors.length === 0;
    } catch (e) {
      setSaveError(getErrorMessage(e));
      errorToastRef.current = true;
      if (
        e instanceof ApiError &&
        e.status === 422 &&
        stateRef.current.visibility === "public"
      ) {
        // The server keeps the publishing requirements and refused. Held on
        // to, "public" would be re-sent every round for the same refusal, so
        // the editor goes back to what the material actually is and passes
        // the server's reasons on — they are more complete than the local
        // check, which is the point of having them there.
        update({ visibility: "private" });
        setPublishError(e.message);
        toast({
          id: SAVE_TOAST_ID,
          title: "Not published",
          message: e.message,
          kind: "warning",
          duration: 0,
        });
        return false;
      }
      if (e instanceof ApiError && e.status === 409) {
        conflictRef.current = true;
        setConflict(true);
        toast({
          id: SAVE_TOAST_ID,
          title: "Someone else edited this material",
          message:
            "Your changes since then aren't saved. Reload to pick up the latest version.",
          kind: "warning",
          duration: 0,
          action: { label: "Reload", onClick: () => window.location.reload() },
        });
        return false;
      }
      // The banner under the title bar is easy to miss while looking at the
      // form, and a save that failed is the one thing here worth
      // interrupting for. One id, so a run of failures replaces itself
      // rather than stacking a toast every debounce.
      toast({
        id: SAVE_TOAST_ID,
        title: "Not saved",
        message: getErrorMessage(e),
        kind: "error",
        duration: 0,
      });
      return false;
    } finally {
      savingRef.current = false;
      setSaving(false);
      if (rerunNeededRef.current) {
        rerunNeededRef.current = false;
        window.clearTimeout(saveTimerRef.current);
        saveTimerRef.current = window.setTimeout(() => void runSaveRef.current(), 0);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reads live state via stateRef by design
  }, [navigate, qc, update, commit, hasUnsentChanges]);

  /** One save at a time. A caller who arrives mid-save gets the promise of
   *  the one already running: its outcome is what "did my click land"
   *  means here, and the rerun queued in the `finally` above carries
   *  whatever it was too late to include. */
  const runSave = useCallback((): Promise<boolean> => {
    if (savingRef.current) {
      rerunNeededRef.current = true;
      return inFlightRef.current ?? Promise.resolve(false);
    }
    const promise = doSave();
    inFlightRef.current = promise;
    return promise;
  }, [doSave]);

  const scheduleSave = useCallback(
    (immediate = false): Promise<boolean> => {
      window.clearTimeout(saveTimerRef.current);
      if (immediate) return runSave();
      pendingRef.current = true;
      saveTimerRef.current = window.setTimeout(() => void runSave(), AUTOSAVE_DELAY_MS);
      return Promise.resolve(true);
    },
    [runSave],
  );

  // Held in a ref so the unmount flush below can stay on an empty dependency
  // list and still call the current one.
  const runSaveRef = useRef(runSave);
  runSaveRef.current = runSave;

  // Any edit to persisted fields schedules a debounced save. Skipped while
  // still hydrating an existing material, and while a brand-new material
  // hasn't been through the picker yet (nothing to save — no parts).
  useEffect(() => {
    if (!loadedRef.current && routeId) return;
    if (!routeId && state.parts.length === 0) return;
    // Something changed, so the server's last refusal may no longer be true.
    // Left standing it would keep the publish button on the checklist for
    // the rest of the session.
    setPublishError(null);
    scheduleSave(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- state fields are the deps, scheduleSave is stable
  }, [state.title, state.visibility, state.audioAssetId, state.parts]);

  // Leaving mid-debounce used to drop the edit: the timer was cleared on the
  // way out and nothing took its place, so up to a second and a half of
  // typing went with it. Now the pending save is flushed instead, and closing
  // the tab outright — where there is no time to flush anything — is
  // challenged by the browser.
  useEffect(() => {
    // Set on the way in, not just cleared on the way out: StrictMode mounts,
    // tears down and mounts again in development, and a flag only ever
    // cleared would stay false for the rest of the session — taking the
    // post-create navigate below with it.
    mountedRef.current = true;

    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (!hasPendingWork()) return;
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      window.clearTimeout(saveTimerRef.current);
      mountedRef.current = false;
      if (pendingRef.current) void runSaveRef.current();
    };
  }, []);

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

  // Every group the author has started needs instructions and finished
  // questions; the material needs at least one question somewhere. "Started"
  // = they have typed something into it — an untouched, still-empty group is
  // fine to leave alone.
  const validateForPublish = (): {
    ok: boolean;
    message?: string;
    badGroupKey?: string;
  } => {
    const s = stateRef.current;
    let anyQuestions = false;

    // The same requirements the server keeps (app/services/publishing.py).
    // Checked here too so the author hears it from the page they are on,
    // pointing at the group that needs work — but the server is the
    // authority, and its refusal is what actually holds.
    const title = s.title.trim();
    if (!title || title.toLowerCase() === "untitled listening") {
      return { ok: false, message: "give the material a title before publishing." };
    }
    if (!s.audioAssetId) {
      return { ok: false, message: "add the audio recording before publishing." };
    }

    for (const { part, group, startNumber } of groupRun(s.parts)) {
      const label = groupLabel(part, group, startNumber);
      const started = group.instructions.trim() !== "" || !isGroupEmpty(group);
      if (!started) continue;

      if (!group.instructions.trim()) {
        return {
          ok: false,
          message: `${label}: add instructions before publishing.`,
          badGroupKey: group.key,
        };
      }
      // The syntax and mcq modules own what "complete" means, so the publish
      // gate and the editor's own inline warnings can never disagree.
      const issue =
        group.type === "form_completion"
          ? docPublishIssues(group.doc, startNumber - 1)[0]
          : group.type === "multiple_choice"
            ? choiceIssues(group.questions, startNumber - 1)[0]?.message
            : // A group still asking what it is has nothing to be wrong
              // about — `started` above has already let it through.
              undefined;
      if (issue) {
        return { ok: false, message: `${label} — ${issue}`, badGroupKey: group.key };
      }
      if (groupQuestionCount(group) > 0) anyQuestions = true;
    }

    if (!anyQuestions) {
      return { ok: false, message: "add at least one question before publishing." };
    }
    return { ok: true };
  };

  // Publishing is the one deliberate, consequential thing on this page, and
  // it used to happen in silence — the only sign was a "saved" timestamp that
  // ticks over on its own anyway. Both directions now say what they did, and
  // both wait for the save rather than announcing an outcome they don't have.
  const handlePublish = async () => {
    const v = validateForPublish();
    if (!v.ok) {
      // The checklist in the publish button has already said this; all that
      // is left is to take the author to the group that needs the work.
      setBadGroupKey(v.badGroupKey ?? null);
      if (v.badGroupKey) {
        groupSectionRefs.current[v.badGroupKey]?.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
      }
      return;
    }
    setPublishError(null);
    setBadGroupKey(null);
    setPublishing(true);
    update({ visibility: "public" });
    const ok = await scheduleSave(true);
    setPublishing(false);
    if (!ok) return;

    // How many the author has out there now. Counted here rather than tracked
    // as it goes: it is one request, only at the moment of publishing, and it
    // can't drift from the truth the way a running total would. When the
    // achievements section arrives this is the number it will own.
    let milestone: PublishMilestone | null = null;
    try {
      const mine = await listeningApi.materials.list("mine");
      milestone = publishMilestone(
        mine.filter((m) => m.visibility === "public").length,
      );
    } catch {
      // The material is published either way; missing the count is not worth
      // telling the author about.
    }

    if (milestone) {
      setMilestone(milestone);
      return;
    }
    // Every other publish gets an ordinary confirmation. Confetti on all of
    // them would stop meaning anything by the third.
    toast({
      id: SAVE_TOAST_ID,
      title: "Published",
      message: "Anyone with the link can take this material now.",
      kind: "success",
    });
  };

  const handleDraft = async () => {
    setPublishError(null);
    setBadGroupKey(null);
    setPublishing(true);
    update({ visibility: "private" });
    const ok = await scheduleSave(true);
    setPublishing(false);
    if (ok) {
      toast({
        id: SAVE_TOAST_ID,
        title: "Back to draft",
        message: "Only you can see this material now.",
        kind: "info",
      });
    }
  };

  /** The publishing requirements as a checklist, so they can be seen before
   *  the button is pressed rather than reported one at a time afterwards.
   *  Same rules as validateForPublish and as the server's publish_blockers —
   *  this is the reading of them the author actually looks at. */
  const publishRequirements = useMemo((): PublishRequirement[] => {
    const title = state.title.trim();
    const run = groupRun(state.parts);

    const gaps = run.flatMap(({ group }) =>
      group.type === "form_completion" ? docGaps(group.doc) : [],
    );
    const answered = gaps.filter((g) => g.answers.some((a) => a.trim()));
    const unmarked = answered.filter((g) => g.replayStartMs == null);

    const choiceGroups = run.filter(
      ({ group }) => group.type === "multiple_choice",
    );
    const choiceProblems: ChoiceIssue[] = choiceGroups.flatMap(
      ({ group, startNumber }) =>
        group.type === "multiple_choice"
          ? choiceIssues(group.questions, startNumber - 1)
          : [],
    );
    const unwritten = choiceProblems.filter((i) => i.kind !== "answer");
    const unanswered = choiceProblems.filter((i) => i.kind === "answer");

    const totalQuestions = run.reduce(
      (total, { group }) => total + groupQuestionCount(group),
      0,
    );
    const missingInstructions = run
      .filter(
        ({ group }) =>
          groupQuestionCount(group) > 0 && !group.instructions.trim(),
      )
      .map(({ part, group, startNumber }) =>
        groupLabel(part, group, startNumber),
      );

    const requirements: PublishRequirement[] = [
      {
        label: "Give it a title",
        done: !!title && title.toLowerCase() !== "untitled listening",
      },
      { label: "Add the recording", done: !!state.audioAssetId },
      {
        label: "Write the instructions",
        done: missingInstructions.length === 0,
        detail: missingInstructions.join(", "),
      },
      { label: "Add at least one question", done: totalQuestions > 0 },
    ];

    // Only where there is one to be about: a material with no multiple
    // choice in it shouldn't be told about a requirement it can't fail.
    if (choiceGroups.length > 0) {
      requirements.push({
        label: "Finish every choice question",
        done: unwritten.length === 0,
        detail: unwritten.length
          ? `${unwritten.length} missing text or options`
          : undefined,
      });
    }

    const missingAnswers = gaps.length - answered.length + unanswered.length;
    requirements.push({
      label: "Answer every question",
      done: totalQuestions > 0 && missingAnswers === 0,
      detail: missingAnswers > 0 ? `${missingAnswers} still empty` : undefined,
    });

    // Gaps only, and only where there are gaps: a choice question is answered
    // from the whole of what was said rather than from one phrase in it, so
    // there is often no single moment to point a reviewer at. Listed for a
    // material that can't fail it, it would be a requirement that never goes
    // green however finished the material is.
    if (gaps.length > 0) {
      requirements.push({
        label: "Link every answer to the audio",
        done: answered.length > 0 && unmarked.length === 0,
        detail: unmarked.length
          ? `${unmarked.length} not linked yet`
          : undefined,
      });
    }

    return requirements;
  }, [state.title, state.audioAssetId, state.parts]);

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

  /** Every group in the order it is asked, with the number it starts at. One
   *  walk, reused by the render, the marks and the help card — computing it
   *  in each of them is how the three would come to disagree. */
  const run = useMemo(() => groupRun(state.parts), [state.parts]);

  const marksForTranscript = useMemo(
    () =>
      run.flatMap(({ group, startNumber }) =>
        group.type === "form_completion"
          ? answerMarks(group.doc, startNumber - 1)
          : [],
      ),
    [run],
  );
  const markChecksByGroup = useMemo(() => {
    const byGroup = new Map<string, ReturnType<typeof checkMarks>>();
    for (const { group } of run) {
      if (group.type !== "form_completion") continue;
      byGroup.set(group.key, checkMarks(group.doc, transcriptSegments));
    }
    return byGroup;
  }, [run, transcriptSegments]);

  // Questions with an answer decided: the nearest thing to evidence that the
  // author has understood how this is done, which is when the help retires.
  const authoredGapCount = useMemo(
    () =>
      run.reduce((total, { group }) => {
        if (group.type === "form_completion") {
          return (
            total +
            docGaps(group.doc).filter((g) => g.answers.some((a) => a.trim()))
              .length
          );
        }
        if (group.type === "multiple_choice") {
          return (
            total + group.questions.filter((q) => q.correct.length > 0).length
          );
        }
        return total;
      }, 0),
    [run],
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
  const startNumberOf = useMemo(
    () => new Map(run.map((entry) => [entry.group.key, entry.startNumber])),
    [run],
  );
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
              What are you authoring, and where does it go?
            </DialogDescription>
          </DialogHeader>
          <PartsPicker onPick={handlePick} />
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col font-mono">
      {milestone && state.materialId && (
        <PublishCelebration
          milestone={milestone}
          materialTitle={state.title.trim() || "Untitled"}
          url={`${window.location.origin}/listening/${state.materialId}`}
          onClose={() => setMilestone(null)}
        />
      )}

      {/* Top bar — title and the actions that apply to it share one line. No
          rule under it: the layout header already draws one just above, and
          the audio label's rule follows shortly after. */}
      {/* Title and actions live in the app header, not on the page. They are
          what this screen is about — the title was also the last breadcrumb,
          said twice — and a publish button that scrolls away with the form is
          a publish button you have to go looking for. */}
      <Header.Lead>
        {/* The way back, as the same round icon button the header already
            uses on its other side, rather than a word in a trail. It leaves
            the title as the only text here, which is what this screen is
            about. */}
        <Link
          to="/studio/listening"
          aria-label="Back to listening materials"
          title="Back to listening materials"
          className="mr-2 flex size-7 shrink-0 items-center justify-center rounded-full border border-foreground/10 text-muted-foreground transition-colors hover:border-foreground/20 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <ArrowLeft className="size-3.5" aria-hidden />
        </Link>
        <input
          type="text"
          value={state.title}
          onChange={(e) => update({ title: e.target.value })}
          placeholder="untitled listening"
          aria-label="Material title"
          className="min-w-0 flex-1 rounded-md border border-transparent bg-transparent px-2 py-1 text-sm font-medium text-foreground placeholder:text-muted-foreground hover:border-border focus:border-ring focus:outline-none"
        />
      </Header.Lead>

      <Header.Actions>
        {/* "saved" has to mean it. A part whose questions the API refused is
            called out here rather than folded into a timestamp that says
            everything is safely stored. */}
        <span
          className={cn(
            "hidden text-xs sm:inline",
            !saving && unsavedGroups.length > 0
              ? "text-warning"
              : "text-muted-foreground",
          )}
        >
          {saving
            ? "saving…"
            : unsavedGroups.length > 0
              ? `${unsavedGroups.join(", ")} not saved`
              : lastSavedAt
                ? `saved ${timeAgo(lastSavedAt.toISOString())}`
                : ""}
        </span>
        <button
          type="button"
          onClick={() => setHelpForced((v) => !v)}
          title="How to build the form"
          aria-label="How to build the form"
          className="flex size-7 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-foreground"
        >
          <CircleQuestionMark className="size-4" aria-hidden />
        </button>
        <PublishBar
          visibility={state.visibility}
          requirements={publishRequirements}
          refusal={publishError}
          busy={publishing}
          onPublish={() => void handlePublish()}
          onUnpublish={() => void handleDraft()}
        />
      </Header.Actions>

      {/* A conflict outlives any toast and stops autosave for good, so it gets
          a place on the page rather than a message that scrolls away. */}
      {conflict && (
        <div className="flex-none pb-2 text-xs text-warning">
          This material was edited in another window. Nothing is being saved
          from here any more —{" "}
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="underline underline-offset-2 hover:text-foreground"
          >
            reload
          </button>{" "}
          to pick up the latest version. Copy anything you typed since first.
        </div>
      )}

      {/* Panes. min-h-0 caps the grid at the height left over from the title
          bar; without it the row sizes to its tallest child and pushes the
          editor past the bottom of the screen, which is what put a second
          scrollbar on the page. */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-5 md:grid-cols-[minmax(340px,46%)_1fr]">
        {/* The player column fills the grid row rather than a hand-computed
            slice of the viewport. The old calc() guessed at everything above
            it — header, padding, title bar — guessed high, and overflowed the
            page by the difference. `h-full` can't be wrong about it.
            Only from md up: on a narrow screen the panes stack and the page
            scrolls normally. */}
        <div className="min-w-0 md:h-full md:min-h-0 md:border-r md:border-border md:pr-5">
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
            // What this part of the exam can be given, and what it's known
            // for that isn't built yet. Both are the part's business, so
            // they're worked out once here rather than per group.
            const partTypes = questionTypesForPart(part.orderIndex);
            const note = missingTypeNote(part.orderIndex);
            return (
              <section key={part.key} className="space-y-6">
                {/* The part heads its groups rather than sharing a line with
                    the first of them: with two sets of questions under it,
                    "Part 1" is what they have in common, not a label on one. */}
                <div className="space-y-2">
                  <h3 className="text-base font-medium text-foreground">
                    {partLabel(part)}
                  </h3>
                  {note && (
                    <p className="rounded-md bg-foreground/6 px-3 py-2 text-[11px] text-muted-foreground">
                      {note}
                    </p>
                  )}
                </div>

                {part.groups.map((group, index) => {
                  const startNumber = startNumberOf.get(group.key) ?? 1;
                  const tools = (
                    <AddGroupButton
                      types={partTypes}
                      onAdd={(type) => addGroup(part.key, group.key, type)}
                    />
                  );
                  const actions = {
                    onMoveUp: () => moveGroup(part.key, group.key, -1),
                    onMoveDown: () => moveGroup(part.key, group.key, 1),
                    onDelete: () => removeGroup(part.key, group.key),
                    canMoveUp: index > 0,
                    canMoveDown: index < part.groups.length - 1,
                  };
                  return (
                    <div
                      key={group.key}
                      ref={(el) => {
                        groupSectionRefs.current[group.key] = el;
                      }}
                    >
                      {group.type === null ? (
                        <GroupTypeChooser
                          types={partTypes}
                          note={missingTypeNote(part.orderIndex)}
                          onChoose={(type) => chooseGroupType(group.key, type)}
                          onRemove={() => removeGroup(part.key, group.key)}
                          disabled={!hasAudioEverAttached}
                        />
                      ) : group.type === "multiple_choice" ? (
                        <ChoiceGroupEditor
                          questions={group.questions}
                          onChange={(edit) => editGroupQuestions(group.key, edit)}
                          instructions={group.instructions}
                          onInstructionsChange={(instructions) =>
                            updateGroup(group.key, (g) => ({ ...g, instructions }))
                          }
                          startNumber={startNumber}
                          showIssues={badGroupKey === group.key}
                          transcriptSelection={transcriptSelection}
                          disabled={!hasAudioEverAttached}
                          extraTools={tools}
                          {...actions}
                        />
                      ) : (
                        <QuestionFormEditor
                          doc={group.doc}
                          onChange={(edit) => editGroupDoc(group.key, edit)}
                          instructions={group.instructions}
                          onInstructionsChange={(instructions) =>
                            updateGroup(group.key, (g) => ({ ...g, instructions }))
                          }
                          rubric={group.rubric}
                          onRubricChange={(rubric) =>
                            updateGroup(group.key, (g) =>
                              g.type === "form_completion"
                                ? {
                                    ...g,
                                    rubric,
                                    // The old numeric field is kept in step so
                                    // nothing that still reads it starts
                                    // disagreeing with the sentence.
                                    wordLimit:
                                      ANSWER_RUBRICS.find(
                                        (r) => r.value === rubric,
                                      )?.words ?? null,
                                  }
                                : g,
                            )
                          }
                          startNumber={startNumber}
                          showIssues={badGroupKey === group.key}
                          markChecks={markChecksByGroup.get(group.key)}
                          onMarkAudio={
                            hasAudioEverAttached ? requestMark : undefined
                          }
                          disabled={!hasAudioEverAttached}
                          extraTools={tools}
                          {...actions}
                        />
                      )}
                    </div>
                  );
                })}

                {/* A part emptied of every group still needs a way back in. */}
                {part.groups.length === 0 && (
                  <div className="flex justify-center">
                    <AddGroupButton
                      types={partTypes}
                      onAdd={(type) => addGroup(part.key, null, type)}
                    />
                  </div>
                )}
              </section>
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
