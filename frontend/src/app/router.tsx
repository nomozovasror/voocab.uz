import type { ComponentType } from "react";
import { Navigate, createBrowserRouter, redirect } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";
import { StudioLayout } from "@/components/studio/StudioLayout";
import { RequireAuth } from "@/auth/RequireAuth";
import { PageLoader } from "@/components/ui/spinner";

/**
 * A code-split page, plus what stands in for it during a cold load.
 *
 * Route-level `lazy:` leaves the router uninitialised until the chunk lands,
 * and a matched tree with NO HydrateFallback anywhere is truncated to the
 * root and rendered as `null` — the header included. A reload used to show a
 * blank page for the length of the import.
 *
 * Declared on the leaf and never on the root: a fallback renders *instead of*
 * its own route's element, so on the root it would replace <Layout/> and take
 * the chrome down with it. On the leaf, the tree above still renders and the
 * fallback simply fills the <Outlet/>.
 *
 * Deliberately PageLoader rather than each page's skeleton: a HydrateFallback
 * is a static component reference, so it is imported eagerly — pointing it at
 * a page's own skeleton would pull that page into the entry chunk and undo
 * the split. PageLoader is already in the entry graph via RequireAuth.
 *
 * Only ever seen on first entry or reload; client-side navigation is covered
 * by <RouteProgress/>.
 */
function page(load: () => Promise<{ default: ComponentType }>) {
  return {
    lazy: async () => ({ Component: (await load()).default }),
    HydrateFallback: PageLoader,
  };
}

/**
 * Central route config. Page components are lazy-loaded so each route is its
 * own chunk (code splitting). Add a section by dropping a page under
 * src/pages/<name>/ and registering a lazy child here.
 *
 * Routes that need a session live under the pathless <RequireAuth> layout route.
 */
export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      {
        index: true,
        ...page(() => import("@/pages/home/HomePage")),
      },
      {
        path: "reading",
        ...page(() => import("@/pages/reading/ReadingPage")),
      },
      {
        path: "vocabulary",
        ...page(() => import("@/pages/vocabulary/VocabularyPage")),
      },
      {
        path: "login",
        ...page(() => import("@/pages/login/LoginPage")),
      },
      // --- Protected ---
      {
        element: <RequireAuth />,
        children: [
          {
            path: "listening",
            ...page(() => import("@/pages/listening/ListeningPage")),
          },
          {
            // Before ``listening/:id``, or an attempt id would be read as a
            // material id and the take page would fetch a material that
            // doesn't exist.
            path: "listening/attempts/:attemptId",
            ...page(() => import("@/pages/listening/ListeningResultsPage")),
          },
          {
            path: "listening/:id",
            ...page(() => import("@/pages/listening/ListeningTakePage")),
          },
          {
            path: "dictation",
            ...page(() => import("@/pages/dictation/DictationPage")),
          },
          {
            path: "profile",
            ...page(() => import("@/pages/profile/ProfilePage")),
          },
          // /materials, /materials/new and /materials/:id/edit used to live
          // here: authoring for dictation, whose learner side was never
          // built. A door to a room with no floor. Closed rather than
          // redirected — there is nowhere to redirect to, and dictation is
          // not deleted, just not open yet.
        ],
      },
      // Anything else under "/". Without it react-router raises the path as
      // an error and renders its own developer screen; with it, a stale
      // bookmark lands on a page wearing the app's own chrome.
      {
        path: "*",
        ...page(() => import("@/pages/NotFoundPage")),
      },
    ],
  },
  // --- Studio (listening authoring) ---
  // Own layout/nav (§3.10, §6), but nested under the same <RequireAuth>
  // session gate as the rest of the protected app.
  {
    path: "/studio",
    element: <RequireAuth />,
    children: [
      {
        element: <StudioLayout />,
        children: [
          {
            index: true,
            ...page(() => import("@/pages/studio/StudioDashboardPage")),
          },
          // Where the listening studio used to live, before it was rebuilt
          // around the editor at /studio/listening. The pages are gone; the
          // paths stay as redirects because they are in people's history and
          // in every link written while they existed, and because landing on
          // the material you asked for beats landing on a 404 that says the
          // studio moved.
          {
            path: "materials",
            element: <Navigate to="/studio/listening" replace />,
          },
          {
            path: "materials/new",
            element: <Navigate to="/studio/listening/new" replace />,
          },
          {
            // A loader rather than a <Navigate> element, only because this one
            // has to read the id: the redirect happens before anything
            // renders, and the route needs no component of its own.
            path: "materials/:id/edit",
            loader: ({ params }) =>
              redirect(
                params.id ? `/studio/listening/${params.id}` : "/studio/listening",
              ),
            Component: () => null,
            // A pending loader leaves the router uninitialised exactly as a
            // pending `lazy` does, so this route blanks on a cold load too.
            HydrateFallback: PageLoader,
          },
          {
            path: "listening",
            ...page(() => import("@/pages/studio/listening/StudioListeningListPage")),
          },
          {
            path: "listening/new",
            ...page(() => import("@/pages/studio/listening/StudioListeningEditorPage")),
          },
          {
            path: "listening/:id",
            ...page(() => import("@/pages/studio/listening/StudioListeningEditorPage")),
          },
          // The studio's own, so a wrong address inside it keeps the studio's
          // chrome rather than dropping the author back into the app shell.
          {
            path: "*",
            ...page(() => import("@/pages/NotFoundPage")),
          },
        ],
      },
    ],
  },
]);
