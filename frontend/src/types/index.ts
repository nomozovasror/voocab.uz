/** Shared, app-wide types. Feature-specific types live in features/<x>/types.ts. */

export interface User {
  id: string;
  email: string;
  displayName: string;
}

/** Standard error shape returned by the FastAPI backend. */
export interface ApiErrorBody {
  detail: string;
}
