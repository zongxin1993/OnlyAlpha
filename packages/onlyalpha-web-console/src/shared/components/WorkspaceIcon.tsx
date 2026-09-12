const paths = {
    analysis: "m12 3 2.2 6.8L21 12l-6.8 2.2L12 21l-2.2-6.8L3 12l6.8-2.2L12 3Z",
    research: "M9 3h6M10 3v6L4.5 18a2 2 0 0 0 1.7 3h11.6a2 2 0 0 0 1.7-3L14 9V3M8 14h8",
    runs: "M5 5h14v14H5zM9 9l6 3-6 3V9Z",
    results: "M4 20V4M4 20h16M8 16v-5M12 16V7M16 16v-8",
    data: "M4 5h16v14H4zM4 10h16M4 14h16M10 5v14",
    library: "M4 4h4v16H4zM10 4h4v16h-4zM17 4l4 15-3 1-4-15 3-1Z",
    menu: "M4 6h16M4 12h16M4 18h16",
    arrow: "M5 12h14m-5-5 5 5-5 5",
    calendar: "M5 5h14v15H5zM8 3v4M16 3v4M5 10h14M8 14h2M14 14h2",
    clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM12 7v5l3 2",
    shield: "m12 3 8 3v5c0 5-8 10-8 10S4 16 4 11V6l8-3Zm-4 8 3 3 5-6"
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
