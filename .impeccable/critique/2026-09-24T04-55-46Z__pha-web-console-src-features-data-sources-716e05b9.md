---
target: 数据源配置与管理 (packages/onlyalpha-web-console/src/features/data/sources)
total_score: 28
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
target_identity: "file:/Users/zongxin/workspace/OnlyAlpha/packages/onlyalpha-web-console/src/features/data/sources"
timestamp: 2026-09-24T04-55-46Z
slug: pha-web-console-src-features-data-sources-716e05b9
closed: true
---
⚠️ DEGRADED: single-context (sub-agent tool exposed but task delivery failed — four spawns across two rounds returned "no task received"; Assessment A and B were run sequentially by the parent)

Target: `packages/onlyalpha-web-console/src/features/data/sources/` — Data Source Configuration & Management (Workspace entry + quick Popover + manager Modal 已配置 / 添加数据源 / 数据源绑定 + contract-driven configuration view with Probe).
Mode: **Operate**.

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Entry count, per-source state and last-probe time are always visible; but a completed mutation has no confirmation (the surface just re-renders) |
| 2 | Match System / Real World | 3 | Chinese operator copy + canonical English ids is coherent; `草稿 v7` / `revision 3f7a91c4` / `HISTORICAL_BARS` remain unglossed insider vocabulary |
| 3 | User Control and Freedom | 3 | Esc, backdrop, 关闭, 返回列表, 重置契约 present; **归档 is one click inside `⋯` with no confirmation** and is not reversible from this surface |
| 4 | Consistency and Standards | 3 | Inherits the shell's tokens and hairlines; the same fact is shown three ways (`DEGRADED` raw, 降级 badge, 降级-shaped mark) |
| 5 | Error Prevention | 3 | Contract-driven enums/bounds, secrets never echoed, CAS conflicts surfaced; no guard before 归档, no guard before 发布 Revision |
| 6 | Recognition Rather Than Recall | 3 | Everything is readable in place and Binding shows candidate counts instead of implied defaults; provider identity is one letter, so two Binance types look identical until read |
| 7 | Flexibility and Efficiency | 2 | No keyboard path to open the manager, no shortcut to 测试连接, Popover rows are not actionable, no filter/sort in 已配置 |
| 8 | Aesthetic and Minimalist Design | 3 | Dense, low-decoration, no card wall; fixed 800px modal leaves ~400px void with two sources, and the degraded card stacks two notices |
| 9 | Error Recovery | 3 | `UNKNOWN_OUTCOME` keeps command identity, "结果未确认" copy, draft conflict → 重新载入, archived → read-only banner; no visible confirmation that recovery succeeded |
| 10 | Help and Documentation | 2 | Inline copy is strong (gap banner, archive semantics, probe support); no contextual help for canonical tokens, no docs entry, no first-run explanation |
| **Total** | | **28/40** | **Good** |

## Design Specificity Verdict

**Verdict: mostly authored, with one interchangeable region.**

Three things here could not be pasted into another product: the status accounting that separates `n 异常` from `n 未验证` and refuses to let an unverifiable set read as a warning; Probe capability derived from the Integration Type descriptor with an explicit "该类型未提供连接测试" instead of a mystery disabled button; and the Binding tab openly declaring a missing canonical capability rather than inventing a browser-local default. That is product truth expressed in the UI, not decoration.

The interchangeable part is the **configuration view**: it is a legacy full-page form re-hosted inside a modal — 480px-wide controls, 1rem vertical rhythm, an `高级设置` fieldset boxed inside an already-bordered panel. It reads as "form page dropped into a dialog" while the surrounding surface is 0.6–0.9rem dense. That is the region a competing product could ship unchanged.

**Deterministic scan (CLI):** `.github/skills/impeccable/scripts/impeccable detect --json` on `features/data/sources` and `features/workspace` both exit 0 with `[]` — the source files are clean of the statically detectable tells.

