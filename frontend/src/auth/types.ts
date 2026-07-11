/** The authenticated user, as returned by GET /api/auth/me. */
export interface User {
  id: string;
  display_name: string;
  email: string | null;
  avatar_url: string | null;
}
