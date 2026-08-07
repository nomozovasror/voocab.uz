import { RouterProvider } from "react-router-dom";
import { AppProviders } from "./providers";
import { router } from "./router";
import { ConnectionGate } from "@/connection/ConnectionGate";
import { SplashScreen } from "./SplashScreen";

export default function App() {
  return (
    <AppProviders>
      {/* Outermost: covers first entry while everything below boots. */}
      <SplashScreen>
        {/* Above the router: when the backend is down, the gate takes over the
            whole screen and navigation is blocked until it's back. */}
        <ConnectionGate>
          <RouterProvider router={router} />
        </ConnectionGate>
      </SplashScreen>
    </AppProviders>
  );
}
