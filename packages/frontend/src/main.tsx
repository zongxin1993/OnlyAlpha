import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { AppProviders } from "./app/providers";
import "./app/styles/tokens.css";
import "./app/styles/base.css";

const root = document.getElementById("root");
if (root === null) throw new Error("OnlyAlpha Web root is missing");
createRoot(root).render(
    <StrictMode>
        <AppProviders>
            <App />
        </AppProviders>
    </StrictMode>
);
