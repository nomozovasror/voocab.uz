import { Check, Palette } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { useTheme } from "./useTheme";

/**
 * Choosing a theme.
 *
 * It lives in the account menu (`ThemeSubmenu`) rather than as a control of
 * its own in the header, and that is a decision about the header rather than
 * about themes. The bar is three floating islands and a middle that pages
 * dock things into; a second button on the right pushed that island out past
 * the space the middle needed, and the thing being crowded out — a player, a
 * search field — is used constantly, while a theme is chosen about twice.
 *
 * A signed-out visitor has no account menu, so there it stays a control of
 * its own, icon only.
 */

/** The three swatches, shared by both routes to them. */
function ThemeChoices() {
  const { theme, themes, setTheme } = useTheme();
  return (
    <>
      {themes.map((t) => (
        <DropdownMenuItem
          key={t.id}
          onSelect={() => setTheme(t.id)}
          className="gap-2"
        >
          <span
            className="flex size-4 shrink-0 items-center justify-center rounded-full border border-border"
            style={{ background: t.preview.background }}
          >
            <span
              className="size-2 rounded-full"
              style={{ background: t.preview.primary }}
            />
          </span>
          <span className="flex-1">{t.label}</span>
          <Check
            className={cn(
              "size-4",
              t.id === theme.id ? "opacity-100" : "opacity-0",
            )}
          />
        </DropdownMenuItem>
      ))}
    </>
  );
}

/** Inside the account menu. A submenu rather than three more rows: the menu
 *  is a list of things you DO, and the theme is a setting — folding it in flat
 *  would make a rarely-used choice the tallest thing in it. */
export function ThemeSubmenu() {
  const { theme } = useTheme();
  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger className="gap-2">
        <Palette className="size-4" />
        <span className="flex-1">Theme</span>
        {/* What it is set to, said here, so the submenu is somewhere you go to
            change it rather than somewhere you go to find out. */}
        <span className="text-xs text-muted-foreground">{theme.label}</span>
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent className="w-52">
        <ThemeChoices />
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}

/** Standalone, for a visitor with no account menu to put it in. Icon only:
 *  the label is what made this control wide, and the island it sits in has to
 *  leave the middle of the bar alone. */
export function ThemeSwitcher() {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="icon"
          aria-label="Change theme"
          title="Change theme"
        >
          <Palette />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuLabel>Theme</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <ThemeChoices />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
