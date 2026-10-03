import { useMutation, useQueryClient } from "@tanstack/react-query";
import { getErrorMessage } from "@/lib/api";
import { toast } from "@/lib/toast";
import { vocabularyApi, wordListsKey } from "@/features/vocabulary/api";

/** `142 / 1,700` — thousands separated, always English digits. */
export function formatProgress(owned: number, total: number): string {
  return `${owned.toLocaleString("en-US")} / ${total.toLocaleString("en-US")}`;
}

export function formatCount(n: number): string {
  return n.toLocaleString("en-US");
}

/** The one-time note after Start. Only when something is waiting; the
 *  server decides the number, this only words it. */
export function pendingMessage(title: string, pending: number): string | null {
  if (pending <= 0) return null;
  const noun = pending === 1 ? "word" : "words";
  return `You have ${pending} saved ${noun} still to learn. ${title} will start after those.`;
}

/** Start and Stop for one list. Both are subscription changes only — no
 *  saved word is created or removed — so what they refresh is the lists and
 *  the practice numbers (new-word candidates change), nothing else. */
export function useListToggle(listKey: string) {
  const qc = useQueryClient();
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: wordListsKey });
    void qc.invalidateQueries({ queryKey: ["vocabulary", "practice"] });
  };
  const start = useMutation({
    mutationFn: () => vocabularyApi.startList(listKey),
    onSuccess: refresh,
    onError: (e) => toast(getErrorMessage(e)),
  });
  const stop = useMutation({
    mutationFn: () => vocabularyApi.stopList(listKey),
    onSuccess: () => {
      start.reset();
      refresh();
    },
    onError: (e) => toast(getErrorMessage(e)),
  });
  return { start, stop, busy: start.isPending || stop.isPending };
}
