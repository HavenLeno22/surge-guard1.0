import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router/dom";

import { Providers } from "@/app/providers";
import { router } from "@/app/router";
import "@/styles/global.css";

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("#root element is missing from index.html");

createRoot(rootElement).render(
  <StrictMode>
    <Providers>
      <RouterProvider router={router} />
    </Providers>
  </StrictMode>,
);
