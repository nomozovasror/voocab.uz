import { PracticePage } from "@/features/paper/PracticePage";
import { READING } from "@/features/paper/skill";

/**
 * What a learner can read, and what they have done with it.
 *
 * The same page the listening catalogue is, asked about the other paper — so
 * the search, the filters, the suggestion block, the sticky column and every
 * rule written into them arrive here by construction rather than by being
 * built again. What differs is in the descriptor: three passages rather than
 * four parts, its own word for a section, and — until reading's collections
 * and drills exist — one list rather than three.
 */
export default function ReadingPage() {
  return <PracticePage skill={READING} />;
}
