# 内部滚动与 SDK 版本筛选实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（- [ ]）语法跟踪进度。

**目标：** 将管理后台固定在 100dvh 应用框架内，让 RouterView 页面内容区承担纵向滚动，并为原始日志增加已有包名/SDK 版本单选筛选和后端精确匹配。

**架构：** 后端在现有管理端 dashboard 路由下增加只读选项接口，并在 analysis_service.get_events() 的同一 SQL 查询中追加可选 sdk_version = 条件；前端以独立状态加载选项，包名变化立即清除 SDK 版本并按包名重新加载版本选项，选项失败不影响事件列表。AppLayout 使用固定视口 Grid，页面根使用内部滚动，表格和编辑器继续在自身容器中处理横向内容。

**技术栈：** Python 3.11、FastAPI、SQLAlchemy 2 async、PostgreSQL、pytest、Vue 3、TypeScript、Vitest、Vite。

---

## 文件结构

- 修改 backend/app/services/analysis_service.py：增加日志筛选选项查询，扩展事件列表的 sdk_version 精确条件。
- 修改 backend/app/api/admin/dashboard.py：增加 GET /events/filter-options，并向事件服务透传 sdk_version。
- 修改 backend/tests/test_analysis_service.py：覆盖组合筛选、分页和选项去重排序。
- 修改 backend/tests/test_admin_api.py：覆盖事件版本参数透传和选项接口响应。
- 修改 frontend/src/api/dashboard.ts：增加 EventFilterOptions、sdk_version 查询字段和选项 API。
- 修改 frontend/src/api/dashboard.test.ts：覆盖事件版本参数与选项接口请求参数。
- 修改 frontend/src/views/LogViewer.vue：将包名改为单选下拉，增加 SDK 版本联动、选项错误状态和版本分页参数。
- 修改 frontend/src/views/LogViewer.test.ts：覆盖下拉联动、迟到响应、错误可用和分页参数。
- 修改 frontend/src/styles/variables.css：锁定 html、body、#app 高度并禁止浏览器根滚动。
- 修改 frontend/src/components/AppLayout.vue：建立 100dvh 框架、固定标题/侧边栏和 .page 内部纵向滚动。
- 创建 frontend/src/components/AppLayout.test.ts：验证布局节点层级和滚动容器契约。
- 修改 frontend/src/views/Dashboard.vue：补齐 Grid/Flex 子项最小尺寸和事件表局部滚动边界。
- 修改 frontend/src/views/ConfigManager.vue：补齐配置 Grid、面板和编辑器的最小尺寸约束。
- 修改 frontend/src/views/VersionManager.vue：增加版本表局部滚动容器并限制表单 Grid 子项。
- 创建 frontend/src/views/PageScrollStructure.test.ts：验证四个页面的宽内容容器没有移除。
- 修改 docs/42-PRODUCTION-SYSTEM-API-BASELINE-20260811.md：记录选项接口和 sdk_version 精确筛选契约。

明确不修改：数据库迁移、事件模型、日志写入、日志分析接口、导出接口、视觉主题变量的颜色/字体/装饰值，以及与本需求无关的组件重构。

## 任务 1：后端服务先锁定筛选与选项 SQL 契约

**文件：**

- 修改：backend/tests/test_analysis_service.py
- 修改：backend/app/services/analysis_service.py

- [ ] **步骤 1：运行后端基线测试并记录实际结果**

运行：

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK\backend'
python -m pytest -q
~~~

预期：命令完成且失败数为 0。记录实际通过数量，不在计划中写死会因本次新增测试而变化的总数。

- [ ] **步骤 2：编写 get_events() 的失败测试**

在现有事件测试的所有直接调用中补充 sdk_version=None，并新增以下组合筛选测试：

~~~python
@pytest.mark.asyncio
async def test_events_combine_package_sdk_device_level_and_date_filters() -> None:
    event = SimpleNamespace(
        id=5,
        event_type="log",
        package_name="com.example.app",
        device_id="device-5",
        sdk_version="1.4.0",
        payload={"level": "error", "message": "boom"},
        client_ts=None,
        server_ts=None,
    )
    db = _EventSession(event)

    result = await get_events(
        db,
        page=2,
        page_size=20,
        event_type="log",
        log_level="error",
        package_name="com.example.app",
        sdk_version="1.4.0",
        device_id="device-5",
        date_from=date(2026, 8, 17),
        date_to=date(2026, 8, 17),
    )

    compiled = db.statements[1].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "sdk_events.package_name" in sql
    assert "sdk_events.sdk_version" in sql
    assert "sdk_events.device_id" in sql
    assert "sdk_events.payload ->>" in sql
    assert {"log", "error", "com.example.app", "1.4.0", "device-5"} <= set(compiled.params.values())
    assert result["page"] == 2
    assert result["page_size"] == 20
    assert result["items"][0]["sdk_version"] == "1.4.0"
