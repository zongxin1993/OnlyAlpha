export type Theme = "dark" | "light";

const STORAGE_KEY = "oa-theme";
const listeners = new Set<() => void>();
let current: Theme = "dark";

function readStored(): Theme {
    try {
        const value = localStorage.getItem(STORAGE_KEY);
        return value === "light" || value === "dark" ? value : "dark";
    } catch {
        return "dark";
    }
}

export function getStoredTheme(): Theme {
    return readStored();
}

export function getThemeSnapshot(): Theme {
    return current;
}

export function subscribeTheme(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}

export function applyTheme(theme: Theme): void {
    current = theme;
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    try {
        localStorage.setItem(STORAGE_KEY, theme);
    } catch {
        // 存储不可用时仅本次会话生效，不影响显示。
    }
    for (const listener of listeners) {
        listener();
    }
}

export function toggleTheme(): Theme {
    const next: Theme = current === "dark" ? "light" : "dark";
    applyTheme(next);
    return next;
}

export function initTheme(): void {
    applyTheme(readStored());
}
