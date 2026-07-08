import { createBrowserRouter } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";

/**
 * Central route config. Page components are lazy-loaded so each route is its
 * own chunk (code splitting). Add a section by dropping a page under
 * src/pages/<name>/ and registering a lazy child here.
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
        path: "dictation",
        lazy: async () => ({
          Component: (await import("@/pages/dictation/DictationPage")).default,
        }),
      },
      {
        path: "vocabulary",
        lazy: async () => ({
          Component: (await import("@/pages/vocabulary/VocabularyPage")).default,
        }),
      },
      {
        path: "auth",
        lazy: async () => ({
          Component: (await import("@/pages/auth/AuthPage")).default,
        }),
      },
    ],
  },
]);
