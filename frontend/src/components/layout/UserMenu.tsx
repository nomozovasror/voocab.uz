import { LogOut, User as UserIcon } from "lucide-react";
import { useNavigate } from "react-router-dom";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { UserAvatar } from "@/auth/UserAvatar";
import { useAuthActions } from "@/auth/useAuthActions";
import type { User } from "@/auth/types";

/** Header account control: avatar + name, with a sign-out menu. */
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
          <span className="hidden max-w-32 truncate text-sm font-medium text-foreground sm:inline">
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
