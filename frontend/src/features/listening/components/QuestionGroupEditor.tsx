import { useMemo, useRef, useState, type RefObject } from "react";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { getErrorMessage } from "@/lib/api";
import {
  useCreateQuestionGroup,
  useDeleteQuestionGroup,
  useUpdateQuestionGroup,
} from "@/features/listening/queries";
import { AnswerChipsInput } from "@/features/listening/components/AnswerChipsInput";
import type { ListeningQuestionGroup } from "@/features/listening/types";

const inputCls =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none";

const TOKEN_RE = /\{\{(\d+)\}\}/g;

function detectTokens(template: string): number[] {
  const found: number[] = [];
  for (const m of template.matchAll(TOKEN_RE)) found.push(Number(m[1]));
  return found;
}

interface ValidationResult {
  errors: string[];
  tokenNumbers: number[];
}

function validateTemplate(
  template: string,
  instructions: string,
  answersByNumber: Record<number, string[]>,
): ValidationResult {
  const errors: string[] = [];
  if (!instructions.trim()) errors.push("Instructions are required.");
  if (!template.trim()) errors.push("Template is required.");

  const tokens = detectTokens(template);
  const tokenSet = new Set(tokens);
  if (tokens.length === 0) {
    errors.push("Template must contain at least one {{N}} gap token.");
  } else if (tokenSet.size !== tokens.length) {
    errors.push("Template gap tokens must not repeat.");
  } else {
    const expected = new Set(
      Array.from({ length: tokens.length }, (_, i) => i + 1),
    );
    const matches =
      tokenSet.size === expected.size &&
      [...expected].every((n) => tokenSet.has(n));
    if (!matches) {
      errors.push(
        `Template gap tokens must be contiguous 1..${tokens.length}, starting at 1 (no gaps).`,
      );
    }
  }

  for (const n of tokenSet) {
    const answers = (answersByNumber[n] ?? []).map((a) => a.trim()).filter(Boolean);
    if (answers.length === 0) {
      errors.push(`Gap {{${n}}} needs at least one accepted answer.`);
    }
  }

  return { errors, tokenNumbers: [...tokenSet].sort((a, b) => a - b) };
}

function insertTokenAtCursor(
  textareaRef: RefObject<HTMLTextAreaElement | null>,
  template: string,
  nextToken: number,
  setTemplate: (v: string) => void,
) {
  const el = textareaRef.current;
  const token = `{{${nextToken}}}`;
  if (!el) {
    setTemplate(template + token);
    return;
  }
  const start = el.selectionStart ?? template.length;
  const end = el.selectionEnd ?? template.length;
  const next = template.slice(0, start) + token + template.slice(end);
  setTemplate(next);
  requestAnimationFrame(() => {
    el.focus();
    const pos = start + token.length;
    el.setSelectionRange(pos, pos);
  });
}

interface QuestionGroupEditorProps {
  partId: string;
  materialId: string;
  /** Existing group to edit; omit to render a "new group" draft form. */
  existing?: ListeningQuestionGroup;
  /** Called after a new draft group is discarded (cancel) or saved. */
  onDone?: () => void;
}

