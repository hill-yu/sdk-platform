# 内部滚动与 SDK 版本筛选设计

## 1. 背景与目标

当前管理后台由 `AppLayout.vue` 以自然文档高度承载页面内容。长页面会推动浏览器 `body` 整体滚动，侧边栏和顶部标题不能稳定停留；Grid/Flex 子项中的表格、编辑器和长文本还可能把页面撑出视口。日志原始视图的 `package_name` 使用文本输入，无法复用数据库已有值，也不能按包名选择 SDK 版本。

本次变更将全局应用框架固定在 `100dvh` 内，把纵向滚动责任收敛到 `RouterView` 页面内容区，并为宽表格和编辑器建立局部横向滚动边界。同时为原始日志增加数据库选项接口、包名单选下拉、按包名联动的 SDK 版本单选下拉，以及 `sdk_version` 精确筛选。

## 2. 范围

### 2.1 包含内容

- `AppLayout.vue` 与全局基础样式：固定视口框架、固定侧边栏和顶部标题、页面内容区内部纵向滚动、Grid/Flex 子项的最小尺寸约束。
- `Dashboard.vue`、`LogViewer.vue`、`ConfigManager.vue`、`VersionManager.vue`：补齐页面根、Grid/Flex 子项、表格和编辑器的滚动边界，保证桌面端和移动端均不让浏览器 `body` 代替页面滚动。
- 后端只读接口 `GET /api/admin/events/filter-options`：返回数据库中日志事件的去重、升序排列的 `package_names` 和 `sdk_versions`；传入 `package_name` 时，SDK 版本仅返回该包名下的值。
- `GET /api/admin/events`：增加 `sdk_version` 可选查询参数，采用精确匹配，保留事件类型、日志级别、包名、设备 ID、北京时间日期范围、排序、分页和响应结构。
- 前端 `dashboard.ts` 与 `LogViewer.vue`：增加选项接口类型和调用；将包名改为已有值单选下拉；增加按包名联动的 SDK 版本单选下拉；包名变化时清除无效版本；查询和翻页时传递精确筛选参数。
- 失败可用性：选项接口失败时不阻断日志列表、刷新、查询和翻页，并显示明确的选项加载失败提示。
- 测试：后端组合筛选与选项去重排序、前端联动清空与分页参数、应用滚动结构、前端全量测试、后端全量测试和前端构建。

### 2.2 非目标

- 不修改视觉主题、颜色、字体、面板装饰、间距体系或现有信息架构。
- 不重构与滚动和原始日志筛选无关的组件、服务或页面逻辑。
- 不新增多选、复杂搜索、远程模糊查询、自由输入补全或排序控件。
- 下拉框只支持单选；选项值只来自接口返回的已有数据库值；日志筛选始终为精确匹配。
- 不修改数据库表结构、事件写入协议、日志解析协议、导出接口或日志分析视图的筛选语义。
- 不改变分析视图的现有筛选和分页行为，只处理原始日志视图的事件列表筛选。

## 3. 现状基线与受影响文件

实现必须以基线 `652180f` 的实际路径为准：

| 文件 | 当前职责 | 本次职责 |
| --- | --- | --- |
| `frontend/src/components/AppLayout.vue` | 应用壳、导航、顶部标题和 `RouterView` | 建立固定视口和页面内部纵向滚动边界 |
| `frontend/src/styles/variables.css` | 全局 `html`、`body`、`#app` 基础样式 | 锁定浏览器根滚动，保留应用填满视口 |
| `frontend/src/views/Dashboard.vue` | 大盘和事件明细 | 补齐子项最小尺寸及表格局部滚动 |
| `frontend/src/views/LogViewer.vue` | 解析统计和原始日志 | 新增选项加载、联动筛选、`sdk_version` 参数和页面内宽内容边界 |
| `frontend/src/views/ConfigManager.vue` | 配置列表和树形/JSON 编辑器 | 防止编辑器和列表撑破 Grid，保留编辑器自身宽度行为 |
| `frontend/src/views/VersionManager.vue` | 版本列表和编辑弹窗 | 为版本表格增加局部滚动并限制表单 Grid 子项 |
| `frontend/src/api/dashboard.ts` | 大盘和事件 API 类型/调用 | 增加 `sdk_version` 与筛选选项 API |
| `backend/app/api/admin/dashboard.py` | 管理端大盘和事件路由 | 增加选项路由并透传 `sdk_version` |
| `backend/app/services/analysis_service.py` | 事件查询 SQL 和序列化 | 增加精确版本条件和选项查询 |
| `backend/tests/test_analysis_service.py` | 分析服务 SQL 契约 | 覆盖组合筛选、分页和去重排序 |
| `backend/tests/test_admin_api.py` | 管理端路由契约 | 覆盖路由参数透传和选项响应 |
| `frontend/src/api/dashboard.test.ts` | 前端事件 API 契约 | 覆盖版本参数和选项请求 |
| `frontend/src/views/LogViewer.test.ts` | 日志视图行为 | 覆盖联动清空、错误可用、分页参数和下拉选项 |
| `frontend/src/components/AppLayout.test.ts` | 当前不存在 | 覆盖布局滚动结构契约 |
| `frontend/src/views/PageScrollStructure.test.ts` | 当前不存在 | 覆盖各页面宽内容容器的结构契约 |

