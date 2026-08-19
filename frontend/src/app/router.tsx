import { Navigate, createBrowserRouter, redirect } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";
import { StudioLayout } from "@/components/studio/StudioLayout";
import { RequireAuth } from "@/auth/RequireAuth";

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
        lazy: async () => ({
          Component: (await import("@/pages/home/HomePage")).default,
        }),
      },
      {
        path: "reading",
        lazy: async () => ({
          Component: (await import("@/pages/reading/ReadingPage")).default,
        }),
      },
      {
        path: "vocabulary",
        lazy: async () => ({
          Component: (await import("@/pages/vocabulary/VocabularyPage")).default,
        }),
      },
      {
        path: "login",
        lazy: async () => ({
          Component: (await import("@/pages/login/LoginPage")).default,
        }),
      },
      // --- Protected ---
      {
        element: <RequireAuth />,
        children: [
          {
            path: "listening",
            lazy: async () => ({
              Component: (await import("@/pages/listening/ListeningPage")).default,
            }),
          },
          {
            // Before ``listening/:id``, or an attempt id would be read as a
            // material id and the take page would fetch a material that
            // doesn't exist.
            path: "listening/attempts/:attemptId",
            lazy: async () => ({
              Component: (
                await import("@/pages/listening/ListeningResultsPage")
              ).default,
            }),
          },
          {
            path: "listening/:id",
            lazy: async () => ({
              Component: (
                await import("@/pages/listening/ListeningTakePage")
              ).default,
            }),
          },
          {
            path: "dictation",
            lazy: async () => ({
              Component: (await import("@/pages/dictation/DictationPage")).default,
            }),
          },
          {
            path: "profile",
            lazy: async () => ({
              Component: (await import("@/pages/profile/ProfilePage")).default,
            }),
          },
          {
            path: "materials",
            lazy: async () => ({
              Component: (await import("@/pages/materials/MaterialsPage")).default,
            }),
          },
          {
            path: "materials/new",
            lazy: async () => ({
              Component: (
                await import("@/pages/materials/MaterialEditorPage")
              ).default,
            }),
          },
          {
            path: "materials/:id/edit",
            lazy: async () => ({
              Component: (
                await import("@/pages/materials/MaterialEditorPage")
              ).default,
            }),
          },
        ],
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
            lazy: async () => ({
              Component: (
                await import("@/pages/studio/StudioDashboardPage")
              ).default,
            }),
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
          },
          {
            path: "listening",
            lazy: async () => ({
              Component: (
                await import("@/pages/studio/listening/StudioListeningListPage")
              ).default,
            }),
          },
          {
            path: "listening/new",
            lazy: async () => ({
              Component: (
                await import("@/pages/studio/listening/StudioListeningEditorPage")
              ).default,
            }),
          },
          {
            path: "listening/:id",
            lazy: async () => ({
              Component: (
                await import("@/pages/studio/listening/StudioListeningEditorPage")
              ).default,
            }),
          },
        ],
      },
    ],
  },
]);
