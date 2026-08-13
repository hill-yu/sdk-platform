# 日志查看与配置树形编辑器实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法跟踪进度。

**目标：** 新增可筛选、分页并查看完整日志详情的独立页面，并将配置路径表格替换为三个配置文件标签下的递归树形 JSON 编辑器。

**架构：** 后端仅扩展现有 Admin 事件查询，增加受枚举约束的 `log_level` 过滤并补齐 `sdk_version` 响应字段。前端日志页复用事件 API；配置编辑器以完整 JSON 数据为唯一状态，由纯函数工具执行不可变增删改移和校验，递归组件只负责展示与派发操作，`ConfigManager` 负责三个根配置、模式切换及现有保存发布流程。

**技术栈：** FastAPI、SQLAlchemy Async、PostgreSQL JSONB、Vue 3 Composition API、Vue Router、Axios、TypeScript、Vitest、Pytest。

---

## 文件结构

### 后端

- 修改 `backend/app/api/admin/dashboard.py`：声明 `log_level` 枚举参数并传入服务层。
- 修改 `backend/app/services/analysis_service.py`：按 `payload.level` 过滤日志，事件响应补充 `sdk_version`。
- 修改 `backend/tests/test_analysis_service.py`：覆盖级别过滤、SDK 版本输出和既有筛选回归。
- 修改 `backend/tests/test_admin_api.py`：覆盖合法/非法 `log_level` 的 HTTP 契约。

### 前端日志页面

- 修改 `frontend/src/api/dashboard.ts`：增加事件查询参数类型，供 Dashboard 和日志页复用。
- 修改 `frontend/src/api/dashboard.test.ts`：验证日志筛选参数原样发送。
- 修改 `frontend/package.json`：加入 Vue 组件测试依赖。
- 修改 `frontend/package-lock.json`：锁定组件测试依赖。
- 修改 `frontend/vite.config.ts`：配置 Vitest DOM 测试环境。
- 创建 `frontend/src/components/TestMount.test.ts`：验证 Vue 组件挂载基础设施。
- 创建 `frontend/src/components/LogDetail.vue`：只负责日志详情、长文本和复制事件。
- 创建 `frontend/src/components/LogDetail.test.ts`：验证详情、空值和复制行为。
- 创建 `frontend/src/views/LogViewer.vue`：负责筛选、分页、查询状态和选中日志。
- 创建 `frontend/src/views/LogViewer.test.ts`：验证查询参数、分页重置、详情选择和错误保留。
- 修改 `frontend/src/router/index.ts`：注册 `/logs` 路由。
- 修改 `frontend/src/components/AppLayout.vue`：增加导航和页面标题。
- 修改 `frontend/src/styles/variables.css` 或页面 scoped style：补充日志级别标签和详情布局所需样式，不改变全局主题。

### 前端树形编辑器

- 创建 `frontend/src/utils/configTree.ts`：定义 JSON 类型、深拷贝、不可变路径操作、校验和错误定位。
- 创建 `frontend/src/utils/configTree.test.ts`：纯函数覆盖特殊键、对象/数组增删复制移动、类型切换及校验。
- 创建 `frontend/src/components/ConfigTreeNode.vue`：递归渲染单节点并派发语义化操作。
- 创建 `frontend/src/components/ConfigTreeEditor.vue`：持有当前配置文件根节点的编辑上下文和确认流程。
- 创建 `frontend/src/components/ConfigTreeEditor.test.ts`：覆盖节点操作、只读态和确认行为。
- 创建 `frontend/src/components/ConfigFileTabs.vue`：三个固定配置文件标签切换。
- 创建 `frontend/src/components/ConfigFileTabs.test.ts`：覆盖标签选择与只读展示。
- 修改 `frontend/src/views/ConfigManager.vue`：改用完整 JSON 状态、三个文件标签、树形/JSON 模式和现有保存发布流程。
- 修改或替换 `frontend/src/utils/configTable.test.ts`：保留旧转换回归证据后删除不再使用的路径表格测试。
- 删除 `frontend/src/components/ConfigTableEditor.vue` 和 `frontend/src/utils/configTable.ts`：确认无引用后移除旧实现。

