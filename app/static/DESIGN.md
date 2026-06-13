# 相机租赁 · 租客端 DESIGN.md（活泼创意 Playful Creative）

> 依据 KAOPU-XiaoPu/web-design SKILL（Phase A→B→C）。风格种子 = Playful Creative。
> **交互层级：L2**（流畅交互 + 弹性入场 + 滚动揭示 + hover 弹跳；不做 L3 影院滚动，保下单效率）。
> 调性：大胆、有趣、年轻、跳跃。Playful 调性下允许少量 emoji 点缀（SKILL 规则）。

## 1. 视觉主题与氛围
像一张设计师朋友寄来的派对邀请函——明亮、圆润、有手作感。
一句话定调：「让租相机这件事变得轻松好玩，3 步搞定还想再来」。
关键词：奶油暖底、撞色、大圆角、弹性、blob 装饰、手写注释。

## 2. 色彩与角色（CSS 变量，含 RGB 辅助）
```
--bg:#FFF8F0        --bg-rgb:255,248,240     /* 奶油暖底 */
--surface:#FFFFFF   --surface-2:#FFF3E8
--ink:#2D2D2D       --ink-rgb:45,45,45       /* 正文 */
--ink-2:#6B6B6B     --ink-3:#A89F97          /* 次级/弱 */
--brand:#FF3366     --brand-rgb:255,51,102   /* 主强调 珊瑚红 */
--brand-700:#E0254F --brand-50:#FFE6EC
--gold:#FFD700      --gold-rgb:255,215,0     /* 辅 亮金 */
--mint:#00CC88      --mint-rgb:0,204,136     /* 三 薄荷绿 */
--ok:#00CC88 --ok-50:#E6FAF2
--warn:#FF9F1C --warn-50:#FFF1DD
--danger:#FF3366 --danger-50:#FFE6EC
--line:#FFE0CC --line-2:#FFD0B0
```
角色：primary=珊瑚红（CTA/选中/重点）；gold/mint 仅作点缀与语义（绿=有货/成功）。撞色克制：一屏主色 1、点缀 ≤2。

## 3. 字体规则
- 标题/Logo：`ZCOOL KuaiLe`（俏皮圆体中文）+ `Sora`（Latin, 700-800）。
- 正文：`Nunito`（Latin, 400-600）+ `Noto Sans SC`（中文）回退 PingFang SC。
- 手写点缀：`Caveat`（仅用于小注释/徽章，勿用于正文）。
- 禁用：正文用 Caveat/装饰体、纯衬线。
- 中文正文 ≥15px、`line-height:1.7`、`letter-spacing:.02em`；标题行高 1.2。
- 金额 `font-variant-numeric:tabular-nums`。

## 4. 组件规范（每组件 5 态 default/hover/active/focus/disabled）
- **按钮 primary**：珊瑚红实底白字，圆角 999px（胶囊），高 ≥46px，带色阴影 `0 6px 16px rgba(var(--brand-rgb),.30)`；hover→上移 2px + 阴影加深 + 轻微放大 1.03；active→回弹 .97；focus-visible→3px 珊瑚红外环；disabled→透明度 .45 灰。
- **按钮 ghost**：白底珊瑚描边圆角胶囊；hover 充 brand-50。
- **按钮 sm**：高 ≥38px 圆角 999px。
- **输入/选择**：高 ≥46px，圆角 14px，2px line 描边；focus→珊瑚描边 + brand-50 环。带 label。
- **设备卡**：白底大圆角 22px，缩略图区为暖渐变 blob + 内联 SVG 相机图标；default 带轻色阴影；hover→上移 4px + 旋转 .5° 俏皮 + 彩色阴影；选中→brand-50 底 + 珊瑚描边 + 角标对勾弹入。
- **chip 标签**：圆角 999px 粗体；有货=薄荷绿底、缺货=珊瑚红底、状态=金/珊瑚。颜色+文字双表达。
- **报价卡**：奶油底大圆角，总价超大珊瑚红数字。
- **订单行**：圆角 16px，状态 chip，操作按钮。
- **聊天气泡**：用户=珊瑚实底右对齐；助手=奶油底左对齐；圆角 18、单侧 6。
- **toast / spinner / 空态**：均有样式与文案；空态配一句俏皮文案。

## 5. 布局原则
- 4px 间距刻度：4/8/12/16/24/32/48/64。
- 容器最大宽 1160px，左右 padding 20px。
- 桌面：主区 `1fr` + AI 侧栏 380px；移动单栏。
- 设备网格 `auto-fill minmax(200px,1fr)`，gap 16px。

## 6. 深度与圆角
- 圆角：按钮/chip 999px（胶囊）、卡片 22px、输入 14px、订单行 16px。
- 阴影：带品牌色，`--sh-sm:0 3px 10px rgba(var(--brand-rgb),.10)`；`--sh-md:0 10px 26px rgba(var(--brand-rgb),.22)`（hover）。
- 可用半透明 blob（径向暖色）作氛围装饰，**不在滚动元素上 blur**。

## 7. 动效与交互（L2）
- 时序：入场/hover 用弹性 `cubic-bezier(.34,1.56,.64,1)`（轻微 overshoot）；滚动揭示 `.5s ease-out`。
- **入场**：设备卡逐个弹入（scale .9→1 + fadeUp，stagger 60ms）。
- **滚动揭示**：区块进入视口 IntersectionObserver 加 `.in` 触发弹入。
- **hover 微交互**：设备卡上移 + 轻旋转 + 彩色阴影；按钮上移 + 放大回弹；选中对勾弹入。
- **氛围**：头部奶油渐变缓动 + 角落柔和 blob（CSS-only，性能 ⭐）。
- **降级**：`@media (prefers-reduced-motion:reduce)` 关闭位移/缩放/旋转，仅留透明度。
- 性能红线：无 3D/WebGL；不在滚动/移动元素上 `filter:blur()`；不滚动劫持。

## 8. Do's & Don'ts（≥8 条，含 ≥5 反模式）
**Do**
1. 颜色一律 CSS 变量（含 RGB 辅助构造 rgba）。
2. 语义化标签 + 每个可交互元素有 hover 与 focus-visible。
3. 中文 Noto Sans SC / 标题 ZCOOL KuaiLe；正文 ≥15px/行高 1.7/字距 .02em。
4. 触控区 ≥44px；金额 tabular-nums。
**Don't（反模式）**
5. 不硬编码 hex（标记里不出现裸色值）。
6. 撞色不超过「主色 1 + 点缀 2」，不做彩虹乱配。
7. 不用纯色/灰块当图片占位。
8. 手写体 Caveat 不用于正文/价格。
9. 不在滚动/移动元素上 `filter:blur()`；不做滚动劫持；移动端不横向溢出。

## 9. 响应式
- 断点：移动 ≤600、平板 601–1024、桌面 ≥1025。
- ≤900：两栏→单栏，聊天移到主流之下，可用可滚动。
- ≤600：头部登录区换行；网格单/双列；无横向溢出；触控 ≥44px；总价字号缩放。

## 自审清单
- [ ] 9 段充实；组件 5 态齐
- [ ] 零硬编码 hex；字体 @import + 回退；中文行距/字距达标
- [ ] L2 弹性入场 + 滚动揭示 + hover；prefers-reduced-motion 降级
- [ ] 图标内联 SVG（可少量 emoji 点缀）；无纯色占位块
- [ ] 触控 ≥44px；focus-visible 可见；键盘可达
- [ ] ≤600 无横向溢出、聊天可用；加载/空/错误态齐
