import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Loader2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageLoader } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import { toast } from "@/lib/toast";
import { getErrorMessage } from "@/lib/api";
import { listeningApi, mediaUrl } from "@/features/listening/api";
import {
  useListeningMaterial,
  useUpdateListeningMaterial,
} from "@/features/listening/queries";
import { PartsPanel } from "@/features/listening/components/PartsPanel";
import type { Visibility } from "@/features/listening/types";

const inputCls =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none";

export default function StudioMaterialEditorPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: material, isLoading } = useListeningMaterial(id);
  const updateMut = useUpdateListeningMaterial(id ?? "");

  const [title, setTitle] = useState("");
  const [visibility, setVisibility] = useState<Visibility>("private");
  const [uploading, setUploading] = useState(false);
  const [metaError, setMetaError] = useState<string | null>(null);

  const audioRef = useRef<HTMLAudioElement>(null);
  const loaded = useRef(false);

  useEffect(() => {
    if (material && !loaded.current) {
      loaded.current = true;
      setTitle(material.title);
      setVisibility(material.visibility);
    }
  }, [material]);

  if (!id) return null;
  if (isLoading || !material) return <PageLoader />;

  const saveMeta = () => {
    if (!title.trim()) {
      setMetaError("Title is required.");
      return;
    }
    setMetaError(null);
    updateMut.mutate(
      { title: title.trim(), visibility },
      { onError: (e) => toast(getErrorMessage(e)) },
    );
  };

  const onUpload = async (file: File) => {
    setUploading(true);
    try {
      const asset = await listeningApi.uploadAudio(file);
      updateMut.mutate(
        { audio_asset_id: asset.asset_id },
        { onError: (e) => toast(getErrorMessage(e)) },
      );
    } catch (e) {
      toast(getErrorMessage(e));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-foreground">Edit listening material</h1>
        <Button variant="ghost" onClick={() => navigate("/studio")}>
          Done
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Details</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="edit-title" className="text-sm font-medium text-foreground">
              Title
            </label>
            <input
              id="edit-title"
              className={inputCls}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
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

          {metaError && <p className="text-sm text-destructive">{metaError}</p>}

          <div className="flex justify-end">
            <Button size="sm" onClick={saveMeta} disabled={updateMut.isPending}>
              {updateMut.isPending && <Loader2 className="size-4 animate-spin" />}
              Save details
            </Button>
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
            {material.audio_url ? "Replace audio" : "Upload audio"}
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
          {material.audio_url && (
            <audio
              ref={audioRef}
              controls
              src={mediaUrl(material.audio_url)}
              className="w-full"
            />
          )}
        </CardContent>
      </Card>

      <PartsPanel
        materialId={id}
        parts={material.parts}
        audioRef={audioRef}
        hasAudio={!!material.audio_url}
      />
    </div>
  );
}