### 文档

- 修改 `docs/40-LATEST-API-INTEGRATION-GUIDE-20260810.md`：记录 Admin 事件查询的 `log_level` 参数与 `sdk_version` 响应。
- 修改 `docs/45-PACKAGE-NAME-LOG-INTEGRATION-20260811.md`：补充后台日志查看入口，不改变 SDK 上报协议。
- 创建 `docs/46-LOG-VIEWER-CONFIG-TREE-IMPLEMENTATION-20260813.md`：记录实现、测试、部署前检查和未变更边界。

---

### 任务 1：扩展 Admin 日志查询契约

**文件：**
- 修改：`backend/app/api/admin/dashboard.py`
- 修改：`backend/app/services/analysis_service.py`
- 测试：`backend/tests/test_analysis_service.py`
- 测试：`backend/tests/test_admin_api.py`

- [ ] **步骤 1：编写服务层失败测试**

在 `test_analysis_service.py` 增加测试，调用：

```python
await analysis_service.get_events(
    db,
    page=1,
    page_size=20,
    event_type="log",
    package_name="com.example.app",
    device_id=None,
    log_level="error",
    date_from=None,
    date_to=None,
)
```

使用 SQLAlchemy 编译结果及绑定参数验证存在 `payload.level` 条件和 `error` 参数，避免依赖精确空白格式；并断言响应事件包含 `sdk_version`。更新所有旧调用显式传 `log_level=None`。

- [ ] **步骤 2：运行定点测试确认失败**

运行：`python -m pytest backend/tests/test_analysis_service.py -q`

预期：FAIL，当前 `get_events` 不接受 `log_level` 且响应不含 `sdk_version`。

- [ ] **步骤 3：实现服务层过滤和响应字段**

将签名扩展为：

```python
async def get_events(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    event_type: str | None,
    package_name: str | None,
    device_id: str | None,
    log_level: str | None,
    date_from: date | None,
    date_to: date | None,
) -> dict[str, Any]:
```

过滤使用 SQLAlchemy JSON 文本表达式：

```python
if log_level:
    stmt = stmt.where(
        SdkEvent.event_type == "log",
        SdkEvent.payload["level"].astext == log_level,
    )
```

响应项增加：

```python
"sdk_version": e.sdk_version,
```

- [ ] **步骤 4：编写路由契约失败测试**

在 `test_admin_api.py` 覆盖：

```text
GET /api/admin/events?event_type=log&log_level=info  -> 200
GET /api/admin/events?event_type=log&log_level=fatal -> 422
```

合法值测试 monkeypatch `analysis_service.get_events`，断言 `log_level="info"` 被透传，避免依赖真实数据库。

- [ ] **步骤 5：实现受约束查询参数**

在路由使用：

```python
log_level: Literal["debug", "info", "warn", "error"] | None = Query(None)
```

并传给服务层。不得接受任意字符串，不新增新路由。

- [ ] **步骤 6：运行后端定点测试**

运行：

```bash
python -m pytest backend/tests/test_analysis_service.py backend/tests/test_admin_api.py -q
```

预期：PASS。

- [ ] **步骤 7：提交**

```bash
git add backend/app/api/admin/dashboard.py backend/app/services/analysis_service.py backend/tests/test_analysis_service.py backend/tests/test_admin_api.py
git commit -m "feat(logs): filter admin events by log level"
```

---

### 任务 2：实现独立日志查看页面

