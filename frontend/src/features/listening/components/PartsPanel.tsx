import { useState, type RefObject } from "react";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { getErrorMessage } from "@/lib/api";
import { toast } from "@/lib/toast";
import { useCreatePart, useDeletePart } from "@/features/listening/queries";
import { QuestionGroupEditor } from "@/features/listening/components/QuestionGroupEditor";
import type { ListeningPart } from "@/features/listening/types";

const inputCls =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none";

function fmt(ms: number): string {
  const s = ms / 1000;
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}.${String(Math.floor(ms % 1000)).padStart(3, "0")}`;
}

function PartQuestionGroups({
  part,
  materialId,
}: {
  part: ListeningPart;
  materialId: string;
}) {
  const [adding, setAdding] = useState(false);

  return (
    <div className="space-y-3 border-t border-border pt-3">
      {part.question_groups.map((group) => (
        <QuestionGroupEditor
          key={group.id}
          partId={part.id}
          materialId={materialId}
          existing={group}
        />
      ))}
      {adding && (
        <QuestionGroupEditor
          partId={part.id}
          materialId={materialId}
          onDone={() => setAdding(false)}
        />
      )}
      {!adding && (
        <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
          <Plus className="size-4" />
          Add question group
        </Button>
      )}
    </div>
  );
}

interface PartsPanelProps {
  materialId: string;
  parts: ListeningPart[];
  audioRef: RefObject<HTMLAudioElement | null>;
  hasAudio: boolean;
}

export function PartsPanel({ materialId, parts, audioRef, hasAudio }: PartsPanelProps) {
  const createPart = useCreatePart(materialId);
  const deletePart = useDeletePart(materialId);

  const [showNewPart, setShowNewPart] = useState(parts.length === 0);
  const [title, setTitle] = useState("");
  const [startMs, setStartMs] = useState<number | null>(null);
  const [endMs, setEndMs] = useState<number | null>(null);
  const [wholeAudio, setWholeAudio] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const currentMs = () => Math.round((audioRef.current?.currentTime ?? 0) * 1000);

  const resetForm = () => {
    setTitle("");
    setStartMs(null);
    setEndMs(null);
    setWholeAudio(true);
    setError(null);
  };

  const submitPart = () => {
    if (!title.trim()) {
      setError("Title is required.");
      return;
    }
    if (!wholeAudio && startMs != null && endMs != null && endMs <= startMs) {
      setError("End must be after start.");
      return;
    }
    setError(null);
    createPart.mutate(
      {
        order_index: parts.length,
        title: title.trim(),
        audio_start_ms: wholeAudio ? null : startMs,
        audio_end_ms: wholeAudio ? null : endMs,
      },
      {
        onSuccess: () => {
          resetForm();
          setShowNewPart(false);
        },
        onError: (e) => toast(getErrorMessage(e)),
      },
    );
  };

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>Parts</CardTitle>
        {!showNewPart && (
          <Button variant="outline" size="sm" onClick={() => setShowNewPart(true)}>
            <Plus className="size-4" />
            Add part
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {parts.length === 0 && !showNewPart && (
          <p className="text-sm text-muted-foreground">
            No parts yet. Add one to start authoring question groups.
          </p>
        )}

        {parts
          .slice()
          .sort((a, b) => a.order_index - b.order_index)
          .map((part) => (
            <div key={part.id} className="space-y-3 rounded-lg border border-border p-3">
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-medium text-foreground">{part.title}</span>
                  <span className="ml-2 text-xs text-muted-foreground">
                    {part.audio_start_ms != null && part.audio_end_ms != null
                      ? `${fmt(part.audio_start_ms)} → ${fmt(part.audio_end_ms)}`
                      : "whole audio"}
                  </span>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive"
                  disabled={deletePart.isPending}
                  aria-label={`Delete part ${part.title}`}
                  onClick={() => {
                    if (
                      window.confirm(
                        `Delete "${part.title}" and all its question groups? This cannot be undone.`,
                      )
                    ) {
                      deletePart.mutate(part.id);
                    }
                  }}
                >
                  {deletePart.isPending ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <Trash2 className="size-4" />
                  )}
                </Button>
              </div>
              <PartQuestionGroups part={part} materialId={materialId} />
            </div>
          ))}

        {showNewPart && (
          <div className="space-y-3 rounded-lg border border-dashed border-border p-3">
            <div className="space-y-1.5">
              <label htmlFor="new-part-title" className="text-sm font-medium text-foreground">
                Part title
              </label>
              <input
                id="new-part-title"
                className={inputCls}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Part 1"
              />
            </div>

            <label className="flex items-center gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                checked={wholeAudio}
                onChange={(e) => setWholeAudio(e.target.checked)}
              />
              Uses the whole audio (no range)
            </label>

            {!wholeAudio && (
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={!hasAudio}
                  onClick={() => setStartMs(currentMs())}
                >
                  Set start
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={!hasAudio}
                  onClick={() => setEndMs(currentMs())}
                >
                  Set end
                </Button>
                <input
                  type="number"
                  className={cn(inputCls, "w-28")}
                  value={startMs ?? 0}
                  min={0}
                  onChange={(e) => setStartMs(Number(e.target.value))}
                  aria-label="Part start ms"
                />
                <input
                  type="number"
                  className={cn(inputCls, "w-28")}
                  value={endMs ?? 0}
                  min={0}
                  onChange={(e) => setEndMs(Number(e.target.value))}
                  aria-label="Part end ms"
                />
              </div>
            )}

            {error && <p className="text-sm text-destructive">{error}</p>}

            <div className="flex justify-end gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  resetForm();
                  if (parts.length > 0) setShowNewPart(false);
                }}
              >
                Cancel
              </Button>
              <Button size="sm" onClick={submitPart} disabled={createPart.isPending}>
                {createPart.isPending && <Loader2 className="size-4 animate-spin" />}
                Create part
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
