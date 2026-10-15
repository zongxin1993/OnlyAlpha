import { TickMarkType, type UTCTimestamp } from "lightweight-charts";
import { chartTimeFormatters, readDisplayTimezone } from "./chartDisplayTime";

afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
});
it("formats the same UTC instant across the Shanghai date boundary without translating identity", () => {
    const time = 1767222000 as UTCTimestamp; // 2025-12-31 23:00 UTC
    const utc = chartTimeFormatters("UTC"),
        shanghai = chartTimeFormatters("Asia/Shanghai");
    expect(utc.timeFormatter(time)).toBe("2025-12-31 23:00:00 UTC");
    expect(shanghai.timeFormatter(time)).toBe("2026-01-01 07:00:00 Asia/Shanghai");
    expect(utc.tickMarkFormatter(time, TickMarkType.DayOfMonth)).toBe("12-31");
    expect(shanghai.tickMarkFormatter(time, TickMarkType.DayOfMonth)).toBe("01-01");
    expect(shanghai.tickMarkFormatter(time, TickMarkType.Year)).toBe("2026");
    expect(shanghai.tickMarkFormatter(time, TickMarkType.Time)).toBe("07:00");
    expect(time).toBe(1767222000);
});
it("uses the browser IANA timezone and DST rules, including repeated local hours", () => {
    const original = new Intl.DateTimeFormat().resolvedOptions();
    vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockReturnValue({
        ...original,
        timeZone: "America/New_York"
    });
    const local = chartTimeFormatters("USER_LOCAL");
    expect(local.timeFormatter(1772951400 as UTCTimestamp)).toBe(
        "2026-03-08 01:30:00 America/New_York"
    );
    expect(local.timeFormatter(1772955000 as UTCTimestamp)).toBe(
        "2026-03-08 03:30:00 America/New_York"
    );
    expect(local.timeFormatter(1793511000 as UTCTimestamp)).toBe(
        "2026-11-01 01:30:00 America/New_York"
    );
    expect(local.timeFormatter(1793514600 as UTCTimestamp)).toBe(
        "2026-11-01 01:30:00 America/New_York"
    );
});
it("restores only the bounded display preference and handles denied reads", () => {
    localStorage.setItem("onlyalpha.chart.displayTimezone", "USER_LOCAL");
    expect(readDisplayTimezone()).toEqual({ zone: "USER_LOCAL", notice: "" });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
        throw new Error("denied");
    });
    expect(readDisplayTimezone()).toEqual({
        zone: "UTC",
        notice: "无法读取时区偏好；仅本次显示生效"
    });
});
