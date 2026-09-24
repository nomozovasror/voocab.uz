import type { ComponentType } from "react";
import { Navigate, createBrowserRouter, redirect } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";
import { StudioLayout } from "@/components/studio/StudioLayout";
import { StudioTabsLayout } from "@/components/studio/StudioTabs";
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
      // Practice home first: `/vocabulary` used to be the list, and is now
      // the spaced-repetition module's front door — due count, Start,
      // totals. The list survives unchanged at its own path below, for
      // stage 2 to rebuild.
      {
        path: "vocabulary",
        ...page(() => import("@/pages/vocabulary/VocabularyHomePage")),
      },
      {
        path: "vocabulary/words",
        ...page(() => import("@/pages/vocabulary/VocabularyPage")),
      },
      {
        path: "vocabulary/practice",
        ...page(() => import("@/pages/vocabulary/VocabularyPracticePage")),
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
          // Reading, and every one of these has to stay ABOVE
          // ``reading/:id`` for the same reason the listening ones do: an
          // attempt id read as a material id fetches a material that doesn't
          // exist, and "statistics" is not a material either.
          {
            path: "reading",
            ...page(() => import("@/pages/reading/ReadingPage")),
          },
          {
            path: "reading/attempts/:attemptId",
            ...page(() => import("@/pages/reading/ReadingResultsPage")),
          },
          {
            // Above ``reading/:id`` for the reason every one of these is:
            // "statistics" is not a material id. The page is the same stub
            // listening reaches, and it reads which paper it is about off
            // the path — the sidebar linked here from the reading page long
            // before this route existed, and landed the reader in the other
            // paper.
            path: "reading/statistics",
            ...page(() => import("@/pages/listening/ListeningStatsPage")),
          },
          {
            // Above ``reading/:id``, like every other one of these: a path
            // segment that is not a material id has to be matched before the
            // route that would read it as one. It renders the take page,
            // which serves a drill and a whole paper from one component
            // rather than two that would drift apart.
            path: "reading/drills/:groupId",
            ...page(() => import("@/pages/reading/ReadingTakePage")),
          },
          {
            path: "reading/collections/:id",
            ...page(() => import("@/pages/listening/CollectionPage")),
          },
          {
            path: "reading/:id",
            ...page(() => import("@/pages/reading/ReadingTakePage")),
          },
          {
            // Before ``listening/:id``, or an attempt id would be read as a
            // material id and the take page would fetch a material that
            // doesn't exist.
            path: "listening/attempts/:attemptId",
            ...page(() => import("@/pages/listening/ListeningResultsPage")),
          },
          {
            // Same reason as above: "statistics" is not a material id.
            path: "listening/statistics",
            ...page(() => import("@/pages/listening/ListeningStatsPage")),
          },
          {
            // And nor is "collections". Every one of these has to stay above
            // ``listening/:id``.
            path: "listening/collections/:id",
            ...page(() => import("@/pages/listening/CollectionPage")),
          },
          {
            // And nor is "drills". Every one of these has to stay above
            // ``listening/:id``. It renders the take page, which serves a
            // drill and a whole paper from one component rather than two
            // that would drift apart.
            path: "listening/drills/:groupId",
            ...page(() => import("@/pages/listening/ListeningTakePage")),
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
          // The three halves of the studio, under one header. A pathless
          // layout route rather than a component each page renders, so the
          // tab bar is the SAME element on all of them — see StudioTabsLayout
          // for why that is load-bearing.
          {
            element: <StudioTabsLayout />,
            children: [
              {
                path: "listening",
                ...page(
                  () => import("@/pages/studio/listening/StudioListeningListPage"),
                ),
              },
              {
                path: "reading",
                ...page(
                  () => import("@/pages/studio/reading/StudioReadingListPage"),
                ),
              },
              {
                path: "collections",
                ...page(
                  () => import("@/pages/studio/collections/StudioCollectionsPage"),
                ),
              },
            ],
          },
          {
            path: "listening/new",
            ...page(() => import("@/pages/studio/listening/StudioListeningEditorPage")),
          },
          {
            path: "listening/:id",
            ...page(() => import("@/pages/studio/listening/StudioListeningEditorPage")),
          },
          {
            path: "reading/new",
            ...page(() => import("@/pages/studio/reading/StudioReadingEditorPage")),
          },
          {
            path: "reading/:id",
            ...page(() => import("@/pages/studio/reading/StudioReadingEditorPage")),
          },
          {
            path: "collections/:id",
            ...page(
              () =>
                import(
                  "@/pages/studio/collections/StudioCollectionEditorPage"
                ),
            ),
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
