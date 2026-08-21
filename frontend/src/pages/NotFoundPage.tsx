import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

/**
 * Nothing at this address.
 *
 * Without it react-router raises the path as an error and renders its own
 * default screen — "Unexpected Application Error!" over a note addressed to
 * the developer. That was true for every mistyped URL in the app; closing
 * /materials is what made it a page somebody could actually arrive at, from
 * a bookmark or from their own history.
 *
 * Deliberately says nothing about WHY. A visitor who followed an old link to
 * a section that was withdrawn and a visitor who fat-fingered the address
 * need the same thing, and guessing between them out loud gets it wrong half
 * the time.
 */
export default function NotFoundPage() {
  return (
    <div className="mx-auto max-w-3xl py-16">
      <p className="font-mono text-xs tracking-[0.14em] text-muted-foreground uppercase">
        404
      </p>
      <h1 className="mt-2 text-lg font-semibold text-foreground">
        there&apos;s nothing at this address.
      </h1>
      <p className="mt-1 text-sm text-muted-foreground">
        the link may be out of date, or the address mistyped.
      </p>
      <Link
        to="/"
        className="mt-6 inline-flex items-center gap-1.5 text-sm text-primary transition-colors hover:underline"
      >
        <ArrowLeft className="size-4" />
        back to voocab
      </Link>
    </div>
  );
}
