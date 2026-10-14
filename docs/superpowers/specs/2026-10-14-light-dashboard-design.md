# 明亮版 SDK 后台首页设计锁定

来源：批准概念图 `docs/superpowers/plans/2026-10-14-light-dashboard-concept.png`。

## 视觉 tokens

- 画布：`#f5f7fa`
- 内容与侧栏：`#ffffff`
- 主色：`#2563eb`
- 正文：`#1f2937`
- 次要文字：`#64748b`
- 边界：`#e5e7eb`
- 控件边界：`#cbd5e1`
- 圆角：6px 为首页面板/导航主轮廓；表格与控件沿用现有 6–12px 体系
- 侧栏：约 224px；移动端折叠为横向可滚动导航

## 页面结构

- AppLayout 仅在 dashboard route 增加 `home-light` 作用域。
- 首页顶部显示“运营中台 / 数据大盘”和“北京时间 UTC+8”；其他 route 保留原 Admin Console 与本地 token 提示。
- 指标条横向分隔展示今日 PV、今日 UV、今日事件数、活跃设备及既有较昨日趋势。
- 趋势区独占宽度，保留 24 小时/7 天/30 天与全部/click/log。
- 趋势 light option 为事件数折线 + UV 折线，双 Y 轴明确标注“事件数”和“UV”；默认 option 保持事件数柱状 + UV 折线。
- 下方为事件分布与事件明细，保留既有筛选、8 条分页、点击展开 JSON。
- 小屏单列，明细表在内部横向滚动容器中，分页位于滚动体外。

## 交互与无障碍

- 所有原 API 参数、分页和展开行为不变；不添加 mock 到生产代码。
- select/input/button 保持浅色可读文字和可见 keyboard focus。
- 保留 loading、error、empty 状态。
- 图表开启 aria 描述配置；CSS 在 reduced-motion 下禁用长动画过渡。

