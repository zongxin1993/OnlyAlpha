import "@testing-library/jest-dom/vitest";

// jsdom does not implement browser layout observers used by the shared UI library.
Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string): MediaQueryList => ({
        matches: false,
        media: query,
        onchange: null,
        addListener() {
            return;
        },
        removeListener() {
            return;
        },
        addEventListener() {
            return;
        },
        removeEventListener() {
            return;
        },
        dispatchEvent: () => false
    })
});
globalThis.ResizeObserver = class {
    observe() {
        return;
    }
    unobserve() {
        return;
    }
    disconnect() {
        return;
    }
};