~~~

- [ ] **步骤 3：编写筛选选项去重、排序和包名联动的失败测试**

在同一测试文件增加确定性 fake session，使第一次执行返回包名行，第二次执行返回版本行：

~~~python
class _OptionRows:
    def __init__(self, values: list[tuple[str | None]]) -> None:
        self.values = values

    def all(self) -> list[tuple[str | None]]:
        return self.values


class _OptionSession:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _OptionRows:
        self.statements.append(statement)
        if len(self.statements) == 1:
            return _OptionRows([("com.example.beta",), ("com.example.alpha",), ("com.example.alpha",)])
        return _OptionRows([("1.10.0",), ("1.2.0",), ("1.2.0",), (None,)])


@pytest.mark.asyncio
async def test_event_filter_options_are_distinct_sorted_and_package_scoped() -> None:
    db = _OptionSession()

    result = await analysis_service.get_event_filter_options(db, package_name="com.example.alpha")

    assert result == {
        "package_names": ["com.example.alpha", "com.example.beta"],
        "sdk_versions": ["1.10.0", "1.2.0"],
    }
    package_sql = str(db.statements[0].compile(dialect=postgresql.dialect()))
    version_sql = str(db.statements[1].compile(dialect=postgresql.dialect()))
    assert "DISTINCT" in package_sql
    assert "ORDER BY sdk_events.package_name" in package_sql
    assert "sdk_events.package_name" in version_sql
    assert "ORDER BY sdk_events.sdk_version" in version_sql
~~~

- [ ] **步骤 4：运行目标测试，确认失败原因来自新契约缺失**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK\backend'
python -m pytest tests/test_analysis_service.py -q
~~~

预期：新增测试失败：get_events() 尚未接受 sdk_version，get_event_filter_options() 尚不存在；现有未改动测试失败信息不能被忽略。

- [ ] **步骤 5：实现最小服务修改**

在 analysis_service.py 中将 get_events() 签名改为包含 sdk_version: str | None，在 package_name 条件后追加：

~~~python
if sdk_version:
    stmt = stmt.where(SdkEvent.sdk_version == sdk_version)
~~~

在同一文件新增：

~~~python
async def get_event_filter_options(
    db: AsyncSession,
    *,
    package_name: str | None,
) -> dict[str, list[str]]:
    """返回原始日志视图使用的去重、升序筛选选项。"""
    package_stmt = (
        select(SdkEvent.package_name)
        .where(SdkEvent.event_type == "log", SdkEvent.package_name != "")
        .distinct()
        .order_by(SdkEvent.package_name)
    )
    version_stmt = (
        select(SdkEvent.sdk_version)
        .where(
            SdkEvent.event_type == "log",
            SdkEvent.sdk_version.is_not(None),
            SdkEvent.sdk_version != "",
        )
        .distinct()
        .order_by(SdkEvent.sdk_version)
    )
    if package_name:
        version_stmt = version_stmt.where(SdkEvent.package_name == package_name)

    package_rows = (await db.execute(package_stmt)).all()
    version_rows = (await db.execute(version_stmt)).all()
    return {
        "package_names": [row[0] for row in package_rows],
        "sdk_versions": [row[0] for row in version_rows],
    }
~~~

保持原有日期边界、排序、LIMIT/OFFSET、序列化和日志级别条件原样不动。

- [ ] **步骤 6：运行后端服务目标测试**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK\backend'
python -m pytest tests/test_analysis_service.py -q
~~~

预期：该文件全部通过，新增测试确认版本是精确匹配，选项结果为去重升序。

- [ ] **步骤 7：提交后端服务变更**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK'
git add backend/app/services/analysis_service.py backend/tests/test_analysis_service.py
git commit -m "feat: add sdk version event filters"
~~~

## 任务 2：接通后端管理路由并固定 API 契约

**文件：**

