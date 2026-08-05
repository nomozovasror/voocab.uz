import { useState } from "react";
import { Link } from "react-router-dom";
import { Plus, Pencil, Trash2, Globe, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { PageLoader } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import {
  useDeleteListeningMaterial,
  useListeningMaterials,
} from "@/features/listening/queries";
import type { ListeningMaterial } from "@/features/listening/types";

function MaterialRow({ material }: { material: ListeningMaterial }) {
  const del = useDeleteListeningMaterial();
  const [confirming, setConfirming] = useState(false);

  return (
    <Card>
      <CardContent className="flex items-center gap-4 py-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate font-medium text-foreground">
              {material.title}
            </span>
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs",
                material.visibility === "public"
                  ? "bg-primary/10 text-primary"
                  : "bg-muted text-muted-foreground",
              )}
            >
              {material.visibility === "public" ? (
                <Globe className="size-3" />
              ) : (
                <Lock className="size-3" />
              )}
              {material.visibility}
            </span>
          </div>
          <div className="mt-0.5 text-sm text-muted-foreground">
            {material.type}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <Button asChild variant="outline" size="sm">
            <Link to={`/studio/materials/${material.id}/edit`}>
              <Pencil className="size-4" />
              Edit
            </Link>
          </Button>
          {confirming ? (
            <>
              <Button
                variant="destructive"
                size="sm"
                disabled={del.isPending}
                onClick={() => del.mutate(material.id)}
              >
                Confirm
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
                Cancel
              </Button>
            </>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive hover:text-destructive"
              onClick={() => setConfirming(true)}
              aria-label={`Delete ${material.title}`}
            >
              <Trash2 className="size-4" />
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export default function StudioMaterialsPage() {
  const { data: materials, isLoading, isError } = useListeningMaterials("mine");
  const listening = materials?.filter((m) => m.type === "listening") ?? [];

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold text-foreground">My materials</h1>
          <p className="text-muted-foreground">
            Listening exercises you&apos;ve authored.
          </p>
        </div>
        <Button asChild>
          <Link to="/studio/materials/new">
            <Plus className="size-4" />
            New listening
          </Link>
        </Button>
      </div>

      {isLoading ? (
        <PageLoader />
      ) : isError ? (
        <p className="text-sm text-destructive">Couldn&apos;t load your materials.</p>
      ) : listening.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
            <p className="text-muted-foreground">No listening materials yet.</p>
            <Button asChild>
              <Link to="/studio/materials/new">
                <Plus className="size-4" />
                Create your first
              </Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {listening.map((m) => (
            <MaterialRow key={m.id} material={m} />
          ))}
        </div>
      )}
    </div>
  );
}
