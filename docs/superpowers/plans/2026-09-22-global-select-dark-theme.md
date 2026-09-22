# 全局暗色主题原生下拉框实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 为所有原生 `select`、`option` 和 `optgroup` 建立可回归验证的暗色主题颜色契约，同时保持现有 `color-scheme: dark`、尺寸、布局和原生控件行为不变。

**架构：** 在 `frontend/src/styles/variables.css` 的全局基础控件样式附近增加三组 CSS 规则：普通下拉框使用面板背景，选项与分组选项使用现有不透明深色背景，禁用下拉框使用次级背景和静音文字。用同目录 Vitest 测试读取 CSS 文本并断言选择器和声明，避免依赖操作系统绘制的原生 popup。

**技术栈：** Vue 3 前端、Vite、Vitest 3、TypeScript、Node `fs`/`url` 文件读取、CSS 自定义属性。

---

## 文件职责

- 修改：`frontend/src/styles/variables.css`——保留现有 `:root` 与 `color-scheme: dark`，为原生 `select`、`option`、`optgroup` 和 `select:disabled` 增加全局颜色规则；不添加几何、布局或自定义控件声明。
- 创建：`frontend/src/styles/variables.test.ts`——读取同目录 `variables.css`，以 CSS 文本契约测试覆盖普通、分组选项、禁用状态和暗色主题声明。
- 创建：`docs/superpowers/plans/2026-09-22-global-select-dark-theme.md`——记录本实现计划；实现阶段不修改规格文档或其他页面文件。

## 任务 1：添加全局样式回归测试并确认其先失败

**文件：**

- 创建：`frontend/src/styles/variables.test.ts`

- [ ] **步骤 1：编写失败的测试**

创建测试文件，使用 `import.meta.url` 定位同目录 CSS，并为每个契约提供可诊断的断言：

```ts
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const css = readFileSync(
  fileURLToPath(new URL('./variables.css', import.meta.url)),
  'utf8',
);

describe('global dark select styles', () => {
  it('keeps the dark color scheme', () => {
    expect(css).toContain('color-scheme: dark;');
  });

  it('sets an explicit dark theme for select controls', () => {
    expect(css).toMatch(
      /select\s*\{[^}]*background-color:\s*var\(--panel-bg\);[^}]*color:\s*var\(--text-primary\);/s,
    );
  });

  it('sets an explicit dark theme for options and option groups', () => {
    expect(css).toMatch(
      /option\s*,\s*optgroup\s*\{[^}]*background-color:\s*var\(--bg-secondary\);[^}]*color:\s*var\(--text-primary\);/s,
    );
  });

  it('keeps disabled selects readable', () => {
    expect(css).toMatch(
      /select:disabled\s*\{[^}]*background-color:\s*var\(--bg-secondary\);[^}]*color:\s*var\(--text-muted\);/s,
    );
  });

  it('does not use light or system colors for the select theme', () => {
    expect(css).not.toMatch(
      /(?:background-color|color):\s*(?:white|#fff(?:fff)?|Canvas|CanvasText)\s*;/i,
    );
  });
});
```

- [ ] **步骤 2：运行测试验证预期失败**

在 `frontend` 目录运行：

```powershell
npm test -- --run src/styles/variables.test.ts
```

预期：Vitest 能加载测试文件，但至少 `select`、`option, optgroup` 和 `select:disabled` 的断言失败，因为基线 CSS 只有 `color-scheme: dark`，尚未包含这些显式规则；不要修改测试来迎合失败输出。

## 任务 2：添加最小全局 CSS 实现并验证针对性测试

**文件：**

- 修改：`frontend/src/styles/variables.css`，在现有 `button, select, input, textarea { font: inherit; }` 之后、`button` 规则之前添加颜色规则。

- [ ] **步骤 1：写入最小 CSS**

增加以下精确规则，仅使用规格指定的现有主题变量；`var(--bg-secondary)` 是明确不透明的深色值（当前值为 `#16213e`），可避免原生 `option` popup 对半透明 `--panel-bg` 继承处理不一致：

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

不要增加 `opacity`、`width`、`height`、`padding`、`font-size`、`appearance`、`position`、`display`、边框、光标或其他会改变几何形态、布局、交互的声明；保留现有通用 `font: inherit` 规则和现有 `button` 规则。

- [ ] **步骤 2：运行针对性测试验证通过**

在 `frontend` 目录运行：

```powershell
npm test -- --run src/styles/variables.test.ts
```

预期：Vitest 报告 1 个测试文件中的 5 个测试全部通过；测试验证的是 CSS 契约，不断言 happy-dom 或 Chromium 的原生 popup 绘制结果。

- [ ] **步骤 3：检查样式差异边界**

在仓库根目录运行：

```powershell
git diff -- frontend/src/styles/variables.css frontend/src/styles/variables.test.ts
```

预期：差异仅包含上述测试文件和三组颜色规则；不存在页面级选择器、自定义下拉组件、布局/交互声明或其他主题控件改动。

## 任务 3：执行完整验证与补充人工兼容性检查

**文件：**

- 无新增修改文件；只验证任务 1–2 的变更。

- [ ] **步骤 1：运行前端全量测试**

在 `frontend` 目录运行：

```powershell
npm test -- --run
```

预期：所有 Vitest 测试通过，进程退出码为 `0`。

- [ ] **步骤 2：运行前端构建**

在 `frontend` 目录运行：

```powershell
npm run build
```

预期：`vue-tsc --noEmit` 和 Vite build 均成功，进程退出码为 `0`。

- [ ] **步骤 3：检查差异空白**

在仓库根目录运行：

```powershell
git diff --check
```

预期：命令无输出并以退出码 `0` 完成。

- [ ] **步骤 4：进行补充浏览器检查**

在可用的 Chromium 页面中打开一个现有原生 `select`，至少确认普通 `option`、`optgroup` 标签和禁用 `select` 的展开/显示状态保持可读。记录浏览器或操作系统原生 popup 忽略部分 CSS 的限制；该手动检查不能替代自动化测试，也不能因此引入自定义组件或页面级覆盖。

## 任务 4：规格覆盖、占位符和一致性自检

- [ ] **步骤 1：逐条核对规格覆盖**

确认任务 1 覆盖 `color-scheme: dark`、三类元素背景/文字颜色、禁用可读性和禁止白色/系统颜色；任务 2 覆盖仅使用现有变量、保留通用字体规则、不改变几何和交互；任务 3 覆盖全量测试、构建、`git diff --check` 和补充 Chromium 检查；全计划保持原生控件及日志查看、Dashboard、版本管理、ConfigTreeEditor 的兼容范围。

- [ ] **步骤 2：扫描计划中的禁止占位符和命名一致性**

确认计划不包含任何未决占位符，并确认测试中使用的文件名 `variables.test.ts`、CSS 选择器 `select:disabled`、变量名 `--panel-bg`、`--bg-secondary`、`--text-primary`、`--text-muted` 与实现步骤完全一致。

## 任务 5：单独提交实现

- [ ] **步骤 1：提交实现变更**

确认任务 3 的三个命令均以退出码 `0` 完成、任务 4 自检无遗漏后，在仓库根目录运行：

```powershell
git add frontend/src/styles/variables.css frontend/src/styles/variables.test.ts
git commit -m "feat: add global dark select styling"
```

预期：创建一个只包含全局 CSS 和样式回归测试的实现提交；不要把规格文档或本计划文档混入实现提交。


