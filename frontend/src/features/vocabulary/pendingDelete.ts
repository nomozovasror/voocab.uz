import { useEffect, useSyncExternalStore } from "react";
import { queryClient } from "@/lib/query-client";
import { toast } from "@/lib/toast";
import { getErrorMessage } from "@/lib/api";
import { vocabularyApi, vocabularyWordsKey, wordDetailKey } from "@/features/vocabulary/api";

/**
 * Deleting ONE word never asks first — the question a confirmation dialog
 * asks ("are you sure?") is answered better by a few seconds in which the
 * word is already gone and one press brings it straight back. This is that
 * window: the row leaves the list at once, the DELETE itself waits.
 *
 * Keyed by the saved word's own id, not its lemma — a lemma stopped naming
 * one row the moment two senses of it could each be saved, and "Removed ·
 * Undo" has to name the exact card leaving, not every row that happens to
 * share a spelling.
 *
 * Module-level rather than a hook's own state, for the one requirement a
 * hook can't meet on its own: pressing delete on the word page navigates to
 * the list, unmounting the page that started the timer. A `setTimeout` held
 * in a component's closure dies with it; one held here keeps running
 * whichever page — or neither — is on screen, and the list picks the same
 * id back up out of this map rather than out of a prop it was never handed.
 *
 * Bulk delete (more than one word at once) does NOT go through here — see
 * `DeleteWordsDialog`. A dialog already asks the question this window
 * answers a cheaper way for one word; asking twice for a batch would be
 * neither cheap nor be answering anything.
 */

const GRACE_MS = 6000;

interface Pending {
  timer: ReturnType<typeof setTimeout>;
  /** Set the instant the DELETE is sent, so a page unmounting in the same
   *  tick the timer fires can't ask for a second one. */
  flushed: boolean;
}

const pending = new Map<string, Pending>();
/** Rebuilt on every change rather than derived per read — `useSyncExternalStore`
 *  needs a snapshot that is reference-stable between notifications, or React
 *  reads it as "changed" on every render and warns about it. */
let snapshot: ReadonlySet<string> = new Set();
const listeners = new Set<() => void>();

function publish(): void {
  snapshot = new Set(pending.keys());
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): ReadonlySet<string> {
  return snapshot;
}

/** The word ids currently sitting in "Removed · Undo", live. */
export function usePendingDeletes(): ReadonlySet<string> {
  return useSyncExternalStore(subscribe, getSnapshot);
}

export function isPendingDelete(wordId: string): boolean {
  return pending.has(wordId);
}

/** Sends the DELETE now instead of waiting out the window. Called by the
 *  timer itself, and by anything that has to leave before the timer would
 *  fire (`useFlushPendingDeletesOnLeave`, the tab closing). Safe to call more
 *  than once for the same id — only the first call still finds it
 *  unflushed. */
function flush(wordId: string): void {
  const entry = pending.get(wordId);
  if (!entry || entry.flushed) return;
  entry.flushed = true;
  clearTimeout(entry.timer);
  void vocabularyApi
    .forget(wordId)
    .catch((e: unknown) => toast(getErrorMessage(e)))
    .finally(() => {
      pending.delete(wordId);
      publish();
      void queryClient.invalidateQueries({ queryKey: vocabularyWordsKey });
      void queryClient.invalidateQueries({ queryKey: wordDetailKey(wordId) });
      void queryClient.invalidateQueries({
        queryKey: ["vocabulary", "practice", "summary"],
      });
    });
}

/** Marks one word for deletion. Idempotent — pressing Delete again on a row
 *  already in the window (there is no button left to press, but nothing here
 *  assumes that) restarts nothing and does not queue a second request. */
export function scheduleDelete(wordId: string): void {
  if (pending.has(wordId)) return;
  const timer = setTimeout(() => flush(wordId), GRACE_MS);
  pending.set(wordId, { timer, flushed: false });
  publish();
}

/** Undo. Only ever clears the timer — the DELETE was never sent, so there is
 *  nothing on the server to put back. */
export function undoDelete(wordId: string): void {
  const entry = pending.get(wordId);
  if (!entry || entry.flushed) return;
  clearTimeout(entry.timer);
  pending.delete(wordId);
  publish();
}

function flushAll(): void {
  for (const wordId of pending.keys()) flush(wordId);
}

let hosts = 0;

/** Registers the words list or the word page as somewhere "Removed · Undo"
 *  could currently be shown, for as long as it's mounted.
 *
 *  On leaving, a delay rather than an immediate check: the words list and
 *  the word page are both hosts, and navigating from one to the other
 *  unmounts one and mounts the other in the same beat — checking the count
 *  synchronously in the unmounting page's own cleanup would read zero a
 *  moment before the arriving page registers. Leaving genuinely (anywhere
 *  outside these two pages, or the tab closing) is the case this is for:
 *  nothing is left that could ever show the row again, so the delete that
 *  row promised happens now rather than silently never. */
export function useFlushPendingDeletesOnLeave(): void {
  useEffect(() => {
    hosts += 1;
    window.addEventListener("beforeunload", flushAll);
    return () => {
      hosts -= 1;
      window.removeEventListener("beforeunload", flushAll);
      setTimeout(() => {
        if (hosts === 0) flushAll();
      }, 50);
    };
  }, []);
}
