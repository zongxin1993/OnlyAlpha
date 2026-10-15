import { TickMarkType, type Time } from "lightweight-charts";

export type DisplayTimezone = "UTC" | "Asia/Shanghai" | "USER_LOCAL";
export const displayTimezoneKey = "onlyalpha.chart.displayTimezone";
export const isDisplayTimezone = (value: unknown): value is DisplayTimezone =>
    value === "UTC" || value === "Asia/Shanghai" || value === "USER_LOCAL";

export function readDisplayTimezone(): { zone: DisplayTimezone; notice: string } {
    try {
        const saved = localStorage.getItem(displayTimezoneKey);
        return saved === null || isDisplayTimezone(saved)
            ? { zone: saved ?? "UTC", notice: "" }
            : { zone: "UTC", notice: "时区偏好已损坏，已使用 UTC；可重新选择" };
    } catch {
        return { zone: "UTC", notice: "无法读取时区偏好；仅本次显示生效" };
    }
}

/** Presentation only. Native UTC timestamps and every query input remain unchanged. */
export function chartTimeFormatters(zone: DisplayTimezone) {
    const timeZone =
        zone === "USER_LOCAL" ? Intl.DateTimeFormat().resolvedOptions().timeZone : zone;
    const formatter = new Intl.DateTimeFormat("en-GB", {
        timeZone,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hourCycle: "h23"
    });
    const parts = (time: number) => {
        const values = formatter.formatToParts(new Date(time * 1000));
        const part = (type: Intl.DateTimeFormatPartTypes) => {
            const value = values.find((item) => item.type === type)?.value;
            if (value === undefined) throw new Error("Missing display time component");
            return value;
        };
        return {
            year: part("year"),
            month: part("month"),
            day: part("day"),
            hour: part("hour"),
            minute: part("minute"),
            second: part("second")
        };
    };
    return {
        timeFormatter: (time: Time) => {
            if (typeof time !== "number") return "";
            const p = parts(time);
            return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second} ${timeZone}`;
        },
        tickMarkFormatter: (time: Time, kind: TickMarkType) => {
            if (typeof time !== "number") return null;
            const p = parts(time);
            return kind === TickMarkType.TimeWithSeconds
                ? `${p.hour}:${p.minute}:${p.second}`
                : kind === TickMarkType.Time
                  ? `${p.hour}:${p.minute}`
                  : kind === TickMarkType.Year
                    ? p.year
                    : `${p.month}-${p.day}`;
        }
    };
}
