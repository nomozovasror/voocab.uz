import { StudioPaperListPage } from "@/pages/studio/StudioPaperListPage";
import { READING } from "@/features/paper/skill";

/** The author's reading materials — the same table, asked about the other
 *  paper. */
export default function StudioReadingListPage() {
  return <StudioPaperListPage skill={READING} />;
}
