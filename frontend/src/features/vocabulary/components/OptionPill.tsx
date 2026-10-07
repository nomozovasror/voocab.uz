import { cn } from "@/lib/utils";

/** One choice of a `radiogroup` of pills — the settings page's exercise type
 *  and accent, and On the go's order. The caller supplies the group. */
export function OptionPill({
  on,
  disabled = false,
  onClick,
  children,
}: {
  on: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={on}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "rounded-full px-3 py-1 text-xs font-medium transition-colors duration-fast focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50",
        on
          ? "bg-primary/20 text-primary"
          : "bg-surface-hover text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}
