/** Browser presentation choices; never Calculation configuration. */
export const studyColors = [
    { name: "红色", value: "#c8332a" },
    { name: "橙色", value: "#e67e22" },
    { name: "黄色", value: "#f1c40f" },
    { name: "黄绿色", value: "#8bc34a" },
    { name: "绿色", value: "#2f7d47" },
    { name: "青绿色", value: "#008877" },
    { name: "青色", value: "#00bcd4" },
    { name: "天蓝色", value: "#29b6f6" },
    { name: "蓝色", value: "#2457c5" },
    { name: "深蓝色", value: "#1f5f8b" },
    { name: "靛蓝色", value: "#5c6bc0" },
    { name: "紫色", value: "#8e44ad" },
    { name: "粉色", value: "#e91e63" },
    { name: "棕色", value: "#795548" },
    { name: "灰色", value: "#757575" },
    { name: "黑色", value: "#222222" }
] as const;
export const studyColorName = (color: string): string =>
    studyColors.find((choice) => choice.value.toLowerCase() === color.toLowerCase())?.name ??
    "自定义颜色";
