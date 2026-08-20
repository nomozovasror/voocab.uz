import { useNavigation } from "react-router-dom";
import { cn } from "@/lib/utils";

/**
 * A hairline across the top while the next page's code arrives.
 *
 * Every route here is code-split with react-router's route-level `lazy:`,
 * which the router resolves BEFORE rendering. So clicking a material leaves
 * the old page on screen, frozen and unmarked, for as long as the import
 * takes. Nothing else in the app can speak for that moment: the page being
 * navigated to has not been downloaded, so it cannot draw its own loading
 * state, and the page being left has no idea it is leaving.
 *
 * Indeterminate on purpose. The router cannot report how far along a dynamic
 * import is, so the bar eases toward the right edge and never arrives — it is
 * removed when the page paints, not completed. Better an honest crawl than a
 * progress bar that invents a percentage.
 *
 * Self-limiting: once a chunk resolves, react-router clears that route's
 * `lazy`, so a second visit has nothing to load and never enters a loading
 * state. The bar appears on genuinely cold navigations and nowhere else.
 *
 * Must live inside the router — `useNavigation` reads the data-router
 * context, which is why this sits in the layouts and not in App.
 */
export function RouteProgress() {
  const navigation = useNavigation();
  const busy = navigation.state !== "idle";

  return (
    <div
      aria-hidden
      className={cn(
        // Above the sticky headers (z-30), below dialogs and the connection
        // gate (z-50). Never intercepts a click.
        "pointer-events-none fixed inset-x-0 top-0 z-40 h-0.5 overflow-hidden",
        "transition-opacity duration-200 ease-out",
        busy ? "opacity-100" : "opacity-0",
      )}
    >
      {busy && (
        // Keyed by the destination, so each navigation restarts the crawl
        // rather than resuming where the last one gave up.
        <span
          key={navigation.location?.key ?? "nav"}
          className="route-progress block h-full w-full origin-left bg-primary"
        />
      )}
    </div>
  );
}
