import { docGaps, type DocBlock } from "@/features/listening/form-syntax";
import type { AudioSegment } from "@/features/listening/types";

/**
 * Checking an author's audio marks against the transcript.
 *
 * A mark says "this is where the answer is said". That claim is checkable:
 * the transcript of those seconds either contains the answer or it doesn't.
 * When it doesn't, it is worth saying so — quietly, because there is a
 * perfectly good reason for it (a spoken number written as digits, a
 * paraphrase, an ASR mishearing) as well as a bad one (the mark is simply on
 * the wrong line).
 */

export interface AnswerMark {
  gapId: string;
  number: number;
  startMs: number;
  endMs: number;
  answers: string[];
}

export interface MarkCheck {
  /** The answer is said within the marked seconds. */
  found: boolean;
  /** Where it is said instead, if anywhere — so the author can go and look. */
  heardAtMs: number | null;
}

function normalize(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9'\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Every gap the author has marked, with the answers to check against. */
export function answerMarks(doc: DocBlock[]): AnswerMark[] {
  return docGaps(doc).flatMap((gap) => {
    const answers = gap.answers.map((a) => a.trim()).filter(Boolean);
    if (gap.replayStartMs == null || gap.replayEndMs == null) return [];
    if (answers.length === 0) return [];
    return [
      {
        gapId: gap.id,
        number: gap.number,
        startMs: gap.replayStartMs,
        endMs: gap.replayEndMs,
        answers,
      },
    ];
  });
}

/** The words spoken between two timestamps, as one normalized string. Word
 *  timings are used where the ASR gave them, since a segment can be much
 *  longer than the mark and would make almost any mark look correct. */
function spokenBetween(
  segments: AudioSegment[],
  startMs: number,
  endMs: number,
): string {
  const words: string[] = [];
  for (const segment of segments) {
    if (segment.end_ms <= startMs || segment.start_ms >= endMs) continue;
    if (segment.words.length > 0) {
      for (const word of segment.words) {
        const middle = (word.start_ms + word.end_ms) / 2;
        if (middle >= startMs && middle <= endMs) words.push(word.word);
      }
    } else {
      words.push(segment.text);
    }
  }
  return normalize(words.join(" "));
}

/** Where an answer is first heard in the whole recording, or null. */
function firstHeardAt(
  segments: AudioSegment[],
  answer: string,
): number | null {
  const needle = normalize(answer);
  if (!needle) return null;
  for (const segment of segments) {
    if (!normalize(segment.text).includes(needle)) continue;
    // Narrow to the word that starts the match where we can, so the caller
    // points at the phrase rather than at the top of a long line.
    const head = needle.split(" ")[0];
    const word = segment.words.find((w) => normalize(w.word) === head);
    return word ? word.start_ms : segment.start_ms;
  }
  return null;
}

export function checkMarks(
  doc: DocBlock[],
  segments: AudioSegment[],
): Map<string, MarkCheck> {
  const checks = new Map<string, MarkCheck>();
  if (segments.length === 0) return checks;

  for (const mark of answerMarks(doc)) {
    const spoken = spokenBetween(segments, mark.startMs, mark.endMs);
    const found = mark.answers.some((answer) => {
      const needle = normalize(answer);
      return needle.length > 0 && spoken.includes(needle);
    });
    checks.set(mark.gapId, {
      found,
      heardAtMs: found
        ? null
        : (mark.answers
            .map((a) => firstHeardAt(segments, a))
            .find((ms) => ms != null) ?? null),
    });
  }
  return checks;
}


export interface AnswerOccurrence {
  answer: string;
  /** The range to mark: padded, so replaying it doesn't clip the answer. */
  startMs: number;
  endMs: number;
  /** When the word itself is said, unpadded. Navigation and the label use
   *  this: the padding reaches back into the previous line often enough that
   *  jumping to `startMs` lands on the wrong one. */
  wordStartMs: number;
  /** The line it was found in, so the author can recognise it before
   *  committing to a timestamp they can't read. */
  context: string;
}

/** A little air either side of the words themselves, so replaying the mark
 *  doesn't clip the answer or drop the reader straight into the middle of a
 *  sentence. */
const SUGGESTION_PAD_MS = 700;

/** Where in the transcript each accepted answer is actually said. Used to
 *  offer the author the timestamp rather than make them hunt for it — the
 *  answer is already written down, and the transcript already knows when it
 *  was said, so asking them to find it again is work the machine can do. */
export function findAnswerOccurrences(
  segments: AudioSegment[],
  answers: string[],
  limit = 6,
): AnswerOccurrence[] {
  const found: AnswerOccurrence[] = [];

  for (const answer of answers.map((a) => a.trim()).filter(Boolean)) {
    const needleWords = normalize(answer).split(" ").filter(Boolean);
    if (needleWords.length === 0) continue;

    for (const segment of segments) {
      const words = segment.words;
      if (words.length > 0) {
        for (let i = 0; i + needleWords.length <= words.length; i++) {
          const window = words.slice(i, i + needleWords.length);
          const matches = window.every(
            (w, j) => normalize(w.word) === needleWords[j],
          );
          if (!matches) continue;
          found.push({
            answer,
            startMs: Math.max(0, window[0].start_ms - SUGGESTION_PAD_MS),
            endMs: window[window.length - 1].end_ms + SUGGESTION_PAD_MS,
            wordStartMs: window[0].start_ms,
            context: segment.text.trim(),
          });
        }
      } else if (normalize(segment.text).includes(normalize(answer))) {
        // No word timings for this line: the line itself is the best we can
        // honestly offer.
        found.push({
          answer,
          startMs: segment.start_ms,
          endMs: segment.end_ms,
          wordStartMs: segment.start_ms,
          context: segment.text.trim(),
        });
      }
      if (found.length >= limit) return found;
    }
  }
  return found;
}
