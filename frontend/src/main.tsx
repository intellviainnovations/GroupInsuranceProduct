import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { App } from "./App";
import { strings } from "./strings";
import "./styles.css";

document.title = strings.document.title;

const root = document.getElementById("root");
if (!root) {
  throw new Error(strings.fatal.missingRoot);
}

createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
