import { AppRoutes } from "@/app/routes";
import { Providers } from "@/app/providers";

export function App() {
  return (
    <Providers>
      <AppRoutes />
    </Providers>
  );
}