## 4. 布局与滚动行为

### 4.1 全局滚动模型

应用框架采用以下层级：

```text
html/body/#app（填满视口，body 不滚动）
└── .shell（height: 100dvh，overflow: hidden）
    ├── .sidebar（框架内固定区域，内容过长时仅自身可滚动）
    └── .content（min-width/min-height: 0）
        ├── .topbar（固定在内容区顶部，不随页面内容滚动）
        └── .page（RouterView 内容，唯一主纵向滚动容器）
```

约束如下：

- `html`、`body`、`#app` 具有填满应用的高度；`body` 使用 `overflow: hidden`，浏览器窗口不承担主页面纵向滚动。
- `.shell` 使用 `height: 100dvh`、`min-height: 0` 和 `overflow: hidden`；不得以 `min-height: 100vh` 作为主高度。
- `.content` 使用 `min-width: 0`、`min-height: 0`、两行 Grid：顶部为自适应标题行，底部为 `minmax(0, 1fr)` 的页面行。
- `.page` 使用 `min-width: 0`、`min-height: 0`、`overflow-y: auto`、`overflow-x: hidden` 和 `overscroll-behavior: contain`。页面内容只在此区域纵向滚动。
- `.topbar` 与 `.sidebar` 保持在 `.shell` 的固定框架内。侧边栏如果内容超过自身可用高度，只允许侧边栏自身出现纵向滚动，不得把滚动传给 `body`。
- 所有作为 Grid/Flex 子项的页面根、面板、双栏项、编辑器面板和列表面板补 `min-width: 0`；需要在固定高度中收缩的子项同时补 `min-height: 0`。

### 4.2 宽内容边界

- 表格的横向滚动只发生在包裹表格的 `.table-scroll` 内，容器使用 `max-width: 100%`、`min-width: 0` 和 `overflow-x: auto`。
- 宽表格可以在自身设置 `min-width` 或 `width: max-content`，但不能让祖先页面产生横向滚动。
- JSON `textarea`、树形编辑器和详情 `pre` 只能在自身面板或编辑器容器内处理宽内容；长字段使用换行或自身横向滚动，不得撑大 `.content`。
- 现有日志分析明细表的 `.table-scroll` 继续保留；本次只补它的父级最小尺寸约束。

### 4.3 页面级约束

| 页面 | 纵向滚动归属 | 横向滚动归属 | 需要保留的行为 |
| --- | --- | --- | --- |
| 数据大盘 | `.page` | 事件表的 `.table-scroll` | 趋势图、分布图、分页和展开事件不变 |
| 日志查看 | `.page` | 聚合表、原始日志表、分析明细表各自的 `.table-scroll`；编辑弹窗自身滚动 | 分析/原始视图、详情、列配置和分页不变 |
| 配置管理 | `.page` | 配置树编辑器和 JSON 编辑器自身容器 | 选择配置、树形/JSON 模式和保存流程不变 |
| 版本管理 | `.page` | 版本列表表格的 `.table-scroll`，弹窗自身在超高内容时滚动 | 平台切换、编辑、新增和启停不变 |

### 4.4 响应式行为