- 修改：backend/app/api/admin/dashboard.py
- 修改：backend/tests/test_admin_api.py

- [ ] **步骤 1：编写管理路由失败测试**

在管理端 API 测试中增加：

~~~python
def test_admin_events_passes_sdk_version_to_service(monkeypatch):
    from app.admin_main import app
    from app.api.admin import dashboard

    async def fake_get_events(_db: Any, **filters: Any) -> dict[str, Any]:
        assert filters["sdk_version"] == "1.4.0"
        return {"total": 0, "page": 1, "page_size": 20, "items": []}

    monkeypatch.setattr(dashboard.analysis_service, "get_events", fake_get_events)

    with TestClient(app) as client:
        response = client.get(
            "/api/admin/events?sdk_version=1.4.0",
            headers=_auth_headers(),
        )

    assert response.status_code == 200


def test_event_filter_options_returns_payload(monkeypatch):
    from app.admin_main import app
    from app.api.admin import dashboard

    async def fake_options(_db: Any, *, package_name: str | None) -> dict[str, list[str]]:
        assert package_name == "com.example.alpha"
        return {
            "package_names": ["com.example.alpha"],
            "sdk_versions": ["1.2.0"],
        }

    monkeypatch.setattr(dashboard.analysis_service, "get_event_filter_options", fake_options)

    with TestClient(app) as client:
        response = client.get(
            "/api/admin/events/filter-options?package_name=com.example.alpha",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "data": {
            "package_names": ["com.example.alpha"],
            "sdk_versions": ["1.2.0"],
        },
    }
~~~

- [ ] **步骤 2：运行路由测试确认缺少参数和路由**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK\backend'
python -m pytest tests/test_admin_api.py -q
~~~

预期：新增测试失败：事件 fake service 未收到 sdk_version，选项路径返回 404 或服务函数不存在；现有管理端测试仍需保持通过。

- [ ] **步骤 3：实现路由透传**

在事件路由签名中加入：

~~~python
sdk_version: str | None = Query(None),
~~~

并在服务调用中加入：

~~~python
sdk_version=sdk_version,
~~~

新增路由：

~~~python
@router.get("/events/filter-options")
async def get_event_filter_options(
    package_name: str | None = Query(None),
    db: AsyncSession = Depends(get_db_no_commit),
):
    data = await analysis_service.get_event_filter_options(db, package_name=package_name)
    return {"code": 0, "data": data}
~~~

保持现有 Router 鉴权依赖和 /api/admin prefix，不新增数据库依赖或路由模块。

- [ ] **步骤 4：运行后端路由回归测试**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK\backend'
python -m pytest tests/test_admin_api.py tests/test_analysis_service.py -q
~~~

预期：目标文件全部通过，非法日志级别仍为 422，无鉴权请求仍为 401。

- [ ] **步骤 5：提交后端 API 变更**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK'
git add backend/app/api/admin/dashboard.py backend/tests/test_admin_api.py
git commit -m "feat: expose event filter options"
~~~

## 任务 3：锁定前端 API 类型和请求参数

**文件：**

- 修改：frontend/src/api/dashboard.ts
- 修改：frontend/src/api/dashboard.test.ts

- [ ] **步骤 1：编写前端 API 失败测试**

扩展 API 测试：

~~~ts
import { getEventFilterOptions, getEvents } from "@/api/dashboard";

it("sends sdk version as an exact event filter", () => {
  const params: EventQuery = {
    page: 1,
    page_size: 20,
    event_type: "log",
    package_name: "com.example.app",
    sdk_version: "1.4.0",
  };

  getEvents(params);

  expect(request.get).toHaveBeenCalledWith("/events", { params });
});

it("loads filter options with an optional exact package name", () => {
  getEventFilterOptions("com.example.app");

  expect(request.get).toHaveBeenCalledWith("/events/filter-options", {
    params: { package_name: "com.example.app" },
  });
});
~~~

- [ ] **步骤 2：运行前端 API 测试确认类型和函数不存在**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK\frontend'
npm test -- --run src/api/dashboard.test.ts
~~~

预期：TypeScript/Vitest 报告 sdk_version 或 getEventFilterOptions 缺失。

- [ ] **步骤 3：实现前端 API 类型和调用**

在 dashboard.ts 中加入：

~~~ts
export interface EventFilterOptions {
  package_names: string[];
  sdk_versions: string[];
}

