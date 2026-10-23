import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import "./app/styles.css";
import { applyTheme, preferredTheme } from "./app/theme";

applyTheme(preferredTheme());
createRoot(document.getElementById("root")!).render(<StrictMode><App/></StrictMode>);
