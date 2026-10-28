import { TickMarkType, type Time } from "lightweight-charts";

export const displayTimezones = [
    ["UTC", "UTC"],
    ["USER_LOCAL", "本地时区"],
    ["Etc/GMT+12", "UTC−12 贝克岛"],
    ["Pacific/Pago_Pago", "UTC−11 帕果帕果"],
    ["Pacific/Honolulu", "UTC−10 檀香山"],
    ["America/Anchorage", "安克雷奇"],
    ["America/Los_Angeles", "洛杉矶"],
    ["America/Denver", "丹佛"],
    ["America/Chicago", "芝加哥"],
    ["America/New_York", "纽约"],
    ["America/Halifax", "哈利法克斯"],
    ["America/St_Johns", "圣约翰斯"],
    ["America/Sao_Paulo", "圣保罗"],
    ["Atlantic/South_Georgia", "UTC−02 南乔治亚"],
    ["Atlantic/Azores", "亚速尔"],
    ["Europe/London", "伦敦"],
    ["Europe/Berlin", "柏林"],
    ["Africa/Johannesburg", "UTC+02 约翰内斯堡"],
    ["Europe/Moscow", "UTC+03 莫斯科"],
    ["Asia/Tehran", "德黑兰"],
    ["Asia/Dubai", "UTC+04 迪拜"],
    ["Asia/Kabul", "UTC+04:30 喀布尔"],
    ["Asia/Karachi", "UTC+05 卡拉奇"],
    ["Asia/Kolkata", "UTC+05:30 加尔各答"],
    ["Asia/Kathmandu", "UTC+05:45 加德满都"],
    ["Asia/Dhaka", "UTC+06 达卡"],
    ["Asia/Yangon", "UTC+06:30 仰光"],
    ["Asia/Bangkok", "UTC+07 曼谷"],
    ["Asia/Shanghai", "北京时间"],
    ["Australia/Eucla", "UTC+08:45 尤克拉"],
    ["Asia/Tokyo", "UTC+09 东京"],
    ["Australia/Adelaide", "阿德莱德"],
    ["Australia/Sydney", "悉尼"],
    ["Pacific/Noumea", "UTC+11 努美阿"],
    ["Pacific/Auckland", "奥克兰"],
    ["Pacific/Chatham", "查塔姆"],
    ["Pacific/Tongatapu", "UTC+13 努库阿洛法"],
    ["Pacific/Kiritimati", "UTC+14 圣诞岛"]
] as const;
export type DisplayTimezone = (typeof displayTimezones)[number][0];
export const displayTimezoneKey = "onlyalpha.chart.displayTimezone";
export const isDisplayTimezone = (value: unknown): value is DisplayTimezone =>
    displayTimezones.some(([zone]) => zone === value);

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