- 桌面端继续使用现有侧边栏、双栏和多栏布局，不改变主题和断点意图。
- 在现有断点下，侧边栏继续变为顶部区域，`.content` 仍保持 `100dvh` 框架，剩余区域由 `.page` 滚动。
- 移动端页面只在 `.page` 内纵向滚动；表格、编辑器和详情内容在自己的容器内横向处理，不能以缩放或隐藏字段替代滚动。
- 所有新增/修改的 `width: 100%` 控件与 Grid/Flex 子项必须在父项上有 `min-width: 0`，避免长包名、URL、JSON 键或按钮组造成水平溢出。

## 5. 后端接口契约

### 5.1 筛选选项接口

#### 基本信息

- **请求方式：** `GET`
- **请求路径：** `/api/admin/events/filter-options`
- **鉴权方式：** 沿用 `dashboard.router` 的 Bearer `admin_token` 鉴权
- **查询参数：** `package_name: string | null`，可选，按值精确匹配

#### 查询语义

- 只从 `sdk_events` 中 `event_type = 'log'` 的记录生成选项，因为该接口服务于原始日志视图。
- `package_names` 排除空值，按数据库值去重后使用升序排序。
- `sdk_versions` 排除 `NULL` 和空字符串；未传 `package_name` 时返回所有日志事件中的去重升序版本；传入包名时增加 `sdk_events.package_name = :package_name`，只返回该包名下的版本。
- 不做模糊匹配、大小写归一化、版本解析或自然版本排序；返回值保留数据库中的原始字符串。
- 该接口只读，不修改事件、缓存或筛选状态。

#### 响应

```json
{
  "code": 0,
  "data": {
    "package_names": ["com.example.alpha", "com.example.beta"],
    "sdk_versions": ["1.2.0", "1.10.0"]
  }
}
```

空结果仍返回 `200` 和两个空数组。鉴权失败、数据库错误沿用现有管理端错误处理；数据库错误由前端显示选项加载失败，但不得阻断日志列表请求。

### 5.2 事件列表接口

现有 `GET /api/admin/events` 增加：

| 参数 | 类型 | 必填 | 语义 |
| --- | --- | --- | --- |
| `sdk_version` | `string` | 否 | `sdk_events.sdk_version = :sdk_version` 精确匹配 |

现有参数 `page`、`page_size`、`event_type`、`log_level`、`package_name`、`device_id`、`date_from`、`date_to` 保持不变。多个条件使用 `AND`；日志级别仍限制为 `debug`、`info`、`warn`、`error`，日期仍按北京时间自然日转换为 UTC 半开区间，结果仍按 `server_ts DESC` 分页，响应中的 `sdk_version` 字段保持现状。

服务函数签名固定扩展为：

```python
async def get_events(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    event_type: str | None,
    log_level: str | None,
    package_name: str | None,
    sdk_version: str | None,
    device_id: str | None,
    date_from: date | None,
    date_to: date | None,
) -> dict[str, Any]:
    ...
```

空字符串由前端转换为未传参数；后端不将 `sdk_version` 解释为模糊查询。

## 6. 前端数据流与交互

### 6.1 原始视图初始化

进入原始日志视图时并行启动两个独立请求：

1. `getEventFilterOptions()` 获取包名选项；
2. `getEvents()` 获取第一页日志。

选项请求失败只更新独立的 `filterOptionsError` 状态；日志请求继续完成。选项请求不应包裹在会导致日志列表短路的单个 `Promise.all` 错误路径中。

### 6.2 下拉联动

- 包名下拉包含一个「全部包名」空值选项和接口返回的唯一包名；不再渲染文本输入框。
- SDK 版本下拉包含一个「全部 SDK 版本」空值选项。未选择包名时保持禁用且无版本选项；已选择包名时请求 `filter-options?package_name=<精确值>` 更新版本列表。
- 每次包名变化立即清空 `rawFilters.sdk_version`，因此旧包名下的版本不会残留到新查询中。
- 联动请求使用递增请求序号；快速切换包名时，迟到的旧响应不能覆盖当前包名的版本列表。
- 如果当前 SDK 版本不在新响应中，必须清空；即使后端因数据变化返回的选项不包含当前值，也不能发送无效组合。

### 6.3 查询、刷新和分页

`rawQueryParams()` 始终生成以下参数：`page`、`page_size`、`event_type: 'log'`，以及有值时的 `package_name`、`sdk_version`、`device_id`、`log_level`、`date_from`、`date_to`。空值转换为 `undefined`，不发送空字符串。

