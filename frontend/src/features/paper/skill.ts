import { BookOpen, Headphones } from "lucide-react";
import type { LucideIcon } from "lucide-react";

/**
 * Which paper a page is about, as a value.
 *
 * Listening and reading are the same machinery over different material: one
 * catalogue, one take screen, one review, one editor. What actually differs
 * between them is a handful of facts — where their pages live, which API
 * prefix answers about them, what a part is called, how many parts make a
 * whole paper — and those are data rather than code.
 *
 * So pages take a descriptor instead of being written twice. It is the
 * client's half of `backend/app/api/papers.py`, which mounts one router per
 * skill for the same reason.
 */
export interface Skill {
  /** What `Material.type` says, and what the API prefix is. */
  id: "listening" | "reading";
  /** Where this paper's pages live: `/listening`, `/reading`. */
  basePath: string;
  /** In a sentence, lower case: "Back to reading". */
  name: string;
  /** What one part of it is called, to a candidate. */
  part: { one: string; many: string };
  /** How many parts a whole paper has. The same number the server calls
   *  `full_test_parts`. */
  fullParts: number;
  icon: LucideIcon;
  /** Where the studio's editor for this paper lives. */
  studioPath: string;
}

export const LISTENING: Skill = {
  id: "listening",
  basePath: "/listening",
  name: "listening",
  part: { one: "part", many: "parts" },
  fullParts: 4,
  icon: Headphones,
  studioPath: "/studio/listening",
};

export const READING: Skill = {
  id: "reading",
  basePath: "/reading",
  name: "reading",
  // "Reading Passage 1", never "Part 1" — it is what the paper prints, and
  // the difference is the whole of what a reading part is.
  part: { one: "passage", many: "passages" },
  // Three, not four: forty questions over three passages. One number for
  // both papers would call every complete reading paper an excerpt, which is
  // the one thing the "full test" filter exists to tell apart.
  fullParts: 3,
  icon: BookOpen,
  studioPath: "/studio/reading",
};

export const SKILLS = { listening: LISTENING, reading: READING } as const;
