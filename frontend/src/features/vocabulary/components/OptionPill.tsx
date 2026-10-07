import { cn } from "@/lib/utils";

/** One choice of a `radiogroup` of pills — the settings page's exercise type
 *  and accent. The caller supplies the group. With `toggle` it is a plain
 *  `aria-pressed` button instead (On the go's order, where the arrow keys
 *  are not the group's to take). */
export function OptionPill({
  on,
  toggle = false,
  disabled = false,
  onClick,
  children,
}: {
  on: boolean;
  toggle?: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role={toggle ? undefined : "radio"}
      aria-checked={toggle ? undefined : on}
      aria-pressed={toggle ? on : undefined}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "rounded-full px-3 py-1 text-xs font-medium transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50",
        on
          ? "bg-primary/20 text-primary-ink"
          : "bg-surface-hover text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}
