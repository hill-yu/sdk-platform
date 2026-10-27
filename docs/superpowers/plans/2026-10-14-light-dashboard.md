# 明亮版 SDK 后台首页实施计划

> **面向执行代理：** 使用 executing-plans，逐任务测试与提交；主会话负责决策和审查，不实施业务代码。

**目标：** 在本地实现用户确认的蓝白首页和首页导航，保留数据/API/事件行为。

**架构：** Vue 3 + 现有 Vue Router/ECharts。样式按首页路由作用域隔离，不将深色日志、配置、版本页面强行切换到半成品浅色；首页导航为浅色，其他路由保持现状。无需引入 Element Plus 依赖：本次采用其视觉语言，不迁移全部组件。

**设计来源：** `C:/Users/喻远飞/.codex/generated_images/019f699e-c80c-7ab0-b8d5-d16af4fea6fd/exec-fb767c6e-6a8b-4f60-9805-2cdff7d5e98a.png`，用户已确认。截图数据仅用于本地 mock，不替换真实 API 数据。

## 范围与设计锁定

- 基线 master `d15e49e075d6cd7c80d997834be94d395d7c3171`，先核实最新状态，隔离分支 `codex/light-dashboard-20261014`。
- 白色侧栏、浅灰画布 `#f5f7fa`、白色内容、蓝色 `#2563eb`、文字 `#1f2937`、次要文字 `#64748b`、边界 `#e5e7eb`、6px 圆角。
- 四项指标：今日 PV、今日 UV、今日事件数、活跃设备；保留既有较昨日计算，不引入新指标。
- 四项导航：数据大盘、日志查看、配置管理、版本管理。保留路由行为；首页不展示无意义 admin_token 提示，不输出 token。
- 事件趋势保留 24 小时/7 天/30 天、全部/click/log；事件分布保留事件类型/页面/元素。
- 仅首页 light 图表将事件数柱状图改为折线图，UV 保持折线，保留双 Y 轴、tooltip/legend 与数据不变；默认深色仍柱状+折线。双轴标题明确事件数与 UV，禁止误用单标尺。
- 明细保留事件类型、包名完全匹配、起止日期、刷新、筛选、8条分页和行展开 JSON。不要修改既有分页语义或后端查询。
- 侧栏约 200–224px；内容间距 16–24px；上方指标横向分隔，趋势独占宽度，下方分布:明细约 1:3。
- 小屏折叠为单列，导航可访问，表格内部横向滚动；分页在滚动体外，主要内容和操作不得被裁切。
- “示例数据 · 非生产环境”只在离线 mock 预览出现，真实页面不假称 mock；面包屑/北京时间属于本次允许的导航文案。
- 禁止修改后端、请求超时、统计口径、生产环境，禁止合并推送部署，禁止修改用户已有脏文件。

## 文件职责

- `frontend/src/components/AppLayout.vue`：首页路由主题、导航和页头，保留其他路由旧主题。
- `frontend/src/views/Dashboard.vue`：首页模块布局和局部样式。
- `frontend/src/components/StatCard.vue`：通过可选首页样式变体实现指标条；已有调用默认行为不变。
- `frontend/src/components/TrendChart.vue`：通过可选 light 主题传递图表文字、网格、背景、线色；默认旧主题不变。
- `frontend/src/views/Dashboard.test.ts`：新增真实 mock API 交互回归测试。
- `frontend/src/components/AppLayout.test.ts`、`frontend/src/views/PageScrollStructure.test.ts`：主题隔离、滚动回归。
- `docs/superpowers/specs/2026-10-14-light-dashboard-design.md`：将以上批准范围整理为正式设计锁定文档。
- `docs/58-LIGHT-DASHBOARD-LOCAL-ACCEPTANCE-20261014.md`：记录 SHA、验证命令、截图、对照与限制；若编号已占用，使用下一个空闲编号。

## 任务 1：隔离与基线

- [ ] 检查 git status、分支、AGENTS；不套用其他项目 ADX 治理脚本；读取 frontend-app-builder、TDD、worktree 技能。
- [ ] 用 worktree 创建独立分支，保留主 checkout docs33/42 及所有 untracked；仅复制计划和概念图到该工作树。
- [ ] 在 frontend 运行 `npm run test -- --run` 和 `npm run build`，保存退出码；依赖若被 Windows 锁定，在独立 worktree 安装，不结束无关进程。
- [ ] 保存设计文档和锁定 tokens/图标/文案清单；不引入 React 或替换现有技术栈。

## 任务 2：首页和导航（TDD）

- [ ] 编写 Dashboard 测试：mock 四接口，断言四指标、筛选参数、24h/7d/30d、分布维度、分页、行展开、错误/加载/空态保留。
- [ ] AppLayout 测试首页 light class，离开首页回归既有 theme。共享图表/指标的新可选属性默认不改变非首页调用。
- [ ] 图表 option 测试：首页 light 为 line+line 且双轴，default 为 bar+line；键盘 focus、浅色 select 文字、loading/error/empty 和 reduced-motion 均保留可用。
- [ ] 先运行 `npm run test -- --run src/views/Dashboard.test.ts src/components/AppLayout.test.ts`，确认新增断言在旧实现上失败，记录红灯原因。
- [ ] 实现页面、路由作用域主题、组件可选样式变体；图表保持 ECharts 可交互、文案与按钮保持代码原生。
- [ ] 运行定向测试至绿；仅提交任务内文件。

## 任务 3：本地视觉和交互验证

- [ ] 使用独立 loopback dev server 和 browser 网络 mock，不读取/写入生产、不在源代码硬编码模拟统计；本地 mock 预览清晰标识。
- [ ] 优先内置浏览器；不可用时记录原因，使用 Playwright Chromium；不反复修复既有不稳定 CDP。
- [ ] 桌面 1536×1024、1366×768、移动端390×844；检查点击导航、明细筛选、图表选择、分页和展开，浏览器无未捕获异常。
- [ ] 对已批准概念与最新截图分别调用 view_image；核对至少五项：导航/文案、布局、排版、色值、图表、滚动/分页。
- [ ] 用一次合并缺陷修正和一次确认截图完成有界验收；不能验证的项目明确列为未通过，不虚称完全一致。
- [ ] 全量 `npm run test -- --run`、`npm run build`、`git diff --check` 必须成功，确认 backend 无差异。
- [ ] 将最终本地预览 URL、完整截图绝对路径、准确 SHA、测试输出、偏离概念原因交 root；保留用户要求的示例图，其他临时 QA 文件不进入提交。

## 任务 4：独立审查

- [ ] 审查窗口只读核对 base/head、计划、图、差异及自动化验证；独立验证首页及非首页主题回归。
- [ ] Critical/Important 修复后重新验收，根会话确认最终范围和证据。
- [ ] 只交付本地预览，不自行合并、推送或部署。


