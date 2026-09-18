import { StudioPaperEditorPage } from "@/pages/studio/StudioPaperEditorPage";
import { LISTENING } from "@/features/paper/skill";

/** Writing a listening material. The editor is
 *  `pages/studio/StudioPaperEditorPage` — one workspace for both papers,
 *  differing only in what the left pane shows — and this says which. */
export default function StudioListeningEditorPage() {
  return <StudioPaperEditorPage skill={LISTENING} />;
}
