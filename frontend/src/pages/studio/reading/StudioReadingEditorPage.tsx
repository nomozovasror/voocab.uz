import { StudioPaperEditorPage } from "@/pages/studio/StudioPaperEditorPage";
import { READING } from "@/features/paper/skill";

/** Writing a reading material — the same workspace, with the passage where
 *  the recording is. */
export default function StudioReadingEditorPage() {
  return <StudioPaperEditorPage skill={READING} />;
}
