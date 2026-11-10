const paths = {
    search: "M10.5 3a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15ZM16 16l5 5",
    more: "M5 11h.01v.01H5zM12 11h.01v.01H12zM19 11h.01v.01H19z",
    watchlist: "M6 3h12v18l-6-4-6 4V3Z",
    // Feather settings icon (MIT); see public/licenses/feather.txt.
    settings:
        "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6ZM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z",
    candles: "M6 3v4M6 15v6M3 7h6v8H3zM17 3v7M17 18v3M14 10h6v8h-6z",
    dashboard: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
    // Feather sun/moon icons (MIT); see public/licenses/feather.txt.
    sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10ZM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
    moon: "M20 13.1A8.1 8.1 0 1 1 10.9 4a6.3 6.3 0 0 0 9.1 9.1Z",

    line: "M3 19 8 10l5 4 8-10",
    analysis: "m12 3 2.2 6.8L21 12l-6.8 2.2L12 21l-2.2-6.8L3 12l6.8-2.2L12 3Z",
    research: "M9 3h6M10 3v6L4.5 18a2 2 0 0 0 1.7 3h11.6a2 2 0 0 0 1.7-3L14 9V3M8 14h8",
    runs: "M5 5h14v14H5zM9 9l6 3-6 3V9Z",
    results: "M4 20V4M4 20h16M8 16v-5M12 16V7M16 16v-8",
    data: "M4 5h16v14H4zM4 10h16M4 14h16M10 5v14",
    database:
        "M12 3c4.42 0 8 1.34 8 3s-3.58 3-8 3-8-1.34-8-3 3.58-3 8-3ZM4 6v6c0 1.66 3.58 3 8 3s8-1.34 8-3V6M4 12v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6",
    library: "M4 4h4v16H4zM10 4h4v16h-4zM17 4l4 15-3 1-4-15 3-1Z",
    menu: "M4 6h16M4 12h16M4 18h16",
    arrow: "M5 12h14m-5-5 5 5-5 5",
    calendar: "M5 5h14v15H5zM8 3v4M16 3v4M5 10h14M8 14h2M14 14h2",
    clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM12 7v5l3 2",
    shield: "m12 3 8 3v5c0 5-8 10-8 10S4 16 4 11V6l8-3Zm-4 8 3 3 5-6",
    pointer: "m7 3 11 8-5 1.2L11 17 7 3Z",
    segment: "M4 17h3v3H4zM17 4h3v3h-3zM6.5 17.5 17.5 6.5",
    level: "M4 12h16M9 9.5 7 14.5M15 9.5l2 5",
    zone: "M4 8h16v8H4z",
    measure: "M3 8h18v8H3zM8 8v3M12 8v4M16 8v3",
    collapse: "M14.5 6 9 12l5.5 6",
    expand: "M9.5 6 15 12l-5.5 6",
    up: "M6 14.5 12 9l6 5.5",
    down: "M6 9.5 12 15l6-5.5"
} as const;

export type WorkspaceIconName = keyof typeof paths;

export function WorkspaceIcon({ name }: { readonly name: WorkspaceIconName }) {
    return (
        <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
            focusable="false"
            className="workspace-icon"
        >
            <path d={paths[name]} />
        </svg>
    );
}
