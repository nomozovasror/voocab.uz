/** The authenticated user, as returned by GET /api/auth/me. */
export interface User {
  id: string;
  display_name: string;
  email: string | null;
  avatar_url: string | null;
  /** Gates Studio's admin review tab on the client — a display fact only;
   *  every endpoint underneath enforces the same flag independently on the
   *  server (`app.api.deps.AdminUser`). */
  is_admin: boolean;
}
