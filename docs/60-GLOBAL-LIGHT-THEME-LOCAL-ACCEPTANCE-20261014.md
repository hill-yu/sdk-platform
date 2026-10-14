# Global Light Theme Local Acceptance

日期：2026-10-14  
源码 SHA：`937da4ee8e5d24ff70cb47195372caec3f793848`  
分支：`codex/global-light-theme-20261014`

## 验证命令

在独立干净验证目录执行：

```text
C:\Users\喻远飞\.codex\visualizations\2026\10\14\global-light-theme-20261014-verify
cd frontend
npm ci
npm run test -- --run
npm run build
```

结果：34 个测试文件、206 个测试通过；`vue-tsc --noEmit && vite build` 通过。Vite 仅报告既有的 chunk size warning；未修改 package 或 lock 文件。

## 本地预览

当前预览：<http://127.0.0.1:4174/>  
API 为本地 mock：`http://127.0.0.1:8101`，仅返回演示数据，不连接生产服务。

## 浏览器证据

Playwright 使用 bundled runtime，执行脚本：

```text
C:\Users\喻远飞\.codex\visualizations\2026\10\14\global-light-theme-20261014-playwright.cjs
```

截图和 DOM 数据目录：`C:\Users\喻远飞\.codex\visualizations\2026\10\14\global-light-theme-20261014\`

已覆盖 390×844、1366×768、1536×1024；路由为 `/`、`/logs`、`/config`、`/version`；日志覆盖解析统计、原始日志、使用时长三个 Tab，并生成原始日志详情与版本新增弹层截图。

使用时长 Tab 使用七个时长桶的成功态 mock 数据，截图 `logs-usage-view-tab-1536.png` 可见汇总行，不以 loading 态作为验收依据。

三种视口均满足四条路由的 `body.scrollWidth === body.clientWidth`。390px 实测：`390/390`；1366px：`1366/1366`；1536px：`1536/1536`。横向滚动仅保留在移动导航、配置文件 Tab、树编辑器和表格等明确的内部容器。

Tab/键盘焦点实测 button、input、select 均为 `2px solid rgb(37, 99, 235)`、offset `2px`；全局 CSS 同时覆盖 button、input、select、textarea、link、tab、role button、summary。

## 设计核对

- 全站 shell、Dashboard、日志、配置、版本页面统一为蓝白浅色表面。
- 状态颜色改用 success/warning/error 语义 token。
- Dashboard 趋势默认为双折线；`trendOption` 保留 `light` 输入类型，但全站强制浅色输出，`light:false` 不再产生暗色 UI。
- 配置版本列表、配置文件 Tab、树编辑器和版本表在窄屏下保留真实内部滚动边界。
- 后端、API 路径和业务交互未改动。

限制：本记录只覆盖本地 mock 数据和本地浏览器渲染，不代表生产部署验收。