export interface EventQuery {
  page: number;
  page_size: number;
  event_type?: string;
  package_name?: string;
  sdk_version?: string;
  device_id?: string;
  log_level?: LogLevel;
  date_from?: string;
  date_to?: string;
}

export const getEventFilterOptions = (packageName?: string) =>
  request.get("/events/filter-options", {
    params: { package_name: packageName || undefined },
  });
~~~

保留现有 getEvents 调用和请求拦截器。

- [ ] **步骤 4：运行前端 API 测试和类型构建**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK\frontend'
npm test -- --run src/api/dashboard.test.ts
npm run build
~~~

预期：API 测试通过，vue-tsc 和 Vite 构建通过。

- [ ] **步骤 5：提交前端 API 变更**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK'
git add frontend/src/api/dashboard.ts frontend/src/api/dashboard.test.ts
git commit -m "feat: type event filter options"
~~~

## 任务 4：实现日志页下拉联动、错误隔离和分页参数

**文件：**

- 修改：frontend/src/views/LogViewer.vue
- 修改：frontend/src/views/LogViewer.test.ts

- [ ] **步骤 1：为日志页准备选项 mock 并编写失败测试**

在 hoisted mock 增加 getEventFilterOptions: vi.fn()，在 beforeEach 默认返回：

~~~ts
getEventFilterOptions.mockResolvedValue({
  data: {
    package_names: ["com.example.app", "com.example.other"],
    sdk_versions: ["1.2.3", "1.4.0"],
  },
});
~~~

新增测试必须覆盖以下行为：

~~~ts
it("clears sdk version when package changes and sends exact filters", async () => {
  const wrapper = await mountViewer();

  await wrapper.get("[data-testid='package-filter']").setValue("com.example.other");
  expect(wrapper.get<HTMLSelectElement>("[data-testid='sdk-version-filter']").element.value).toBe("");
  await wrapper.get("[data-testid='query-button']").trigger("click");
  await flushPromises();

  expect(getEvents).toHaveBeenLastCalledWith(expect.objectContaining({
    page: 1,
    page_size: 20,
    event_type: "log",
    package_name: "com.example.other",
    sdk_version: undefined,
  }));
  expect(getEventFilterOptions).toHaveBeenLastCalledWith("com.example.other");
});

it("preserves sdk version and filters during pagination", async () => {
  respond([makeItem()], 41);
  const wrapper = await mountViewer();

  await wrapper.get("[data-testid='package-filter']").setValue("com.example.app");
  await flushPromises();
  await wrapper.get("[data-testid='sdk-version-filter']").setValue("1.4.0");
  await wrapper.get("[data-testid='query-button']").trigger("click");
  await wrapper.get("[data-testid='next-page']").trigger("click");
  await flushPromises();

  expect(getEvents).toHaveBeenLastCalledWith(expect.objectContaining({
    page: 2,
    package_name: "com.example.app",
    sdk_version: "1.4.0",
  }));
});

it("keeps the log list usable when filter options fail", async () => {
  getEventFilterOptions.mockRejectedValueOnce(new Error("options unavailable"));
  const wrapper = await mountViewer();
  await flushPromises();

  expect(wrapper.get("[data-testid='filter-options-error']").text()).toContain("选项加载失败");
  expect(wrapper.get("[data-testid='log-row']").exists()).toBe(true);
  await wrapper.get("[data-testid='refresh-button']").trigger("click");
  expect(getEvents).toHaveBeenCalled();
});
~~~

另加一个迟到响应测试：使用两个 deferred options response，先返回旧包名、后返回新包名，确认新包名的 SDK 选项仍在下拉中；保留现有分析视图和日志分页回归测试。

- [ ] **步骤 2：运行日志页目标测试确认失败**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK\frontend'
npm test -- --run src/views/LogViewer.test.ts
~~~

预期：新增测试因缺少下拉节点、联动状态和 sdk_version 参数而失败；现有测试失败也必须修复，不能删除。

- [ ] **步骤 3：实现日志筛选状态和独立选项加载**

在 LogViewer.vue 中增加：

~~~ts
const rawFilters = reactive({
  package_name: "",
  sdk_version: "",
  device_id: "",
  log_level: "",
  date_from: "",
  date_to: "",
});
const filterOptions = reactive<EventFilterOptions>({ package_names: [], sdk_versions: [] });
const filterOptionsError = ref("");
const filterOptionsLoading = ref(false);
let filterOptionsRequestSequence = 0;
~~~

