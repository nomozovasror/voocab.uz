import { cn } from "@/lib/utils";
import type { User } from "@/auth/types";

/** Telegram avatar if present, otherwise a themed initial. */
export function UserAvatar({
  user,
  className,
}: {
  user: User;
  className?: string;
}) {
  if (user.avatar_url) {
    return (
      <img
        src={user.avatar_url}
        alt=""
        className={cn("rounded-full object-cover", className)}
      />
    );
  }
  return (
    <span
      className={cn(
        "flex items-center justify-center rounded-full bg-primary/10 font-semibold text-primary",
        className,
      )}
    >
      {user.display_name.charAt(0).toUpperCase()}
    </span>
  );
}
