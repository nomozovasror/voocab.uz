import { createBrowserRouter } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";
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
        path: "listening",
        lazy: async () => ({
          Component: (await import("@/pages/listening/ListeningPage")).default,
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
]);