实现以下请求序号和联动逻辑：

~~~ts
async function loadFilterOptions(packageName?: string): Promise<void> {
  const requestSequence = ++filterOptionsRequestSequence;
  filterOptionsLoading.value = true;
  filterOptionsError.value = "";
  try {
    const response = await getEventFilterOptions(packageName || undefined);
    if (requestSequence !== filterOptionsRequestSequence) return;
    filterOptions.package_names = response.data.package_names;
    filterOptions.sdk_versions = packageName ? response.data.sdk_versions : [];
  } catch {
    if (requestSequence === filterOptionsRequestSequence) {
      filterOptionsError.value = "包名和 SDK 版本选项加载失败，可继续查看日志并使用其他筛选条件；请刷新重试。";
    }
  } finally {
    if (requestSequence === filterOptionsRequestSequence) filterOptionsLoading.value = false;
  }
}

function changePackageFilter(packageName: string): void {
  rawFilters.package_name = packageName;
  rawFilters.sdk_version = "";
  filterOptions.sdk_versions = [];
  void loadFilterOptions(packageName || undefined);
}
~~~

原始视图首次打开时独立调用 void loadFilterOptions(); void loadLogs();；选项异常不得阻止日志请求。

- [ ] **步骤 4：实现两个单选下拉和错误提示**

将原始视图现有 package 文本框替换为：

~~~vue
<select
  v-model="rawFilters.package_name"
  data-testid="package-filter"
  :disabled="filterOptionsLoading"
  @change="changePackageFilter(rawFilters.package_name)"
>
  <option value="">全部包名</option>
  <option v-for="packageName in filterOptions.package_names" :key="packageName" :value="packageName">
    {{ packageName }}
  </option>
</select>
<select
  v-model="rawFilters.sdk_version"
  data-testid="sdk-version-filter"
  :disabled="!rawFilters.package_name || filterOptionsLoading"
>
  <option value="">全部 SDK 版本</option>
  <option v-for="sdkVersion in filterOptions.sdk_versions" :key="sdkVersion" :value="sdkVersion">
    {{ sdkVersion }}
  </option>
</select>
<p v-if="filterOptionsError" data-testid="filter-options-error" class="feedback error">
  {{ filterOptionsError }}
</p>
~~~

保留设备、级别、日期、查询和刷新控件；错误提示独立于日志列表错误反馈。

- [ ] **步骤 5：把 SDK 版本加入请求参数**

使用以下完整参数构造逻辑，空值不得发送为空字符串：

~~~ts
function rawQueryParams(targetPage: number): EventQuery {
  return {
    page: targetPage,
    page_size: rawPageSize,
    event_type: "log",
    package_name: rawFilters.package_name || undefined,
    sdk_version: rawFilters.sdk_version || undefined,
    device_id: rawFilters.device_id || undefined,
    log_level: (rawFilters.log_level || undefined) as LogLevel | undefined,
    date_from: rawFilters.date_from || undefined,
    date_to: rawFilters.date_to || undefined,
  };
}
~~~

保留已有请求序号、查询重置到第 1 页、刷新保留当前成功页和分页失败恢复逻辑。

- [ ] **步骤 6：运行日志页测试和构建**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK\frontend'
npm test -- --run src/views/LogViewer.test.ts src/api/dashboard.test.ts
npm run build
~~~

预期：日志页和 API 测试全部通过，构建成功；选项失败测试确认日志请求仍然发生。

- [ ] **步骤 7：提交日志筛选变更**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK'
git add frontend/src/views/LogViewer.vue frontend/src/views/LogViewer.test.ts
git commit -m "feat: add linked sdk version log filters"
~~~

## 任务 5：建立 100dvh 应用壳和页面内部纵向滚动

**文件：**

- 修改：frontend/src/styles/variables.css
- 修改：frontend/src/components/AppLayout.vue
- 创建：frontend/src/components/AppLayout.test.ts

- [ ] **步骤 1：编写布局结构与滚动样式失败测试**

创建布局测试，使用 RouterLink/RouterView stub，验证侧边栏和顶部标题位于 .page 外，RouterView 位于 .page 内，并在样式注入文本中断言 100dvh 与 overflow-y: auto：

~~~ts
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import AppLayout from "@/components/AppLayout.vue";