**Browser overlay:** injection succeeded in an automated Chrome session (preflight `document.title` + `<script>` append both worked; `live-server` bound port 8400 and `/detect.js` loaded). It reported **9 anti-patterns** with the workspace + Popover open and **11** with the manager + configuration view open. Overlay screenshot: `.impeccable/review/ds-09-overlay.png`. The findings were: `tiny-text` ×6 · `undersized-ui-text` ×3 · `gpt-thin-border-wide-shadow` ×2 · `overused-font` · `flat-type-hierarchy` · `dark-glow`. Your own browser tab was **not** instrumented — the overlay lives only in that automated session and the live-server has been stopped.

## Overall Impression

This is a disciplined Operate surface: it answers "which sources do I have, which are healthy, which are only unverified" in one glance, and it never lies about what the backend can prove. The biggest opportunity is not more features — it is **finishing the modal as a modal** (focus contract), **raising the text floor**, and **re-composing the configuration view** so it stops looking like a page that wandered into a dialog.

## What's Working

1. **Status semantics that resist the easy lie.** `UNKNOWN` is counted as 未验证, never as 异常, and the entry keeps a muted dashed mark so a permanently unverifiable source can't paint the workspace yellow. The counts (`1 异常 · 1 未验证`) are text, not just color.
2. **Probe as evidence, not a verdict.** Per-capability rows distinguish 通过 / 失败 / 未验证 (`SKIPPED`) / 不适用 (undeclared) / 未知 (declared but missing), each with its own latency and the raw error code kept verbatim. An operator can tell "Binance realtime broke" from "we never checked authentication".
3. **Honest gap handling.** The Binding tab says out loud that canonical Source Binding does not exist yet, shows 未设置 rather than a plausible default, and the Workspace block says the chart is synthetic instead of naming a provider it isn't using.

## Priority Issues

**[P1] The modal has no focus contract.**
**What:** `DataSourceManager.tsx` focuses `.manager-surface` on mount, but nothing traps Tab inside the dialog, the background is not `inert`, and focus is never restored to the `数据源` trigger on close.
**Why it matters:** a keyboard or screen-reader operator tabs straight out of "管理数据源" into the chart behind it — the dialog claims `aria-modal` while behaving like a panel — and after closing, focus lands at the top of the document instead of the control they used.
**Fix:** while open, mark the workspace behind the overlay `inert`, wrap Tab/Shift+Tab inside the surface, store `document.activeElement` before mount and `.focus()` it on unmount.
**Suggested command:** `/impeccable harden`

**[P1] Secondary text sits below both the design system's and the detector's legibility floor.**
**What:** capability tags, tool labels, Popover metadata, binding notes, banners and Probe latency use 0.68–0.74rem (10.9–11.8px); the detector flagged 6 `tiny-text` and 3 `undersized-ui-text` instances at 10.88–11.84px, and `DESIGN.md` sets its own label floor at 0.78rem.
**Why it matters:** on a surface whose entire job is reading配置与状态 at a glance, the smallest type carries the most decision-relevant facts (which capability failed, which candidate exists, what `synthetic` means). Contrast is fine (5.0–6.7:1) — size is the problem.
**Fix:** raise in-surface secondary text to 0.78rem minimum; keep 0.72rem only for timestamps and never below 0.75rem elsewhere.
**Suggested command:** `/impeccable typeset`

**[P2] The entry's open state borrows the focus ring.**
**What:** `ds-trigger--open` uses `box-shadow: 0 0 0 3px var(--accent-soft)`, the same glow as `:focus-visible` (detector: `dark-glow`, zero-offset).
**Why it matters:** the same visual means two different things, so a keyboard user cannot tell "this control has focus" from "this popover is open" — exactly the distinction they rely on.
**Fix:** open state = `--accent-line` border plus a caret/rotation and the existing `aria-expanded`; reserve the 3px glow for focus only.
**Suggested command:** `/impeccable polish`