- 点击「查询」将页码重置为 `1`，发送当前所有筛选项。
- 点击「刷新」保留当前筛选项和当前成功页码。
- 点击分页只修改 `page`，保留当前筛选项；成功后更新当前页，失败后恢复到最后成功页。
- 事件列表请求的错误反馈与现有行为一致；选项加载错误使用单独、明确且不阻断列表的提示文案。

## 7. 错误状态与可用性

至少提供以下可观察状态：

- 选项请求加载中：下拉显示禁用/加载态，日志列表仍可显示已有数据或加载态。
- 选项请求失败：显示「包名和 SDK 版本选项加载失败，可继续查看日志并使用其他筛选条件；请刷新重试。」；不清空已经成功加载的日志列表，不抛出未处理 Promise 错误。
- 日志列表请求失败：沿用现有日志查询错误提示、当前页恢复和已有列表保留行为。
- 切换包名后版本为空：SDK 版本下拉回到「全部 SDK 版本」，不可发送上一包名版本。
- 选项为空：下拉保留全部值选项并显示空状态，不伪造默认包名或版本。

## 8. 测试设计与验收标准

### 8.1 后端

- 服务测试编译 SQL，确认 `package_name`、`sdk_version`、设备、日志级别和日期条件可以组合，版本条件是 `=`，分页仍使用 `LIMIT/OFFSET`，响应保留版本值。
- 选项服务测试提供重复、无序、空版本和不同包名的行，确认两个数组分别去重、升序、过滤空值，并确认传包名时版本查询带精确包名条件。
- 管理端路由测试确认 `sdk_version` 透传给 `get_events`，并确认 `/events/filter-options` 返回包装后的 `code/data` 响应和包名参数。
- 现有鉴权和非法日志级别测试继续通过。

### 8.2 前端

- API 测试确认 `getEvents()` 发送 `sdk_version`，`getEventFilterOptions()` 使用 `/events/filter-options` 和可选 `package_name` 参数。
- `LogViewer` 测试确认包名与版本下拉渲染、切包名清空版本、联动请求使用新包名、迟到旧响应不覆盖新选项、查询和分页参数完整。
- `LogViewer` 测试让选项请求失败，确认错误提示出现且日志列表仍加载、查询和分页仍可用。
- `AppLayout` 测试确认侧边栏、顶部标题和页面容器层级正确，RouterView 位于 `.page` 内；滚动样式契约确认 `.shell` 使用 `100dvh`，`.page` 承担纵向滚动。
- 页面结构测试确认大盘、日志、配置、版本页面的宽内容都位于自身容器，且没有移除现有表格、编辑器和弹窗滚动包裹。
- 执行前端全量测试和 `npm run build`；执行后端全量测试。

验收以零失败为准，测试数量以实际代码库输出为准。`git diff --check` 必须无输出，文档和实现中不得出现未定义接口、空泛步骤或相互冲突的滚动归属。

## 9. 发布与回滚

### 9.1 发布前

1. 在独立工作区运行后端全量测试、前端全量测试和前端构建。
2. 使用浏览器验收桌面端和移动端：浏览器 `body` 不滚动；侧边栏和顶部标题固定；页面内容区可以纵向滚动；每个宽表格/编辑器只在自身容器横向滚动。
3. 使用已有事件数据验证包名选项、包名联动版本、精确版本筛选、查询重置页码、刷新保留页码，以及选项接口失败时列表仍可用。
4. 检查 API 契约未改变既有字段和日期/分页语义，确认没有数据库迁移文件或主题改动。

### 9.2 发布

- 先部署后端，使新选项接口和 `sdk_version` 参数可用，再部署前端静态资源；后端向后兼容旧前端请求，前端只调用已部署的新接口。
- 发布后执行健康检查、鉴权检查、日志列表旧筛选 smoke、版本精确筛选 smoke、选项接口 smoke 和前端页面滚动验收。

### 9.3 回滚

- 若前端出现筛选或布局问题，先恢复前端静态资源到上一版本；旧后端兼容原有 `/events` 请求，日志查询可继续使用旧页面。
- 若新后端路由或查询导致错误，恢复后端应用版本；本次不改数据库结构，因此不需要数据库逆向迁移。
- 回滚后验证健康、鉴权、日志列表、分页和既有设备/级别/日期筛选；记录失败接口、版本和浏览器视口信息。