describe("AppLayout internal scroll structure", () => {
  it("keeps fixed shell nodes outside page content", () => {
    const wrapper = mount(AppLayout, {
      global: {
        stubs: {
          RouterLink: { template: "<a><slot /></a>" },
          RouterView: { template: "<div data-testid='router-view-content'>page</div>" },
        },
      },
    });

    expect(wrapper.find(".shell > .sidebar").exists()).toBe(true);
    expect(wrapper.find(".content > .topbar").exists()).toBe(true);
    expect(wrapper.find(".page > [data-testid='router-view-content']").exists()).toBe(true);
  });

  it("publishes fixed viewport and page overflow rules", () => {
    mount(AppLayout, {
      global: {
        stubs: {
          RouterLink: { template: "<a><slot /></a>" },
          RouterView: { template: "<div />" },
        },
      },
    });
    const styleText = Array.from(document.head.querySelectorAll("style"))
      .map((style) => style.textContent ?? "")
      .join("\n");

    expect(styleText).toContain("100dvh");
    expect(styleText).toContain("overflow-y: auto");
  });
});
~~~

- [ ] **步骤 2：运行布局测试确认新结构尚不存在**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK\frontend'
npm test -- --run src/components/AppLayout.test.ts
~~~

预期：样式契约测试失败，基线仍使用 100vh 和页面自然撑高，根样式没有 body overflow: hidden。

- [ ] **步骤 3：实现根高度和 AppLayout 约束**

在 variables.css 中将根样式设置为 width: 100%; height: 100%; min-height: 0，并在 body 上设置 overflow: hidden。

在 AppLayout.vue 保留原颜色、背景、padding 和断点，只增加：

~~~css
.shell {
  width: 100%;
  height: 100dvh;
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  overflow: hidden;
}

.sidebar {
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
}

.content {
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  overflow: hidden;
}

.page {
  min-width: 0;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
}

@media (max-width: 920px) {
  .shell {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr);
  }
}
~~~

删除 .shell 的 min-height: 100vh 和 .page 的 min-height: calc(100vh - 120px) 两个旧主布局约束。

- [ ] **步骤 4：运行布局测试和构建**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK\frontend'
npm test -- --run src/components/AppLayout.test.ts
npm run build
~~~

预期：布局测试通过，构建成功。

- [ ] **步骤 5：提交应用壳变更**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK'
git add frontend/src/styles/variables.css frontend/src/components/AppLayout.vue frontend/src/components/AppLayout.test.ts
git commit -m "fix: confine admin scrolling to page content"
~~~

## 任务 6：为所有页面补齐宽内容局部滚动边界

**文件：**

- 修改：frontend/src/views/Dashboard.vue
- 修改：frontend/src/views/LogViewer.vue
- 修改：frontend/src/views/ConfigManager.vue
- 修改：frontend/src/views/VersionManager.vue
- 创建：frontend/src/views/PageScrollStructure.test.ts

- [ ] **步骤 1：编写页面宽内容结构失败测试**

创建页面结构测试，使用 child stubs 和已解决 API mocks，验证大盘、日志和版本页面各有表格滚动容器，配置页保留编辑器面板：

~~~ts
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import Dashboard from "@/views/Dashboard.vue";
import ConfigManager from "@/views/ConfigManager.vue";
import LogViewer from "@/views/LogViewer.vue";
import VersionManager from "@/views/VersionManager.vue";

vi.mock("@/api/dashboard", () => ({
  getBreakdown: vi.fn().mockResolvedValue({ data: [] }),
  getEvents: vi.fn().mockResolvedValue({ data: { total: 0, items: [] } }),
  getSummary: vi.fn().mockResolvedValue({ data: {} }),
  getTrend: vi.fn().mockResolvedValue({ data: { points: [] } }),
}));

vi.mock("@/api/config", () => ({
  getConfigs: vi.fn().mockResolvedValue({ data: { published: [], drafts: [], history: [] } }),
}));