export function QuestionGroupEditor({
  partId,
  materialId,
  existing,
  onDone,
}: QuestionGroupEditorProps) {
  const isNew = !existing;
  const createMut = useCreateQuestionGroup(materialId);
  const updateMut = useUpdateQuestionGroup(materialId);
  const deleteMut = useDeleteQuestionGroup(materialId);

  const [instructions, setInstructions] = useState(existing?.instructions ?? "");
  const [wordLimit, setWordLimit] = useState<string>(
    existing?.word_limit != null ? String(existing.word_limit) : "",
  );
  const [template, setTemplate] = useState(existing?.config.template ?? "");
  const [answersByNumber, setAnswersByNumber] = useState<Record<number, string[]>>(
    () => {
      const map: Record<number, string[]> = {};
      for (const q of existing?.questions ?? []) {
        map[q.number] = q.correct_answers ?? [];
      }
      return map;
    },
  );
  const [attempted, setAttempted] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const { errors, tokenNumbers } = useMemo(
    () => validateTemplate(template, instructions, answersByNumber),
    [template, instructions, answersByNumber],
  );

  const setAnswersFor = (n: number, next: string[]) =>
    setAnswersByNumber((prev) => ({ ...prev, [n]: next }));

  const insertToken = () => {
    const next = detectTokens(template).length + 1;
    insertTokenAtCursor(textareaRef, template, next, setTemplate);
  };

  const save = () => {
    setAttempted(true);
    setServerError(null);
    if (errors.length > 0) return;

    const wl = wordLimit.trim() ? Number(wordLimit) : null;
    const payload = {
      type: "form_completion" as const,
      instructions: instructions.trim(),
      word_limit: wl,
      config: { template },
      questions: tokenNumbers.map((n) => ({
        number: n,
        correct_answers: (answersByNumber[n] ?? [])
          .map((a) => a.trim())
          .filter(Boolean),
      })),
    };

    if (isNew) {
      createMut.mutate(
        { partId, data: payload },
        {
          onSuccess: () => onDone?.(),
          onError: (e) => setServerError(getErrorMessage(e)),
        },
      );
    } else {
      updateMut.mutate(
        { groupId: existing.id, data: payload },
        {
          onError: (e) => setServerError(getErrorMessage(e)),
        },
      );
    }
  };

  const saving = createMut.isPending || updateMut.isPending;
  const showErrors = attempted && errors.length > 0;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>{isNew ? "New question group" : "Question group"}</CardTitle>
        <div className="flex items-center gap-1">
          {isNew ? (
            <Button variant="ghost" size="sm" onClick={onDone}>
              Cancel
            </Button>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive hover:text-destructive"
              onClick={() => {
                if (window.confirm("Delete this question group? This cannot be undone.")) {
                  deleteMut.mutate(existing.id);
                }
              }}
              disabled={deleteMut.isPending}
              aria-label="Delete question group"
            >
              {deleteMut.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Trash2 className="size-4" />
              )}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1.5">
          <label
            htmlFor={`instructions-${existing?.id ?? "new"}-${partId}`}
            className="text-sm font-medium text-foreground"
          >
            Instructions
          </label>
          <textarea
            id={`instructions-${existing?.id ?? "new"}-${partId}`}
            className={cn(inputCls, "min-h-16 resize-y")}
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            placeholder="Complete the form below. Write NO MORE THAN THREE WORDS AND/OR A NUMBER for each answer."
          />
        </div>

        <div className="max-w-40 space-y-1.5">
          <label
            htmlFor={`word-limit-${existing?.id ?? "new"}-${partId}`}
            className="text-sm font-medium text-foreground"
          >
            Word limit (optional)
          </label>
          <input
            id={`word-limit-${existing?.id ?? "new"}-${partId}`}
            type="number"
            min={1}
            className={inputCls}
            value={wordLimit}
            onChange={(e) => setWordLimit(e.target.value)}
            placeholder="e.g. 3"
          />
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label
              htmlFor={`template-${existing?.id ?? "new"}-${partId}`}
              className="text-sm font-medium text-foreground"
            >
              Template
            </label>
            <Button type="button" variant="outline" size="sm" onClick={insertToken}>
              <Plus className="size-4" />
              Insert next gap
            </Button>
          </div>
          <textarea
            id={`template-${existing?.id ?? "new"}-${partId}`}
            ref={textareaRef}
            className={cn(inputCls, "min-h-32 resize-y font-mono")}
            value={template}
            onChange={(e) => setTemplate(e.target.value)}
            placeholder={"Name:              {{1}}\nDelivery address:  17 {{2}} Street"}
          />
          <p className="text-xs text-muted-foreground">
            Mark gaps with <code>{"{{1}}"}</code>, <code>{"{{2}}"}</code>, …
            contiguous from 1.
          </p>
        </div>

        {tokenNumbers.length > 0 && (
          <div className="space-y-3 rounded-lg border border-border p-3">
            <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
              Gaps &amp; accepted answers
            </p>
            {tokenNumbers.map((n) => (
              <AnswerChipsInput
                key={n}
                label={`Gap ${n} — accepted answers`}
                value={answersByNumber[n] ?? []}
                onChange={(next) => setAnswersFor(n, next)}
                placeholder="Type an answer and press Enter"
                error={
                  showErrors && (answersByNumber[n] ?? []).filter((a) => a.trim()).length === 0
                    ? "At least one accepted answer is required."
                    : undefined
                }
              />
            ))}
          </div>
        )}

        {showErrors && (
          <ul className="space-y-1 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {errors.map((err) => (
              <li key={err}>{err}</li>
            ))}
          </ul>
        )}
        {serverError && <p className="text-sm text-destructive">{serverError}</p>}

        <div className="flex justify-end">
          <Button onClick={save} disabled={saving}>
            {saving && <Loader2 className="size-4 animate-spin" />}
            {isNew ? "Save group" : "Save changes"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