**文件：**
- 修改：`frontend/src/api/dashboard.ts`
- 修改：`frontend/src/api/dashboard.test.ts`
- 修改：`frontend/package.json`
- 修改：`frontend/package-lock.json`
- 修改：`frontend/vite.config.ts`
- 创建：`frontend/src/components/TestMount.test.ts`
- 创建：`frontend/src/components/LogDetail.vue`
- 创建：`frontend/src/components/LogDetail.test.ts`
- 创建：`frontend/src/views/LogViewer.vue`
- 创建：`frontend/src/views/LogViewer.test.ts`
- 修改：`frontend/src/router/index.ts`
- 修改：`frontend/src/components/AppLayout.vue`

- [ ] **步骤 1：安装并验证组件测试环境**

运行：

```bash
npm --prefix frontend install --save-dev @vue/test-utils happy-dom
```

在 `vite.config.ts` 增加：

```ts
test: { environment: "happy-dom" }
```

先创建一个导入不存在测试组件的最小测试并运行确认 RED；再改为挂载一个内联 Vue 组件，断言文本可见：

```ts
import { mount } from "@vue/test-utils";
import { defineComponent } from "vue";

it("mounts a Vue component", () => {
  const wrapper = mount(defineComponent({ template: "<p>ready</p>" }));
  expect(wrapper.text()).toContain("ready");
});
```

运行：`npm --prefix frontend test -- --run src/components/TestMount.test.ts`

预期：PASS，证明后续组件测试可执行。

- [ ] **步骤 2：先编写 API 参数失败测试**

测试使用尚不存在的 `EventQuery.log_level` 和 `getEvents` 类型约束。

运行：`npm --prefix frontend test -- --run src/api/dashboard.test.ts`

预期：FAIL（类型或参数契约尚未实现）。

- [ ] **步骤 3：定义事件类型和 API 参数类型**

在 `dashboard.ts` 导出：

```ts
export type LogLevel = "debug" | "info" | "warn" | "error";

export interface EventItem {
  id: number;
  event_type: string;
  package_name: string;
  device_id?: string | null;
  sdk_version?: string | null;
  payload: Record<string, unknown>;
  client_ts?: string | null;
  server_ts: string;
}

export interface EventQuery {
  page: number;
  page_size: number;
  event_type?: string;
  package_name?: string;
  device_id?: string;
  log_level?: LogLevel;
  date_from?: string;
  date_to?: string;
}
```

将 `getEvents` 参数从无约束字典改为 `EventQuery`。

- [ ] **步骤 4：运行 API 参数测试**

测试 `getEvents` 将 `event_type=log`、`log_level=error`、包名、设备和日期完整传给 Axios。

运行：`npm --prefix frontend test -- --run src/api/dashboard.test.ts`

预期：先因类型/断言缺失失败，实现后 PASS。

- [ ] **步骤 5：编写并运行日志详情失败测试**

测试以下行为：

- `null` 字段显示 `-`；
- 完整 `extra` 不截断；
- 点击“复制 extra”调用 `navigator.clipboard.writeText(String(extra ?? ""))`；
- 发出 `copy-success` 或 `copy-error`。

运行：`npm --prefix frontend test -- --run src/components/LogDetail.test.ts`

预期：FAIL，组件尚不存在。

- [ ] **步骤 6：实现 `LogDetail.vue` 并复测**

组件只接收：

```ts
defineProps<{ item: EventItem | null }>();
defineEmits<{ "copy-success": []; "copy-error": [message: string] }>();
```

长文本放入可滚动 `<pre>`，不解析 `extra` 字符串内部内容。

运行：`npm --prefix frontend test -- --run src/components/LogDetail.test.ts`

预期：PASS。

- [ ] **步骤 7：编写并运行日志页面失败测试**

使用 mock API 验证：

