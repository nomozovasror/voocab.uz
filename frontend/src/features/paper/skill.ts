import { BookOpen, Headphones } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ListMode } from "@/features/listening/practice";

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
  /** The page's own name, for anything that cannot see the header. */
  title: string;
  /** What one part of it is called, to a candidate: in a sentence, and
   *  capitalised where it begins a label ("Passage 2", "All passages"). */
  part: { one: string; many: string; title: string };
  /** How many parts a whole paper has. The same number the server calls
   *  `full_test_parts`. */
  fullParts: number;
  icon: LucideIcon;
  /** Where the studio's editor for this paper lives. */
  studioPath: string;
  /** Which lists this paper has, in the order the tabs offer them.
   *
   *  Reading has only its materials until its collections and drills are
   *  built. A tab that is always empty is worse than no tab: it is an offer
   *  the page cannot keep, and a reader who takes it up learns the section is
   *  broken rather than unbuilt. */
  modes: ListMode[];
  /** Where the page's tab choice is remembered, per paper — the two are
   *  different questions and one key would answer both wrong. */
  tabKey: string;
}

export const LISTENING: Skill = {
  id: "listening",
  basePath: "/listening",
  name: "listening",
  title: "Listening",
  part: { one: "part", many: "parts", title: "Part" },
  fullParts: 4,
  icon: Headphones,
  studioPath: "/studio/listening",
  modes: ["materials", "courses", "drills"],
  tabKey: "voocab-listening-tab",
};

export const READING: Skill = {
  id: "reading",
  basePath: "/reading",
  name: "reading",
  title: "Reading",
  // "Reading Passage 1", never "Part 1" — it is what the paper prints, and
  // the difference is the whole of what a reading part is.
  part: { one: "passage", many: "passages", title: "Passage" },
  // Three, not four: forty questions over three passages. One number for
  // both papers would call every complete reading paper an excerpt, which is
  // the one thing the "full test" filter exists to tell apart.
  fullParts: 3,
  icon: BookOpen,
  studioPath: "/studio/reading",
  // Materials only, for now. Reading's courses and drills are real work that
  // has not been done — see the plan — and a Courses tab over an empty shelf
  // would say they had.
  modes: ["materials"],
  tabKey: "voocab-reading-tab",
};

export const SKILLS = { listening: LISTENING, reading: READING } as const;
