/**
 * The voocab logo, rendered as a favicon whose colors come from the live theme
 * tokens (--card for the rounded square, --primary for the mark). Call after a
 * theme is applied to <html> so getComputedStyle reflects the new values.
 *
 * Geometry mirrors public/voocab.svg, which serves as the static fallback shown
 * before JS runs.
 */
const LOGO_VIEWBOX = "0 0 512 533";
const LOGO_PATH =
  "M200.84 457L83.6523 133.025H193.76L305.82 457H200.84ZM319.004 447.234L270.42 304.656L322.666 133.025H431.064L319.004 447.234Z";

export function updateFavicon() {
  const styles = getComputedStyle(document.documentElement);
  const surface = styles.getPropertyValue("--card").trim() || "#2c2e31";
  const mark = styles.getPropertyValue("--primary").trim() || "#e2b714";

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="512" height="533" viewBox="${LOGO_VIEWBOX}" fill="none"><rect y="21" width="512" height="512" rx="156" fill="${surface}"/><path d="${LOGO_PATH}" fill="${mark}"/></svg>`;
  const href = `data:image/svg+xml,${encodeURIComponent(svg)}`;

  let link = document.querySelector<HTMLLinkElement>('link[rel~="icon"]');
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    document.head.appendChild(link);
  }
  link.type = "image/svg+xml";
  link.href = href;
}
