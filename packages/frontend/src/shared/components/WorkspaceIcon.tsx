const paths = {
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
