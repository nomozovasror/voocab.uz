import { Link } from "react-router-dom";

/**
 * One line, on every page: the attribution the NGSL family and Open English
 * WordNet's licences require (`brief-lexicon.md` §9). Small on purpose — the
 * obligation is real but nobody visiting `/reading` came to read about it,
 * so this is the whole footer rather than a block of links competing with
 * the page above it.
 */
export function Footer() {
  return (
    <footer className="mx-auto w-full max-w-7xl px-4 py-6 text-center sm:px-6 lg:px-8">
      <Link
        to="/licences"
        className="text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:rounded-sm focus-visible:outline-none"
      >
        Data sources and licences
      </Link>
    </footer>
  );
}
