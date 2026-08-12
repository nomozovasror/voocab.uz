import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Plus, Trash2, Play, Upload, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageLoader } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import { PublishControl } from "@/components/studio/PublishControl";
import { toast } from "@/lib/toast";
import { getErrorMessage } from "@/lib/api";
import { materialsApi, mediaUrl } from "@/features/materials/api";
import {
  useCreateMaterial,
  useMaterial,
  useUpdateMaterial,
} from "@/features/materials/queries";
import type {
  SegmentInput,
  Visibility,
} from "@/features/materials/types";

const inputCls =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none";

function fmt(ms: number): string {
  const s = ms / 1000;
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}.${String(Math.floor(ms % 1000)).padStart(3, "0")}`;
}

export default function MaterialEditorPage() {
  const { id } = useParams<{ id: string }>();
  const isEdit = !!id;
  const navigate = useNavigate();
  const { data: existing, isLoading } = useMaterial(id);
  const createMut = useCreateMaterial();
  const updateMut = useUpdateMaterial(id ?? "");

  const [title, setTitle] = useState("");
  const [visibility, setVisibility] = useState<Visibility>("private");
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [punctuationSensitive, setPunctuationSensitive] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [segments, setSegments] = useState<SegmentInput[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const audioRef = useRef<HTMLAudioElement>(null);
  const pauseTimer = useRef<number | undefined>(undefined);
  const loaded = useRef(false);

  // Hydrate the form once when editing.
  useEffect(() => {
    if (existing && !loaded.current) {
      loaded.current = true;
      setTitle(existing.title);
      setVisibility(existing.visibility);
      setCaseSensitive(existing.case_sensitive);
      setPunctuationSensitive(existing.punctuation_sensitive);
      setAudioUrl(existing.audio_url);
      setSegments(
        existing.segments.map((s) => ({
          start_ms: s.start_ms,
          end_ms: s.end_ms,
          reference_text: s.reference_text,
        })),
      );
    }
  }, [existing]);

  const currentMs = () =>
    Math.round((audioRef.current?.currentTime ?? 0) * 1000);

  const patchSegment = (i: number, patch: Partial<SegmentInput>) =>
    setSegments((prev) =>
      prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)),
    );

  const addSegment = () =>
    setSegments((prev) => {
      const last = prev[prev.length - 1];
      const start = last ? last.end_ms : 0;
      return [...prev, { start_ms: start, end_ms: start + 3000, reference_text: "" }];
    });

  const removeSegment = (i: number) =>
    setSegments((prev) => prev.filter((_, idx) => idx !== i));

  const playSegment = (seg: SegmentInput) => {
    const audio = audioRef.current;
    if (!audio) return;
    window.clearTimeout(pauseTimer.current);
    audio.currentTime = seg.start_ms / 1000;
    void audio.play();
    pauseTimer.current = window.setTimeout(
      () => audio.pause(),
      Math.max(0, seg.end_ms - seg.start_ms),
    );
  };

  const onUpload = async (file: File) => {
    setUploading(true);
    try {
      const url = await materialsApi.uploadAudio(file);
      setAudioUrl(url);
    } catch (e) {
      toast(getErrorMessage(e));
    } finally {
      setUploading(false);
    }
  };

  const validate = (): string | null => {
    if (!title.trim()) return "Title is required.";
    for (const [i, s] of segments.entries()) {
      if (!s.reference_text.trim())
        return `Segment ${i + 1}: reference text is required.`;
      if (s.end_ms <= s.start_ms)
        return `Segment ${i + 1}: end must be after start.`;
    }
    return null;
  };

  const onSave = () => {
    const problem = validate();
    setError(problem);
    if (problem) return;

    const payload = {
      title: title.trim(),
      type: "dictation",
      audio_url: audioUrl,
      case_sensitive: caseSensitive,
      punctuation_sensitive: punctuationSensitive,
      segments: segments.map((s) => ({
        start_ms: s.start_ms,
        end_ms: s.end_ms,
        reference_text: s.reference_text.trim(),
      })),
    };

    const onDone = () => navigate("/materials");
    if (isEdit) updateMut.mutate(payload, { onSuccess: onDone });
    else createMut.mutate(payload, { onSuccess: onDone });
  };

  const saving = createMut.isPending || updateMut.isPending;

  if (isEdit && isLoading) return <PageLoader />;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="text-2xl font-semibold text-foreground">
        {isEdit ? "Edit material" : "New material"}
      </h1>

      <Card>
        <CardHeader>
          <CardTitle>Details</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-foreground">Title</label>
            <input
              className={inputCls}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. TED Talk — opening lines"
            />
          </div>

          <div className="flex flex-wrap gap-4">
            {isEdit && (
              <PublishControl
                visibility={visibility}
                onChange={async (next) => {
                  await updateMut.mutateAsync({ visibility: next });
                  setVisibility(next);
                }}
              />
            )}

            <label className="flex items-center gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                checked={caseSensitive}
                onChange={(e) => setCaseSensitive(e.target.checked)}
              />
              Case sensitive
            </label>
            <label className="flex items-center gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                checked={punctuationSensitive}
                onChange={(e) => setPunctuationSensitive(e.target.checked)}
              />
              Punctuation sensitive
            </label>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Audio</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-border px-3 py-2 text-sm text-foreground transition-colors hover:bg-foreground/5">
            {uploading ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Upload className="size-4" />
            )}
            {audioUrl ? "Replace audio" : "Upload audio"}
            <input
              type="file"
              accept="audio/*"
              className="hidden"
              disabled={uploading}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void onUpload(f);
                e.target.value = "";
              }}
            />
          </label>
          {audioUrl && (
            <audio
              ref={audioRef}
              controls
              src={mediaUrl(audioUrl)}
              className="w-full"
            />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Segments</CardTitle>
          <Button variant="outline" size="sm" onClick={addSegment}>
            <Plus className="size-4" />
            Add
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {segments.length === 0 && (
            <p className="text-sm text-muted-foreground">
              Add segments and set their start/end from the audio player above.
            </p>
          )}
          {segments.map((seg, i) => (
            <div
              key={i}
              className="space-y-2 rounded-lg border border-border p-3"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-muted-foreground">
                  Segment {i + 1} · {fmt(seg.start_ms)} → {fmt(seg.end_ms)}
                </span>
                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => playSegment(seg)}
                    disabled={!audioUrl}
                  >
                    <Play className="size-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    onClick={() => removeSegment(i)}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              </div>
              <input
                className={inputCls}
                value={seg.reference_text}
                onChange={(e) =>
                  patchSegment(i, { reference_text: e.target.value })
                }
                placeholder="Reference text the learner should type"
              />
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!audioUrl}
                  onClick={() => patchSegment(i, { start_ms: currentMs() })}
                >
                  Set start
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!audioUrl}
                  onClick={() => patchSegment(i, { end_ms: currentMs() })}
                >
                  Set end
                </Button>
                <input
                  type="number"
                  className={cn(inputCls, "w-28")}
                  value={seg.start_ms}
                  min={0}
                  onChange={(e) =>
                    patchSegment(i, { start_ms: Number(e.target.value) })
                  }
                  aria-label="Start ms"
                />
                <input
                  type="number"
                  className={cn(inputCls, "w-28")}
                  value={seg.end_ms}
                  min={0}
                  onChange={(e) =>
                    patchSegment(i, { end_ms: Number(e.target.value) })
                  }
                  aria-label="End ms"
                />
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={() => navigate("/materials")}>
          Cancel
        </Button>
        <Button onClick={onSave} disabled={saving}>
          {saving && <Loader2 className="size-4 animate-spin" />}
          {isEdit ? "Save changes" : "Create material"}
        </Button>
      </div>
    </div>
  );
}
