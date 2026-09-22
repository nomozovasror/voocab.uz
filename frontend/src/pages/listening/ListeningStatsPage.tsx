import { ArrowLeft } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { SKILLS } from "@/features/paper/skill";

/**
 * Full statistics — the room the sidebar's numbers don't fit in.
 *
 * One stub for both papers, which paper it is taken from the path it was
 * reached by. It was listening's alone, and the sidebar on the reading page
 * linked to it anyway — so somebody reading about their reading was offered
 * "Back to listening", which is the page telling them they are somewhere
 * they are not.
 *
 * A stub, and deliberately an honest one. The sidebar links here from two
 * places ("Review your mistakes", "Full statistics"), and a link that 404s is
 * worse than no link: the reader can't tell a missing page from a broken app.
 * So this says which it is.
 *
 * What belongs here, once it is built (from the sidebar brief): the mistake
 * breakdown with real examples — "you wrote `accomodation`, the answer was
 * `accommodation`" — the question-type profile as a radar with the platform
 * average laid over it, accuracy by question position (which is where fatigue
 * shows), the part and type splits, the replay-count trend, and the
 * distractor analysis that multiple choice needs and spelling analysis can't
 * give it.
 *
 * No band score. The IELTS scale is calibrated to a 40-question paper, and
 * quoting a band off a six-question Part 1 is precision that isn't there.
 */
export default function PaperStatsPage() {
  const { pathname } = useLocation();
  const skill = pathname.startsWith(SKILLS.reading.basePath)
    ? SKILLS.reading
    : SKILLS.listening;
  return (
    <div className="mx-auto w-full max-w-2xl py-16">
      <h1 className="text-2xl font-semibold text-foreground">Full statistics</h1>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
        Not built yet. This is where the detail behind the sidebar will
        live — your mistakes with the actual words you wrote, how you do by
        question type against everyone else, and where in a paper your accuracy
        starts to drop.
      </p>
      <Link
        to={skill.basePath}
        className="mt-6 inline-flex items-center gap-1.5 text-sm text-primary transition-colors hover:underline"
      >
        <ArrowLeft className="size-3.5" aria-hidden />
        Back to {skill.name}
      </Link>
    </div>
  );
}
