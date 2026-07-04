import { useEffect, useState } from "react";

/** True once the window is scrolled past `threshold` px. Used to toggle the
 *  navbar's frosted-glass state (transparent at top → blurred on scroll). */
export function useScrolled(threshold = 8): boolean {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > threshold);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [threshold]);

  return scrolled;
}
