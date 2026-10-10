# 配置版本分页与内部滚动实施计划

> 执行窗口使用 executing-plans、test-driven-development；主窗口只负责方案与审查，独立窗口负责验收。方案已经用户确认。

**目标：** 配置管理左侧版本列表默认每页 10 条，允许 20、50 条，支持翻页及窗口内部上下滚动。

**架构：** 保留 GET /api/admin/configs 及 published/drafts/history 响应，前端对现有 allConfigs 做 slice 分页，保留现有顺序。右侧编辑器与当前列表页分离，翻页不请求详情、不改变 selectedId/configData/jsonText。仅局部布局调整，不改后端、加密、保存、发布、回滚规则。

**技术栈：** Vue 3、TypeScript、Vitest、浏览器真实布局验收。

## 文件与范围

- 修改 `frontend/src/views/ConfigManager.vue`：分页状态/控制、版本列表滚动布局。
- 修改 `frontend/src/views/ConfigManager.test.ts`：分页交互及编辑状态回归。
- 新增本任务验收记录；若确需布局测试脚本只能服务本任务，不添加公共业务组件或依赖。
- 保留既有暗色主题与全局 select 可读性规范。不得修改接口、后端、日志模块、数据库或无关组件。

## 任务 1：红测试与分页实现

- [ ] 从 master `f4a9827531e74f8f12a59ec28d7da3a48f22a301` 创建隔离 worktree / 分支 `codex/config-version-pagination-20261010`，记录 BASE。复制本计划至 worktree 纳入提交，保留主仓全部脏文件。
- [ ] 在 ConfigManager.test.ts 用 25 条配置摘要编写失败测试：初次只渲染 10 条，上一页禁用，下一页显示第 11–20 条，再下一页显示最后 5 条并禁用下一页；标题/分页不作为 list-item 计数。
- [ ] 运行 `npm run test -- --run src/views/ConfigManager.test.ts`，保存旧实现红测证据。
- [ ] 实现 page=1、pageSize=10、可选 [10,20,50]、total=allConfigs.length、pageCount=max(1,ceil(total/pageSize))、visibleConfigs=slice((page-1)*pageSize,page*pageSize)。只有列表模板切换为 visibleConfigs，selectedConfig 仍从 allConfigs 查找。
- [ ] 上/下一页边界禁用，显示总条数和当前页/总页，每页条数选择控件有明确 label。分页移动后滚动列表回顶部，不改变编辑器数据或选择配置。
- [ ] 每页条数变化、用户点击包名筛选回第 1 页；不能把内部 save/publish 调用 loadConfigs 的刷新当作用户筛选而无条件回第 1 页。列表刷新后页码越界则夹到合法末页。
- [ ] 新建草稿成功后 refresh，再根据返回的 ID 在 allConfigs 中的索引定位所在页，最后选中该草稿；不得只猜第 1 页。保留此前选详情的请求序列保护。
- [ ] 补 20/50、空列表、刷新末页减少、包名筛选重置、翻页不触发 getConfig、右侧未保存 JSON/tree 值不丢失、新草稿定位所在页、保存发布现有测试。

## 任务 2：内部滚动布局

- [ ] `.list-panel` 使用受视口约束的 flex column，标题和分页栏 flex-shrink:0；中间列表容器 min-height:0、overflow-y:auto、overscroll-behavior:contain，限制滚动传播到外页。
- [ ] 遵循现有 layout/app shell 的高度限制；桌面为配置版本窗内滚动，窄屏使用合理视口高度上限，不能要求全页面固定且剪裁右侧编辑器。需要 min-height:0 / min-width:0 的布局链补在本文件局部，不大范围修改 App.vue。
- [ ] 列表滚动时标题、分页仍可见；10/20/50 条均支持窗口内滚动。选择框背景/文字沿用全局主题避免白底白字。
- [ ] 全前端 `npm run test -- --run`、`npm run build` 均通过，记录实际命令、退出码及数量。
- [ ] 在浏览器用 mock 配置摘要（不改真实数据）验收桌面与窄屏：列表scrollHeight>clientHeight、滚动前后标题/分页位置稳定、列表外容器不被版本数量撑高、20/50选项可读、翻页保留右侧未保存文本。提供截图/结构测量证据。没有浏览器可用就明确报告不能声称视觉验收通过。

## 审查与交付

- [ ] 只提交本任务文件与验收记录；报告绝对 worktree、BASE、HEAD、红绿测试、全部前端测试/build、浏览器证据；不合并、不推送、不部署。
- [ ] 独立审查锁定精确 HEAD，复跑测试，验证分页边界/当前编辑状态/草稿定位/刷新行为/内部滚动。主窗口复核 diff 与要求。
- [ ] 通过后向用户交付实现情况与记录。生产发布需要用户后续明确授权，不继承上个解析故障部署授权。

