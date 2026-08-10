import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Link } from "react-router-dom";

/**
 * Studio breadcrumbs live in the layout header, but their content belongs to
 * the page (the editor's last crumb is the material's title, which only the
 * page knows). A tiny context lets each page declare its own trail while the
 * header stays the single place it's rendered.
 */
export interface Crumb {
  label: string;
  /** Omit on the last crumb — the page you're already on isn't a link. */
  to?: string;
}

const ROOT: Crumb[] = [{ label: "studio", to: "/studio" }];

const BreadcrumbContext = createContext<{
  crumbs: Crumb[];
  setCrumbs: (crumbs: Crumb[]) => void;
} | null>(null);

export function StudioBreadcrumbProvider({ children }: { children: ReactNode }) {
  const [crumbs, setCrumbs] = useState<Crumb[]>(ROOT);
  const value = useMemo(() => ({ crumbs, setCrumbs }), [crumbs]);
  return (
    <BreadcrumbContext.Provider value={value}>
      {children}
    </BreadcrumbContext.Provider>
  );
}

/**
 * Declare the trail for the current page. `studio` is prepended for you, so
 * pass only what comes after it: `useStudioCrumbs([{ label: "listening" }])`.
 */
export function useStudioCrumbs(tail: Crumb[]) {
  const ctx = useContext(BreadcrumbContext);
  const setCrumbs = ctx?.setCrumbs;
  // Compare by value: callers build the array inline, so a reference check
  // would re-run (and re-render) on every pass.
  const key = JSON.stringify(tail);

  useEffect(() => {
    if (!setCrumbs) return;
    setCrumbs([...ROOT, ...(JSON.parse(key) as Crumb[])]);
    return () => setCrumbs(ROOT);
  }, [key, setCrumbs]);
}

export function StudioBreadcrumbs() {
  const crumbs = useContext(BreadcrumbContext)?.crumbs ?? ROOT;

  return (
    <nav
      aria-label="Breadcrumb"
      className="flex min-w-0 items-center gap-1.5 font-mono text-xs text-muted-foreground"
    >
      {crumbs.map((crumb, i) => {
        const last = i === crumbs.length - 1;
        return (
          <span key={`${crumb.label}-${i}`} className="flex min-w-0 items-center gap-1.5">
            {i > 0 && (
              <span aria-hidden className="text-muted-foreground/50">
                /
              </span>
            )}
            {crumb.to && !last ? (
              <Link
                to={crumb.to}
                className="transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                {crumb.label}
              </Link>
            ) : (
              <span
                className={cnLast(last)}
                aria-current={last ? "page" : undefined}
              >
                {crumb.label}
              </span>
            )}
          </span>
        );
      })}
    </nav>
  );
}

function cnLast(last: boolean): string {
  return last ? "truncate text-foreground" : "truncate";
}
