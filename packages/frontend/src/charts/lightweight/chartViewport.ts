import type { LogicalRange } from "lightweight-charts";

/** Display indexes only: preserve matching UTC anchors when series change the union axis. */
export function rebaseChartRange(
    range: LogicalRange,
    before: readonly number[],
    after: readonly number[],
    followNewBars = false
): LogicalRange {
    const index = (position: number): number => {
        if (before.length === 0) return position;
        const anchor = Math.max(0, Math.min(before.length - 1, Math.floor(position)));
        const time = before[anchor];
        if (time === undefined) return position;
        const next = after.indexOf(time);
        // Deleted point: retain the next chronological display anchor, not a value.
        const fallback = after.findIndex((candidate) => candidate >= time);
        return (next >= 0 ? next : fallback >= 0 ? fallback : after.length - 1) + position - anchor;
    };
    const last = before.at(-1);
    const appended = last === undefined ? 0 : after.filter((time) => time > last).length;
    const shift = followNewBars && range.to >= before.length - 1 ? appended : 0;
    return { from: index(range.from) + shift, to: index(range.to) + shift } as LogicalRange;
}