- 首次加载固定传 `event_type: "log"`；
- 选择 `error` 后查询传 `log_level: "error"`；
- 改筛选并点击查询将 `page` 重置为 1；
- 点击列表项显示详情；
- 查询失败时已有 `items` 不被清空；
- 复制事件更新反馈文案。
- 刷新保留筛选条件和当前页；
- 列表展示 tag/message 摘要但不展开完整 extra；
- level 使用状态标签；
- null 字段、空结果正确展示；
- 第一页禁用上一页、末页禁用下一页。

运行：`npm --prefix frontend test -- --run src/views/LogViewer.test.ts`

预期：FAIL，页面尚不存在。

- [ ] **步骤 8：实现 `LogViewer.vue` 并复测**

状态分离为：

```ts
const filters = reactive({ package_name: "", device_id: "", log_level: "", date_from: "", date_to: "" });
const result = reactive({ total: 0, items: [] as EventItem[] });
const page = ref(1);
const pageSize = 20;
const selected = ref<EventItem | null>(null);
```

`loadLogs({ resetPage: true })` 才重置页码；翻页调用不重置。请求失败不覆盖 `result.items`。

运行：`npm --prefix frontend test -- --run src/views/LogViewer.test.ts`

预期：PASS。

- [ ] **步骤 9：接入路由和导航**

增加：

```ts
{ path: "/logs", name: "logs", component: LogViewer }
```

侧边栏增加“日志查看”，`routeTitle` 对 `logs` 返回同名标题。

- [ ] **步骤 10：运行日志页面测试和构建**

```bash
npm --prefix frontend test -- --run src/api/dashboard.test.ts src/components/LogDetail.test.ts src/views/LogViewer.test.ts
npm --prefix frontend run build
```

预期：测试与类型检查全部 PASS。

