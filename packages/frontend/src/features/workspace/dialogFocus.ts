import type { KeyboardEvent } from "react";

/** Native dialog owns inertness; keep Tab edge traversal out of browser chrome. */
export function keepDialogFocus(event: KeyboardEvent<HTMLDialogElement>): void {
    if (event.key !== "Tab") return;
    const controls = [
        ...event.currentTarget.querySelectorAll<HTMLElement>(
            'button, input, select, summary, [tabindex]:not([tabindex="-1"])'
        )
    ].filter((node) => !node.matches(":disabled") && node.getClientRects().length > 0);
    const first = controls[0],
        last = controls.at(-1);
    if (first === undefined || last === undefined) return;
    if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
    }
}