describe("page wide-content scroll boundaries", () => {
  it("keeps dashboard events inside table-scroll", async () => {
    const wrapper = mount(Dashboard, { global: { stubs: { TrendChart: true, StatCard: true } } });
    await vi.dynamicImportSettled();
    expect(wrapper.find(".table-scroll").exists()).toBe(true);
  });

  it("keeps config editor grid structure", () => {
    const wrapper = mount(ConfigManager, { global: { stubs: { ConfigFileTabs: true, ConfigTreeEditor: true } } });
    expect(wrapper.find(".content-grid").exists()).toBe(true);
    expect(wrapper.find(".editor-panel").exists()).toBe(true);
  });

  it("keeps version table inside table-scroll", async () => {
    const wrapper = mount(VersionManager);
    await vi.dynamicImportSettled();
    expect(wrapper.find(".table-scroll").exists()).toBe(true);
  });

  it("keeps analysis and raw log table containers", () => {
    const wrapper = mount(LogViewer, { global: { stubs: {
      LogAnalysisDetail: true,
      LogAnalysisFilters: true,
      LogColumnSettings: true,
      PackageProfileCell: true,
      LogDetail: true,
      LogExportPanel: true,
    } } });
    expect(wrapper.findAll(".table-scroll").length).toBeGreaterThanOrEqual(2);
  });
});
~~~

若某个页面挂载会产生 API 调用，测试必须用 vi.mock() 返回确定的已解决响应；不得让测试等待永久 Promise。

- [ ] **步骤 2：运行页面结构测试确认版本表容器缺失**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK\frontend'
npm test -- --run src/views/PageScrollStructure.test.ts
~~~

预期：基线的版本表没有 .table-scroll，测试失败。

- [ ] **步骤 3：修改四个页面的宽内容边界**

在 Dashboard.vue、LogViewer.vue、ConfigManager.vue 的页面根、面板、Grid/Flex 子项上补 min-width: 0；在固定高度收缩链路需要的位置同时补 min-height: 0；表格包装容器统一为：

~~~css
.table-scroll {
  min-width: 0;
  max-width: 100%;
  overflow-x: auto;
}
~~~

保留 LogViewer 聚合表宽度、分析明细容器、消息省略和现有表格内容。将日志弹窗高度约束改为 calc(100dvh - 40px)，保留弹窗自身滚动。

在 ConfigManager.vue 明确补充：

~~~css
.layout,
.panel,
.content-grid,
.content-grid > *,
.editor-panel,
.list-panel {
  min-width: 0;
}

.editor {
  max-width: 100%;
  min-width: 0;
  overflow: auto;
}
~~~

在 VersionManager.vue 将现有表格包裹为 <div class="table-scroll">，并为 .stack、.panel、.form-grid、.form-grid > * 补 min-width: 0；版本弹窗继续使用 position: fixed。

- [ ] **步骤 4：运行页面结构、日志/配置回归和构建**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK\frontend'
npm test -- --run src/views/PageScrollStructure.test.ts src/views/LogViewer.test.ts src/views/ConfigManager.test.ts
npm run build
~~~

预期：目标测试全部通过，构建成功；没有新增全局横向滚动规则。

- [ ] **步骤 5：提交页面滚动边界变更**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK'
git add frontend/src/views/Dashboard.vue frontend/src/views/LogViewer.vue frontend/src/views/ConfigManager.vue frontend/src/views/VersionManager.vue frontend/src/views/PageScrollStructure.test.ts
git commit -m "fix: isolate wide admin page content"
~~~

## 任务 7：同步接口文档并执行独立验收

**文件：**

- 修改：docs/42-PRODUCTION-SYSTEM-API-BASELINE-20260811.md

- [ ] **步骤 1：更新 API 基线文档**

在现有管理端事件接口章节增加：

~~~text
GET /api/admin/events/filter-options
可选 query 参数 package_name；返回 code=0、data.package_names 和 data.sdk_versions。
两个数组均按数据库值去重、升序；传入 package_name 时 sdk_versions 只包含该包名的日志版本。

GET /api/admin/events
新增可选 sdk_version，按 sdk_events.sdk_version 精确匹配；设备、级别、北京时间日期范围和分页语义保持不变。
~~~

文档中不得写入真实 Token、密码、数据库连接串或原始日志内容。

- [ ] **步骤 2：执行文档和差异自检**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK'
$forbidden = @(("TO" + "DO"), ("待" + "定"), ("后续" + "实现"), ("适当" + "的错误"), ("类似" + "任务"))
$hits = Select-String -Path 'docs/superpowers/specs/2026-09-21-internal-scroll-sdk-filter-design.md','docs/superpowers/plans/2026-09-21-internal-scroll-sdk-filter.md','docs/42-PRODUCTION-SYSTEM-API-BASELINE-20260811.md' -Pattern $forbidden
if ($hits) { $hits | Format-Table -AutoSize; exit 1 }
git diff --check
~~~

