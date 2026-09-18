import { PracticePage } from "@/features/paper/PracticePage";
import { LISTENING } from "@/features/paper/skill";

/**
 * What a learner can listen to, and what they have done with it.
 *
 * The page itself is `features/paper/PracticePage` — the catalogue, its
 * filters, the suggestion block and the statistics column are the same page
 * on both papers, and this says which one. See `features/paper/CLAUDE.md`.
 */
export default function ListeningPage() {
  return <PracticePage skill={LISTENING} />;
}
