import indexHtml from "../../../index.html?raw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
    applyTheme,
    getStoredTheme,
    getThemeSnapshot,
    initTheme,
    subscribeTheme,
    toggleTheme
} from "./theme";

describe("主题基础（暗色默认双主题）", () => {
    beforeEach(() => {
        localStorage.clear();
        document.documentElement.removeAttribute("data-theme");
        document.documentElement.style.removeProperty("color-scheme");
    });

    it("无存储记录时默认暗色，并同步 color-scheme", () => {
        initTheme();
        expect(document.documentElement.dataset.theme).toBe("dark");
        expect(document.documentElement.style.colorScheme).toBe("dark");
        expect(getStoredTheme()).toBe("dark");
    });

    it("toggleTheme 切到浅色并持久化 oa-theme", () => {
        initTheme();
        expect(toggleTheme()).toBe("light");
        expect(document.documentElement.dataset.theme).toBe("light");
        expect(localStorage.getItem("oa-theme")).toBe("light");
    });

    it("已有存储时 initTheme 恢复既有主题", () => {
        localStorage.setItem("oa-theme", "light");
        initTheme();
        expect(document.documentElement.dataset.theme).toBe("light");
        expect(getStoredTheme()).toBe("light");
    });

    it("损坏的存储值回落到暗色", () => {
        localStorage.setItem("oa-theme", "neon");
        expect(getStoredTheme()).toBe("dark");
    });

    it("applyTheme 通知订阅者且快照同步", () => {
        initTheme();
        const spy = vi.fn();
        const unsubscribe = subscribeTheme(spy);
        applyTheme("light");
        expect(spy).toHaveBeenCalledTimes(1);
        expect(getThemeSnapshot()).toBe("light");
        unsubscribe();
        applyTheme("dark");
        expect(spy).toHaveBeenCalledTimes(1);
    });

    it("index.html 在渲染 #root 前同步应用主题（防首帧闪白）", () => {
        const html = indexHtml;
        const inlinePos = html.indexOf("oa-theme");
        expect(inlinePos).toBeGreaterThan(-1);
        expect(inlinePos).toBeLessThan(html.indexOf('<div id="root">'));
        expect(inlinePos).toBeLessThan(html.indexOf('type="module"'));
        expect(html).toMatch(/lang="zh-CN"/);
        expect(html).toContain("<title>OnlyAlpha</title>");
    });
});