预期：PowerShell 检查无输出；git diff --check 无输出。文档必须不含未定义步骤、模糊表述或相互冲突的滚动归属。

- [ ] **步骤 3：运行后端全量测试**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK\backend'
python -m pytest -q
~~~

预期：全部测试通过，失败数为 0；不因新增测试数量变化而假设固定总数。

- [ ] **步骤 4：运行前端全量测试和构建**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK\frontend'
npm test -- --run
npm run build
~~~

预期：Vitest 全量通过，Vite 构建成功；仅记录实际存在的非失败 warning，不把 warning 当作成功条件。

- [ ] **步骤 5：执行独立 UI/API 验收**

启动已有 admin API 和前端开发服务器，使用有效管理 Token 与已有日志数据完成：

~~~text
GET /api/admin/events/filter-options                 -> 200，两个数组去重升序
GET /api/admin/events/filter-options?package_name=com.example.alpha -> 200，版本按包名联动
GET /api/admin/events?sdk_version=1.4.0              -> 200，只返回精确版本
~~~

浏览器检查桌面端/移动端断点、body 不滚动、侧边栏和顶部标题固定、页面内容区纵向滚动、宽表格和编辑器自身横向滚动、切包清空版本、选项请求失败后的可用列表、查询重置分页和刷新保留分页。记录视口尺寸、请求状态码和失败信息。

- [ ] **步骤 6：提交 API 文档更新**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK'
git add docs/42-PRODUCTION-SYSTEM-API-BASELINE-20260811.md
git commit -m "docs: document sdk version event filters"
~~~

## 任务 8：生产发布与回滚执行清单

本任务属于实施计划中的发布门禁；当前设计/计划编写窗口不得执行这些外部发布动作。

- [ ] **步骤 1：发布前确认准确提交和干净工作树**

~~~powershell
Set-Location 'C:\Users\喻远飞\.codex\worktrees\internal-scroll-sdk-filter\SDK'
git status --short
git log --oneline --decorate -8
git diff --check
~~~

预期：实现分支只包含本需求提交，工作树无未提交修改，差异检查无输出；部署前端和后端使用同一经过测试的提交。

- [ ] **步骤 2：按兼容顺序发布后端和前端**

先发布后端并确认两个新接口返回 200，再发布前端静态资源；后端先行保证旧前端的原有 /events 请求仍可用。

- [ ] **步骤 3：执行发布 smoke**

验证健康检查、Bearer 鉴权、事件选项接口、包名联动版本、精确版本筛选、设备/级别/日期组合筛选、分页和四个页面的内部滚动。任一检查失败都停止继续发布。

- [ ] **步骤 4：执行前端回滚**

若问题只出现在页面布局或筛选交互，恢复上一版前端静态资源，确认旧前端继续使用既有事件接口；记录资源版本、浏览器信息和失败接口。

- [ ] **步骤 5：执行后端回滚**

若新路由或 SQL 导致服务错误，恢复上一版后端应用并重启对应服务。本次没有数据库结构变更，不运行逆向数据库迁移；回滚后重新验证健康、鉴权、日志列表、分页和既有筛选。

- [ ] **步骤 6：完成发布报告**

报告列出部署提交、后端/前端测试实际结果、构建结果、smoke 请求结果、已知 warning 和是否执行回滚；不得声称未执行的生产检查已经通过。

## 计划自检

- [ ] **规格覆盖度：** 固定 100dvh、body 不滚动、页面内纵向滚动、子项最小尺寸、表格/编辑器局部横向滚动、响应式行为、包名下拉、SDK 版本联动、无效版本清空、选项接口、sdk_version 精确匹配、错误可用性、测试、全量测试、构建、发布和回滚，均在任务 1～8 中有对应步骤。
- [ ] **文档扫描：** 计划使用 PowerShell 检查禁止的占位和模糊措辞；每个实现步骤给出精确文件、函数/选择器、命令和预期结果。
- [ ] **类型一致性：** EventFilterOptions、EventQuery.sdk_version、getEventFilterOptions(packageName?)、get_event_filter_options(db, *, package_name)、get_events(..., sdk_version)、filterOptions、rawFilters.sdk_version 和测试中的 data-testid 在所有任务中保持同名。
- [ ] **范围限制：** 计划没有新增视觉主题、无关重构、多选、复杂搜索、模糊查询或数据库迁移。