**[P2] Flat type hierarchy across the manager.**
**What:** detector: "largest adjacent step 1.13:1, target 1.25:1" (body 12.8px, h4 12.8px, h3 14.4px, h2 15.2px). Modal title 0.95rem, section title 0.8rem, card title 0.84rem, body 0.8rem.
**Why it matters:** with four stacked regions inside one dialog, hierarchy rests almost entirely on weight and color; the eye gets no size cue for "this is a section" vs "this is a row", which is the difference between scannable density and a wall of similar text.
**Fix:** give the modal title, section headings and card titles real steps (e.g. 1.05 / 0.9 / 0.875 rem) while keeping the hairline, ≤6px radius, no-shadow world.
**Suggested command:** `/impeccable typeset`

**[P2] The configuration view reads as a legacy page inside a modal.**
**What:** full-width ~480px controls, 1rem vertical rhythm, `高级设置` boxed inside an already-bordered panel, `探测标的` floating under the field group — while the rest of the surface runs at 0.6–0.9rem density.
**Why it matters:** this is the screen where the operator spends the most time and makes the riskiest edits (credentials, publish, contract reset); it is also the only screen that looks assembled rather than designed, which weakens trust precisely where the stakes are highest.
**Fix:** compose it as a two-column dense form at desktop width (label column + control column, max 28rem controls), demote the advanced fieldset to an inline disclosure without its own border, and pin 保存草稿 / 发布 Revision / 重置契约 to the modal footer.
**Suggested command:** `/impeccable layout`

## Persona Red Flags

**Alex (impatient power user)**: no keyboard route into the manager (Tab to the trigger, then activate); no shortcut for 测试连接 on the focused card; Popover rows are inert text, so a status glance always costs a modal open; 已配置 has no filter or sort even though the surface is designed for many sources; inside the modal the primary action sits after ~8 Tab stops.

**Sam (accessibility-dependent)**: tabs out of the dialog into the chart behind it (no trap, no `inert`); focus is not returned to the 数据源 trigger after close; `aria-description` on the disabled Probe control is not uniformly exposed, so the "需要先发布一个 Revision" reason can be missing for a screen reader (the `title` is the fallback); positive notes — state is never color-only, every icon-only control has an accessible name, and measured contrast is 5.0–6.7:1.

**Jordan (first-timer)**: `草稿 v7`, `revision 3f7a91c4`, `HISTORICAL_BARS`, `probe_contract`, `重置契约` appear without gloss; the difference between 保存草稿 and 发布 Revision — the single most consequential pair on the surface — is not explained next to the buttons; the monogram icon means two Binance sources look identical until the name is read.

## Minor Observations

- The degraded card stacks three notices (state line, prose line, `该类型未提供连接测试`) where one combined line would do.
- The Probe failure row puts the human sentence and the canonical error code at equal weight in the same paragraph; the code is copy-to-issue material, not a sentence.
- Overlay shadows use `1px border + 18/32px blur`; legal per `DESIGN.md` (浮层允许一层柔和阴影) but it is the generic "hairline + big blur" tell — tightening to ~`0 8px 20px rgba(32,36,43,0.14)` reads more deliberate.
- With two sources the fixed-height modal leaves roughly half its area empty; the fixed height is a deliberate cross-tab decision, so this is a trade, not a bug.
- `overused-font` (Inter at 59–61% of text) is a **false positive**: one family is the documented intent for this Operate surface, and `DESIGN.md` says so explicitly.
- Findings attributed to the shell, not this slice: `undersized-ui-text` on the `OA` brand mark and the `synthetic` tags (10.88px) and `tiny-text` on the watchlist note (11.52px). They will keep appearing in any critique of this app until the shell is addressed.

## Questions to Consider

- If the Popover could open a source's configuration directly, would the Configured tab still need to be the default landing view?
- Does the Workspace entry need to show a numeric count at all, or would the state mark plus "有问题" be enough at 40px?
- What would this surface look like if it treated **bindings** as the primary object and sources as their implementation — would the missing canonical capability become more visible instead of less?
- Is `归档（删除）` honest enough when the reverse operation does not exist in the UI?
