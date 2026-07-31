import { RouterProvider } from "react-router-dom";
import { AppProviders } from "./providers";
import { router } from "./router";
import { ConnectionGate } from "@/connection/ConnectionGate";

export default function App() {
  return (
    <AppProviders>
      {/* Above the router: when the backend is down, the gate takes over the
          whole screen and navigation is blocked until it's back. */}
      <ConnectionGate>
        <RouterProvider router={router} />
      </ConnectionGate>
    </AppProviders>
  );
}
