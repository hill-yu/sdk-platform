# SDK 全站明亮主题实施计划

> **面向执行代理：** 使用 executing-plans 逐任务执行；root 只负责决策，既有执行窗口实施、既有审查窗口独立验收，不新增窗口。

**目标：** 将用户批准的明亮首页风格扩展至全站，修复移动端裁切。

**架构：** Vue 3 全局浅色 token + 公共外壳 + 各功能局部语义样式；不引入新组件库，不改 API/业务。完整批准规格见 `docs/superpowers/specs/2026-10-14-global-light-theme-design.md`。

**技术栈：** Vue 3、Vue Router、ECharts、Vite、Vitest；浏览器自动化使用可用的内置浏览器，否则 Playwright。

## 约束和基线

- 从 `689a92aef7e4cab611a2b9c98ac62df32cd8d06b` 核实最新 master 后建立 `codex/global-light-theme-20261014` 独立 worktree；保留主仓所有 dirty/untracked。
- 将 root 创建的规格与本计划复制到新工作树并提交，仅处理任务相关文件。
- 无生产访问，无合并、推送、部署；不得掺入 overview 慢查询或配置业务修复。
- 禁止只改 variables.css 后用全局 !important 覆盖深色；组件清理列表与状态 tokens 以规格为准。

## 任务 1：公共主题与全路由外壳

**文件：** `frontend/src/styles/variables.css`、`frontend/src/styles/variables.test.ts`、`frontend/src/components/AppLayout.vue`、`frontend/src/components/AppLayout.test.ts`、`frontend/src/components/StatCard.vue`、`frontend/src/components/TrendChart.vue`、`frontend/src/components/TrendChart.test.ts`、`frontend/src/components/trendOption.ts`。

- [ ] 全量基线：在新工作树 frontend 运行 `npm run test -- --run`、`npm run build`；目前基线为 202 tests。npm 安装如遇文件锁使用新目录，不结束用户进程。
- [ ] 修改旧 route-light 测试为四路由统一浅色测试，新增 token/状态检查和默认图表浅色断言，先执行定向测试并记录红灯。

```ts
expect(css).toContain('color-scheme: light');
expect(buildTrendOption({title: '事件趋势', labels: [], counts: []}).series.map(x => x.type)).toEqual(['line', 'line']);
```

- [ ] 将规格 tokens 提升到全局，清除 home-light 路由条件；公共导航始终浅色，保持准确 active 路由和标题；图表默认浅色、双轴、减弱动态设置有效。不要改数据数组或数值。
- [ ] `npm run test -- --run src/styles/variables.test.ts src/components/AppLayout.test.ts src/components/TrendChart.test.ts` 至绿后提交该任务。

## 任务 2：日志相关所有页面及浮层

**文件：** `frontend/src/views/LogViewer.vue`；`frontend/src/components/LogAnalysisFilters.vue`、`LogMetricsPanel.vue`、`LogParseTaskPanel.vue`、`LogColumnSettings.vue`、`LogFailureDrawer.vue`、`LogDetail.vue`、`LogAnalysisDetail.vue`、`LogExportPanel.vue`、`PackageMultiSelect.vue`、`PackageProfileCell.vue`、`UsageDurationPanel.vue` 及对应现有 `*.test.ts`。

- [ ] 增加样式契约测试，检查日志三标签、浮层、代码区没有已知深底浅字/琥珀主色。先验证旧组件失败。
- [ ] 逐个替换硬编码背景/前景/状态色为 tokens，保持原 template 事件、props、请求参数、轮询生命周期和禁用逻辑。
- [ ] 表格、使用时长七桶、指标明细、导出区各自内部横滚；抽屉/弹窗可在短屏内部滚动，按钮始终可达。包名下拉、native option 均浅底深字。
- [ ] 运行 `npm run test -- --run src/views/LogViewer.test.ts src/components/UsageDurationPanel.test.ts src/components/LogMetricsPanel.test.ts src/components/LogExportPanel.test.ts src/components/LogColumnSettings.test.ts src/components/LogFailureDrawer.test.ts src/components/LogDetail.test.ts src/components/LogAnalysisDetail.test.ts src/components/LogAnalysisFilters.test.ts src/components/LogParseTaskPanel.test.ts src/components/PackageProfileCell.test.ts src/components/PackageMultiSelect.test.ts`；全部通过再提交。

## 任务 3：配置、版本及移动端

**文件：** `frontend/src/views/ConfigManager.vue`、`VersionManager.vue`、`Dashboard.vue`；`frontend/src/components/ConfigFileTabs.vue`、`ConfigTreeNode.vue`、`ConfigTreeEditor.vue` 及对应测试；`frontend/src/views/PageScrollStructure.test.ts`。

- [ ] 为主题、宽度/滚动容器补红灯测试，不删除配置保存/发布超时确认和未保存编辑内容测试。
- [ ] 统一版本列表/分页、树编辑/JSON编辑、状态标签、表单和提示。保持10/20/50分页、创建草稿选中页、树增删、保存/发布行为。
- [ ] 修复小屏实际根因：grid/flex 子项 min-width:0、控件 max-width:100%、导航可完整访问、图表 resize；不能用外层 hidden 遮住宽内容。
- [ ] `npm run test -- --run src/views/Dashboard.test.ts src/views/ConfigManager.test.ts src/views/PageScrollStructure.test.ts src/components/ConfigFileTabs.test.ts src/components/ConfigTreeEditor.test.ts` 至绿后提交。

## 任务 4：浏览器和独立审查

- [ ] 创建独立 loopback 本地预览，使用 mock 数据和 mock 请求，不接生产 token；源代码不嵌入模拟统计。
- [ ] 一次批量检查1536×1024、1366×768、390×844，四路由和日志三个标签、抽屉、指标弹窗、JSON/树编辑状态；涵盖loading/empty/error/disabled/focus。保存每个视图可读截图。
- [ ] 用 Playwright `page.evaluate` 获取 document/body/route/control rect 与 scrollWidth；工具不可用先解决浏览器环境，禁止只用截图猜测测量结果。以失败项目清单一次集中修复，再一次确认，不反复重跑无效 Chrome CDP/DOMdump。

```js
const widths = await page.evaluate(() => ({
  viewport: document.documentElement.clientWidth,
  document: document.documentElement.scrollWidth,
  body: document.body.scrollWidth,
}));
```

- [ ] 同时检查控件 bounding box、可滚动容器 scrollLeft/scrollTop 和滚动后操作可达，防止 hidden 形成假通过。保留图表、表格内合法滚动，不要求所有表格列挤进手机宽度。
- [ ] 逐页面 `view_image` 对照已批准首页与前期日志/配置概念：白色外壳、蓝主色、6px控件、清晰表格和无深色残留；不新增指标/入口。
- [ ] 全量 `npm run test -- --run`、`npm run build`、`git diff --check`；`git diff 689a92a -- backend` 必须为空。
- [ ] 写 `docs/60-GLOBAL-LIGHT-THEME-LOCAL-ACCEPTANCE-20261014.md`（若占用选下个编号）：源码SHA、命令结果、截图、DOM测量、流程、色值扫描例外和限制。临时QA脚本不入git，保留可访问预览及用户需要的截图。
- [ ] 独立审查窗口核对代码/规格、复跑测试、检查本地预览和截图/测量。必须修复的问题回交执行窗口，不由root实施。
- [ ] 交root准确head、worktree、preview URL、各页面截图和验收结论。未获新授权不合并推送或部署。