- [ ] **步骤 11：提交**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/src/api/dashboard.ts frontend/src/api/dashboard.test.ts frontend/src/components/TestMount.test.ts frontend/src/components/LogDetail.vue frontend/src/components/LogDetail.test.ts frontend/src/views/LogViewer.vue frontend/src/views/LogViewer.test.ts frontend/src/router/index.ts frontend/src/components/AppLayout.vue frontend/src/styles/variables.css
git commit -m "feat(logs): add admin log viewer"
```

---

### 任务 3：建立树形编辑器纯函数内核

**文件：**
- 创建：`frontend/src/utils/configTree.ts`
- 创建：`frontend/src/utils/configTree.test.ts`

- [ ] **步骤 1：编写 JSON 类型和特殊键测试**

定义：

```ts
export type JsonScalar = string | number | boolean | null;
export type JsonValue = JsonScalar | JsonObject | JsonValue[];
export interface JsonObject { [key: string]: JsonValue }
export type TreePath = Array<string | number>;
```

测试键名 `"a.b"`、`"a[0]"`、`"中文 字段"` 通过数组路径读取和更新后保持原键，不做点号解析。

- [ ] **步骤 2：运行测试确认失败**

运行：`npm --prefix frontend test -- --run src/utils/configTree.test.ts`

预期：FAIL，模块不存在。

- [ ] **步骤 3：实现不可变基础操作**

导出并测试：

```ts
cloneJson(value: JsonValue): JsonValue
getAtPath(root: JsonValue, path: TreePath): JsonValue
replaceAtPath(root: JsonValue, path: TreePath, value: JsonValue): JsonValue
removeAtPath(root: JsonValue, path: TreePath): JsonValue
```

每个更新返回新根对象，不修改输入引用；非法路径抛出包含路径位置的错误。

- [ ] **步骤 4：实现对象操作**

导出：

```ts
addObjectField(root, objectPath, key, value)
renameObjectField(root, fieldPath, nextKey)
```

空字段名或同级重复字段名抛错。改名保留字段值，不通过 JSON 文本拼接实现。

- [ ] **步骤 5：实现数组操作**

导出：

```ts
appendArrayItem(root, arrayPath, value)
duplicateArrayItem(root, itemPath)
moveArrayItem(root, itemPath, direction: -1 | 1)
```

复制必须深拷贝；首项上移和末项下移保持原数据并由 UI 禁用对应按钮。

- [ ] **步骤 6：实现类型默认值和结构校验**

```ts
export type JsonType = "string" | "number" | "boolean" | "null" | "object" | "array";
defaultValueForType(type: JsonType): JsonValue
jsonTypeOf(value: JsonValue): JsonType
validateConfigData(value: unknown): asserts value is JsonObject
```

`validateConfigData` 检查根对象、三个根字段存在且均为 object/array/标量合法 JSON、所有 number 有限；错误包含配置文件名和树路径。

- [ ] **步骤 7：运行纯函数测试**

运行：`npm --prefix frontend test -- --run src/utils/configTree.test.ts`

预期：特殊键、不可变更新、对象操作、数组操作、类型转换和错误路径全部 PASS。

- [ ] **步骤 8：提交**

```bash
git add frontend/src/utils/configTree.ts frontend/src/utils/configTree.test.ts
git commit -m "feat(config): add immutable config tree operations"
```

---

### 任务 4：实现递归树形编辑组件

**文件：**
- 创建：`frontend/src/components/ConfigTreeNode.vue`
- 创建：`frontend/src/components/ConfigTreeEditor.vue`
- 创建：`frontend/src/components/ConfigTreeEditor.test.ts`

- [ ] **步骤 1：编写只读和标量编辑失败测试**

挂载 `ConfigTreeEditor`，验证：

- string/number/boolean/null 使用对应控件；
- number 非法时显示错误且不发出更新；
- `disabled=true` 时增删改移控件禁用，但折叠和复制文本仍可用。

运行：`npm --prefix frontend test -- --run src/components/ConfigTreeEditor.test.ts`

预期：FAIL，组件尚不存在。

- [ ] **步骤 2：编写对象操作失败测试**

验证新增子字段、同级字段、改名、删除标量；重复字段名显示局部错误，不覆盖有效模型值。

再次运行同一测试，预期仍 FAIL，且失败点对应尚未实现的对象操作。

- [ ] **步骤 3：编写数组操作和确认失败测试**

验证新增、复制、删除、上移、下移；删除非空容器和非空容器改类型时调用注入的确认函数，取消后不发出更新。

再次运行同一测试，预期仍 FAIL，且失败点对应尚未实现的数组/确认操作。

- [ ] **步骤 4：实现递归节点组件**

`ConfigTreeNode.vue` 接收：

```ts
defineProps<{
  nodeKey: string | number;
  value: JsonValue;
  path: TreePath;
  parentKind: "root" | "object" | "array";
  disabled?: boolean;
}>();
```

仅发出 `add-child`、`add-sibling`、`rename`、`replace`、`remove`、`duplicate`、`move` 语义事件。递归节点不直接维护完整根对象。

- [ ] **步骤 5：实现编辑器协调层**

`ConfigTreeEditor.vue` 接收单个配置文件 `modelValue: JsonValue`，调用 `configTree.ts` 生成新值后发出 `update:modelValue`。容器危险操作统一通过：

```ts
const confirmDestructive = (message: string) => window.confirm(message);
```

测试时通过模块 mock 控制确认结果。

- [ ] **步骤 6：运行组件测试**

运行：`npm --prefix frontend test -- --run src/components/ConfigTreeEditor.test.ts`

预期：全部 PASS，Vue 控制台无 key 或递归警告。

- [ ] **步骤 7：提交**

```bash
git add frontend/src/components/ConfigTreeNode.vue frontend/src/components/ConfigTreeEditor.vue frontend/src/components/ConfigTreeEditor.test.ts
git commit -m "feat(config): add recursive tree editor"
```

---

### 任务 5：将配置管理接入三文件树形编辑

**文件：**
- 修改：`frontend/src/views/ConfigManager.vue`
- 创建：`frontend/src/views/ConfigManager.test.ts`
- 创建：`frontend/src/components/ConfigFileTabs.vue`
- 创建：`frontend/src/components/ConfigFileTabs.test.ts`
- 删除：`frontend/src/components/ConfigTableEditor.vue`
- 删除：`frontend/src/utils/configTable.ts`
- 删除或替换：`frontend/src/utils/configTable.test.ts`

- [ ] **步骤 1：编写并运行配置文件标签失败测试**

验证恰好展示三个固定标签、点击发出选择值、当前标签有 active 状态。运行：

`npm --prefix frontend test -- --run src/components/ConfigFileTabs.test.ts`

预期：FAIL，组件尚不存在。

- [ ] **步骤 2：实现 `ConfigFileTabs.vue` 并复测**

组件只接收 `modelValue` 并发出 `update:modelValue`，不接触完整配置内容。复测预期 PASS。

- [ ] **步骤 3：编写并运行配置管理模式失败测试**

mock 配置详情包含三份不同嵌套数据，验证：

- 选择配置后默认激活 `mainConfig`；
- 三个标签切换显示各自数据；
- 当前标签的树更新只替换对应根字段；
- 选择另一个配置后重置到 `mainConfig`；
- published/archived 将树编辑器设为 disabled。

运行：`npm --prefix frontend test -- --run src/views/ConfigManager.test.ts`

预期：FAIL，页面尚未接入树形组件。

- [ ] **步骤 4：编写双模式无损测试**

使用包含特殊键和嵌套数组的数据：

```ts
{
  mainConfig: { "a.b": [{ "中文 字段": 1 }] },
  newTouchConfig: {},
  newTextRuleConfig: {}
}
```

验证树形 → JSON → 树形后 `toEqual` 原数据。JSON 缺根字段或语法错误时模式不切换且反馈可见。

再次运行页面测试，预期仍 FAIL，失败点对应尚未实现的模式切换。

- [ ] **步骤 5：重构唯一状态**

将 `editorValue/tableRows` 替换为：

```ts
const configData = ref<JsonObject>(emptyConfigData());
const jsonText = ref(JSON.stringify(configData.value, null, 2));
const mode = ref<"tree" | "json">("tree");
const activeFile = ref<"mainConfig" | "newTouchConfig" | "newTextRuleConfig">("mainConfig");
```

树形模式更新：

```ts
function updateActiveFile(value: JsonValue) {
  configData.value = { ...configData.value, [activeFile.value]: value };
}
```

- [ ] **步骤 6：实现模式切换校验**

JSON → 树形先 `JSON.parse` 再 `validateConfigData`；树形 → JSON 先校验 `configData` 再序列化。失败时不得改变 `mode`。

`currentData()` 始终返回校验后的完整三个根配置；现有保存、发布、超时重查函数不改变调用协议。

- [ ] **步骤 7：运行页面测试并移除旧路径表格实现**

先运行：`npm --prefix frontend test -- --run src/components/ConfigFileTabs.test.ts src/views/ConfigManager.test.ts`

预期：PASS。

运行：

```bash
rg -n "ConfigTableEditor|flattenConfig|rowsToConfig|configTable" frontend/src
```

确认仅剩待删除文件后删除它们。不得保留双套可编辑状态。

- [ ] **步骤 8：运行配置页面和全量前端测试**

```bash
npm --prefix frontend test -- --run src/utils/configTree.test.ts src/components/ConfigTreeEditor.test.ts src/components/ConfigFileTabs.test.ts src/views/ConfigManager.test.ts
npm --prefix frontend test -- --run
npm --prefix frontend run build
```

预期：全部 PASS；生产构建只有既有 chunk size 警告，不新增 TypeScript 错误。

- [ ] **步骤 9：提交**

```bash
git add frontend/src/views/ConfigManager.vue frontend/src/views/ConfigManager.test.ts frontend/src/components/ConfigFileTabs.vue frontend/src/components/ConfigFileTabs.test.ts frontend/src/components/ConfigTableEditor.vue frontend/src/utils/configTable.ts frontend/src/utils/configTable.test.ts
git commit -m "feat(config): edit three config files as trees"
```

---

### 任务 6：文档、全量验证与本地真实冒烟

**文件：**
- 修改：`docs/40-LATEST-API-INTEGRATION-GUIDE-20260810.md`
- 修改：`docs/45-PACKAGE-NAME-LOG-INTEGRATION-20260811.md`
- 创建：`docs/46-LOG-VIEWER-CONFIG-TREE-IMPLEMENTATION-20260813.md`

- [ ] **步骤 1：更新接口文档**

记录：

```http
GET /api/admin/events?event_type=log&package_name=com.example.app&log_level=error&page=1&page_size=20
```

明确 `log_level` 枚举、`sdk_version` 响应字段、Admin Token 和分页规则。

- [ ] **步骤 2：编写实施记录**

实施记录必须列出：新页面、树操作、未变更的加密/发布协议、测试命令、部署前检查和回滚边界。不得声称未执行的生产部署已完成。

- [ ] **步骤 3：运行残留扫描**

```bash
rg -n "ConfigTableEditor|flattenConfig|rowsToConfig" frontend/src
rg -n "log_level" backend frontend docs/40-LATEST-API-INTEGRATION-GUIDE-20260810.md
git diff --check
```

预期：旧表格实现无运行引用；`log_level` 在 API、测试、页面和现行文档均有覆盖；diff 无空白错误。

- [ ] **步骤 4：运行全量验证**

```bash
python -m pytest backend/tests -q
npm --prefix frontend test -- --run
npm --prefix frontend run build
```

预期：后端、前端测试全部通过，构建退出码为 0。

- [ ] **步骤 5：启动本地服务并做只读日志冒烟**

启动 SDK API 8100、Admin API 8101 和前端 5173，使用本地 `ADMIN_TOKEN` 验证：

- `/logs` 返回页面；
- `GET /api/admin/events?event_type=log&log_level=info` 返回 200；
- 详情显示数据库中完整 `payload.extra`；
- 复制按钮写入完整字符串。

- [ ] **步骤 6：使用专用测试草稿做配置写入冒烟**

仅对本地测试包的 draft：

1. 在 `mainConfig` 对象新增特殊键字段；
2. 在数组新增并复制一个对象元素；
3. 切换 JSON 模式确认完整结构；
4. 保存草稿；
5. 重新获取详情并比较新增结构；
6. 不发布该测试草稿。

- [ ] **步骤 7：请求代码审查并处理 Critical/Important**

按 `requesting-code-review` 技能审查规格对应范围，重点检查递归更新的不可变性、特殊键无损、危险操作确认、日志长文本安全渲染和 API 参数约束。修复全部 Critical/Important 后重新运行全量验证。

- [ ] **步骤 8：提交文档与验证记录**

```bash
git add docs/40-LATEST-API-INTEGRATION-GUIDE-20260810.md docs/45-PACKAGE-NAME-LOG-INTEGRATION-20260811.md docs/46-LOG-VIEWER-CONFIG-TREE-IMPLEMENTATION-20260813.md
git commit -m "docs: record log viewer and config tree editor"
```

---

## 完成标准

- 独立日志页面可按包名、级别、设备和日期查询并分页；
- 可查看和复制未截断的原始 `extra`；
- 三份配置可在独立标签中以递归树动态增删、复制和排序；
- 树形/JSON 往返对所有合法 JSON 键名保持数据语义无损；
- 非草稿配置严格只读，危险容器操作有确认；
- 保存继续使用现有后端加密与超时确认流程；
- 后端全量测试、前端全量测试和生产构建通过；
- 本地真实接口和专用测试草稿冒烟通过；
- 未经用户新的明确授权，不推送、不合并、不部署生产。
