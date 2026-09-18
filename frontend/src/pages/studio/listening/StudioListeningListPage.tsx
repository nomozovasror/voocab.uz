import { StudioPaperListPage } from "@/pages/studio/StudioPaperListPage";
import { LISTENING } from "@/features/paper/skill";

/** The author's listening materials. The page is
 *  `pages/studio/StudioPaperListPage` — one table for both papers — and this
 *  says which. */
export default function StudioListeningListPage() {
  return <StudioPaperListPage skill={LISTENING} />;
}
