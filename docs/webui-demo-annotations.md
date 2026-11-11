# 演示页元素批注（Agentation 书签注入）

演示期间对 `http://127.0.0.1:5173/` 的界面提出针对性修改意见用此工具：
在页面上实时点选元素 → 写批注 → 一键复制含选择器链的结构化反馈 → 粘贴到
与 Agent 的对话，即可精确定位源码位置进行修改。

工具为开源 [Agentation](https://agentation.com)（PolyForm Shield 1.0.0，
内部使用允许），经 CDN 在浏览器侧注入。**产品代码、构建与产物零改动**，
正式构建不包含任何相关代码。

## 安装（一次性）

新建书签，URL 粘贴以下内容（Chrome 粘贴后会剥掉 `javascript:` 前缀，
手动在开头补回 `java` 两个字母即可保存）：

```text
javascript:(async()=>{if(document.querySelector("agentation-toolbar"))return;const h=document.createElement("div");document.body.appendChild(h);const[R,D,M]=await Promise.all([import("https://esm.sh/react@19.2.0"),import("https://esm.sh/react-dom@19.2.0/client"),import("https://esm.sh/agentation@3.1.2?deps=react@19.2.0")]);D.createRoot(h).render(R.createElement(M.Agentation))})()
```

## 使用流程

1. 打开演示页，点一次书签 → 右下角出现批注工具条（每次整页刷新后需再点一次；
   站内路由切换不需要）。
2. 点 **Start feedback mode**（或按住 Cmd/Ctrl 直接多选、拖拽框选区域）。
3. 点击要改的元素（悬停高亮），在弹出框写批注，回车或点确认。
4. 可继续批注多处；点 **Copy feedback** 复制全部（Markdown，含 URL、视口、
   元素位置与选择器链）。
5. 把复制内容整段粘贴到与 Agent 的对话中；Agent 依据选择器链定位源码做针对
   性修改，改完重新部署演示实例后刷新即可验证。

批注保存在浏览器 localStorage（按页面路径分组），刷新后重新点书签可继续。
**Clear all** 清空重来。

## 边界与已验证事实

- 仅演示环境使用；不进入任何构建产物（构建环境本就剥离全部 `VITE_` 变量，
  未做产品侧接线）。
- 依赖外网 CDN（esm.sh）加载工具本体，演示机需可访问外网。
- 2026-11-11 验证：headless Chromium 走真实演示页完成"挂载→反馈模式→点选
  自选行→批注→复制"，剪贴板输出含 `tr[data-testid="watchlist-row"]` 等
  可直接 grep 的定位信息；页面零报错。验证脚本与截图留在
  `test-results/annotation-check/`（下次演示部署重建前清理）。
