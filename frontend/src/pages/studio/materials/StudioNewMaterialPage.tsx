import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { toast } from "@/lib/toast";
import { getErrorMessage } from "@/lib/api";
import { listeningApi } from "@/features/listening/api";
import { useCreateListeningMaterial } from "@/features/listening/queries";
import type { Visibility } from "@/features/listening/types";

const inputCls =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none";

export default function StudioNewMaterialPage() {
  const navigate = useNavigate();
  const createMut = useCreateListeningMaterial();

  const [title, setTitle] = useState("");
  const [visibility, setVisibility] = useState<Visibility>("private");
  const [audioAssetId, setAudioAssetId] = useState<string | null>(null);
  const [audioFileName, setAudioFileName] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onUpload = async (file: File) => {
    setUploading(true);
    try {
      const asset = await listeningApi.uploadAudio(file);
      setAudioAssetId(asset.asset_id);
      setAudioFileName(file.name);
    } catch (e) {
      toast(getErrorMessage(e));
    } finally {
      setUploading(false);
    }
  };

  const onSave = () => {
    if (!title.trim()) {
      setError("Title is required.");
      return;
    }
    setError(null);
    createMut.mutate(
      {
        title: title.trim(),
        type: "listening",
        visibility,
        audio_asset_id: audioAssetId,
      },
      {
        onSuccess: (material) => navigate(`/studio/materials/${material.id}/edit`),
        onError: (e) => toast(getErrorMessage(e)),
      },
    );
  };

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="text-2xl font-semibold text-foreground">New listening material</h1>

      <Card>
        <CardHeader>
          <CardTitle>Details</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="material-title" className="text-sm font-medium text-foreground">
              Title
            </label>
            <input
              id="material-title"
              className={inputCls}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. IELTS Listening — Part 1 Booking a hotel room"
            />
          </div>

          <div className="space-y-1.5">
            <span className="text-sm font-medium text-foreground">Visibility</span>
            <div className="flex gap-1 rounded-md border border-border p-1">
              {(["private", "public"] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setVisibility(v)}
                  className={cn(
                    "rounded px-3 py-1 text-sm capitalize transition-colors",
                    visibility === v
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {v}
                </button>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Audio (optional — can be added later)</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-border px-3 py-2 text-sm text-foreground transition-colors hover:bg-foreground/5">
            {uploading ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Upload className="size-4" />
            )}
            {audioAssetId ? "Replace audio" : "Upload audio"}
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
          {audioFileName && (
            <p className="text-sm text-muted-foreground">Selected: {audioFileName}</p>
          )}
        </CardContent>
      </Card>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={() => navigate("/studio")}>
          Cancel
        </Button>
        <Button onClick={onSave} disabled={createMut.isPending || uploading}>
          {createMut.isPending && <Loader2 className="size-4 animate-spin" />}
          Create material
        </Button>
      </div>
    </div>
  );
}
