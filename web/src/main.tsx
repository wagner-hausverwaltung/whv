import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./i18n";
import App from "./App.tsx";
import { WhvThemeProvider } from "./theme/ThemeProvider";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <WhvThemeProvider>
      <App />
    </WhvThemeProvider>
  </StrictMode>,
);
