import { Link } from "react-router-dom";
import { Headphones, Globe, Lock } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageLoader } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import { useListeningMaterials } from "@/features/listening/queries";
import type { ListeningMaterial } from "@/features/listening/types";

function dedupeById(lists: ListeningMaterial[][]): ListeningMaterial[] {
  const map = new Map<string, ListeningMaterial>();
  for (const list of lists) for (const m of list) map.set(m.id, m);
  return [...map.values()];
}

function MaterialCard({ material }: { material: ListeningMaterial }) {
  return (
    <Card>
      <CardContent className="flex items-center gap-4 py-4">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
          <Headphones className="size-5" />
        </div>
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
          <p className="mt-0.5 text-sm text-muted-foreground">Listening practice</p>
        </div>
        <Button asChild size="sm">
          <Link to={`/listening/${material.id}`}>Practice</Link>
        </Button>
      </CardContent>
    </Card>
  );
}

export default function ListeningPage() {
  const mine = useListeningMaterials("mine");
  const pub = useListeningMaterials("public");

  const isLoading = mine.isLoading || pub.isLoading;
  const isError = mine.isError && pub.isError;

  const materials = dedupeById([mine.data ?? [], pub.data ?? []]).filter(
    (m) => m.type === "listening",
  );

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold text-foreground">Listening</h1>
        <p className="text-muted-foreground">
          Practice IELTS-style listening exercises — play the audio and fill in
          the gaps.
        </p>
      </div>

      {isLoading ? (
        <PageLoader />
      ) : isError ? (
        <p className="text-sm text-destructive">
          Couldn&apos;t load listening materials.
        </p>
      ) : materials.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
            <p className="text-muted-foreground">
              No listening materials yet. Check back soon, or author one in the
              Studio.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {materials.map((m) => (
            <MaterialCard key={m.id} material={m} />
          ))}
        </div>
      )}
    </div>
  );
}
