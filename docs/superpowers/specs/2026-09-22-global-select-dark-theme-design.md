# 全局暗色主题原生下拉框设计

## 1. 背景与目标

暗色主题下，浏览器原生 `select` 展开后的 `option` 和 `optgroup` 可能继续使用浅色系统背景，导致白底浅色文字或分组文字难以阅读。本次变更采用方案 A：在全局样式中为原生下拉框及其选项明确指定暗色背景和浅色文字，并保留现有 `color-scheme: dark`，统一修复所有使用原生 `select` 的页面。

## 2. 范围

### 2.1 包含内容

- 在 `frontend/src/styles/variables.css` 全局设置 `select`、`option`、`optgroup` 的主题背景和文字颜色，颜色只使用现有主题变量：
  - `select` 使用 `var(--panel-bg)` 背景和 `var(--text-primary)` 文字。
  - `option` 与 `optgroup` 使用 `var(--bg-secondary)` 背景和 `var(--text-primary)` 文字。
  - `select:disabled` 使用 `var(--bg-secondary)` 背景和 `var(--text-muted)` 文字，保持禁用状态可读。
- 保留 `:root { color-scheme: dark; }`，不引入第二套主题变量或系统颜色值。
- 新增全局样式回归测试，明确检查 `select`、`option`、`optgroup` 的背景与文字颜色声明，以及禁用下拉框的可读性规则。
- 兼容日志查看、Dashboard、版本管理、ConfigTreeEditor 等现有原生 `select`，不替换为自定义下拉组件。

### 2.2 非目标

- 不逐一增加页面级覆盖规则。
- 不改变控件尺寸、间距、布局、数据、交互、选项顺序、筛选语义或组件架构。
- 不重构主题、不调整其他按钮、输入框、表格、面板或图表的视觉元素。
- 不引入自定义选择器、弹出层、搜索下拉框或第三方 UI 组件。

## 3. 受影响文件

| 文件 | 变更职责 |
| --- | --- |
| `frontend/src/styles/variables.css` | 保留全局暗色配色基础，并为原生 `select`、`option`、`optgroup` 与禁用 `select` 增加统一颜色规则；不改变尺寸和布局。 |
| `frontend/src/styles/variables.test.ts` | 新增样式回归测试，读取全局 CSS 并验证主题变量、元素选择器和 `color-scheme: dark` 声明。 |
| `docs/superpowers/specs/2026-09-22-global-select-dark-theme-design.md` | 记录设计边界、实现契约、测试、验收、风险与回滚方案。 |

实现前确认上述测试文件不存在；如果代码库已有同职责的全局样式测试入口，直接在该入口补充断言，不重复创建测试载体。

## 4. 样式契约

全局样式保留现有 `:root` 规则和 `color-scheme: dark`。在基础控件规则附近增加以下等价 CSS 规则，选择器和颜色语义必须保持明确：

```css
select {
  background-color: var(--panel-bg);
  color: var(--text-primary);
}

option,
optgroup {
  background-color: var(--bg-secondary);
  color: var(--text-primary);
}

select:disabled {
  background-color: var(--bg-secondary);
  color: var(--text-muted);
}
```

规则要求如下：

- `select`、`option`、`optgroup` 必须分别有明确的背景和文字颜色结果；不能只依赖继承、浏览器默认值或 `color-scheme`。
- `optgroup` 的文字颜色与普通选项保持足够对比度；分组标签不得回到浅色系统默认背景。
- `select:disabled` 只改变颜色，不改变 `opacity`、尺寸、光标、边框、布局或交互行为。
- 不新增 `width`、`height`、`padding`、`font-size`、`appearance`、`position`、`display` 或其他会改变控件几何形态的声明。
- 现有通用 `button, select, input, textarea { font: inherit; }` 继续保留。

## 5. 测试设计与验收标准

### 5.1 样式回归测试

新增 `frontend/src/styles/variables.test.ts`，使用 Node 文件读取能力读取同目录下的 `variables.css`，以稳定、与浏览器原生 popup 渲染无关的方式验证 CSS 契约：

- 断言文件包含 `color-scheme: dark`。
- 断言 `select` 规则包含 `background-color: var(--panel-bg)` 和 `color: var(--text-primary)`。
- 断言 `option, optgroup` 规则包含 `background-color: var(--bg-secondary)` 和 `color: var(--text-primary)`。
- 断言 `select:disabled` 规则包含 `background-color: var(--bg-secondary)` 和 `color: var(--text-muted)`。
- 断言颜色规则没有依赖白色背景、白色文字或系统默认颜色；测试失败时应能直接指出缺少的选择器或声明。

测试只验证全局样式契约，不尝试断言 `happy-dom` 或 Chromium 对原生下拉 popup 的实际绘制结果。若环境可用，使用 Chromium 手动检查至少一个包含普通选项和分组 `optgroup` 的现有页面，确认展开后背景、选项文字、分组文字和禁用状态均可读；该检查是补充验收，不能替代自动化测试。

### 5.2 必须执行的命令

在 `frontend` 目录执行前端全量测试和构建：

```powershell
npm test -- --run
npm run build
```

在仓库根目录执行差异空白检查：

```powershell
git diff --check
```

验收条件：三个命令均退出码为 `0`；全量测试无失败；构建完成；`git diff --check` 无输出。测试总数以实际运行结果为准，不在规格中固定数量。

## 6. 兼容性与风险

- 原生 `option` 和 `optgroup` 的可样式化能力受浏览器和操作系统限制，展开 popup 可能由系统控件绘制；显式背景色、文字色与 `color-scheme: dark` 是不改变组件架构情况下的最低风险方案。
- 全局规则会覆盖现有原生 `select` 的默认颜色，但不改变控件的尺寸、布局、数据或交互。日志查看、Dashboard、版本管理、ConfigTreeEditor 等现有使用方继续使用原生下拉框。
- 某些浏览器可能忽略部分 `option` 样式；这属于原生控件限制，不通过引入自定义下拉组件规避。Chromium 可行时进行人工可读性检查，并记录无法由自动截图可靠覆盖的系统 popup 限制。

## 7. 发布与回滚

- 本次实现只涉及全局 CSS、样式回归测试和本设计文档，不需要数据库迁移、接口变更或部署顺序调整。
- 本规格文档使用单独提交 `docs: design global dark select styling`；实际实现样式和测试时，必须在实现提交前完成本规格列出的前端测试、构建和 `git diff --check`。
- 如果浏览器兼容性检查发现颜色规则影响现有页面，只需回滚该单提交即可恢复原有全局样式；不需要数据回滚或配置迁移。
