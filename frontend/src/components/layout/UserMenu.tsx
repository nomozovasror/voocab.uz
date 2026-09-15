import { LogOut, User as UserIcon, Mic } from "lucide-react";
import { useNavigate } from "react-router-dom";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ThemeSubmenu } from "@/theme/ThemeSwitcher";
import { UserAvatar } from "@/auth/UserAvatar";
import { useAuthActions } from "@/auth/useAuthActions";
import type { User } from "@/auth/types";

/**
 * Header account control: avatar + name, with a menu behind it.
 *
 * It also carries the theme (see ThemeSwitcher). The header's right island
 * used to hold two controls, and between them they took enough of the bar
 * that the middle — where pages dock a player or a search field — had nowhere
 * left to go. One trigger on each side leaves the middle to the thing that is
 * actually used while working.
 */
export function UserMenu({ user }: { user: User }) {
  const { logout } = useAuthActions();
  const navigate = useNavigate();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className="flex items-center gap-2 rounded-full py-1 pr-2 pl-1 transition-colors hover:bg-foreground/5 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          aria-label="Account menu"
        >
          <UserAvatar user={user} className="size-7 text-xs" />
          {/* The name waits for a wide window. Below that the avatar says
              whose account this is on its own, and the room it would take is
              room the docked control in the middle needs more. */}
          <span className="hidden max-w-32 truncate text-sm font-medium text-foreground lg:inline">
            {user.display_name}
          </span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="flex items-center gap-2">
          <UserAvatar user={user} className="size-8 text-sm" />
          <div className="min-w-0">
            <div className="truncate font-medium">{user.display_name}</div>
            <div className="truncate text-xs font-normal text-muted-foreground">
              {user.email ?? "Telegram account"}
            </div>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={() => navigate("/profile")}
          className="gap-2"
        >
          <UserIcon className="size-4" />
          Profile
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={() => navigate("/studio")}
          className="gap-2"
        >
          <Mic className="size-4" />
          Studio
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <ThemeSubmenu />
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={() => void logout()}
          className="gap-2 text-destructive focus:text-destructive"
        >
          <LogOut className="size-4" />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
