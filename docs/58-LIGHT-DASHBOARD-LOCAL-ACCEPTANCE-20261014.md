# Light Dashboard 本地验收记录

日期：2026-10-14  
分支：`codex/light-dashboard-20261014`  
基线：`d15e49e075d6cd7c80d997834be94d395d7c3171`

## 范围

- 仅实现 Dashboard 首页浅色主题；日志、配置、版本页面保持原有深色主题。
- 保留既有 dashboard API、筛选、分页、行展开与错误/空状态行为。
- 未修改 `backend/`，未接入生产 token、生产 API 或部署流程。

## 验证结果

- `npm run test -- --run`：通过，33 个测试文件、202 个测试。
- `npm run build`：通过，709 个模块转换；仅保留既有的大 chunk warning。
- `git diff --check`：通过。
- `git diff d15e49e075d6cd7c80d997834be94d395d7c3171 -- backend`：无输出，后端零改动。

## 视觉验收

使用本地 mock API 与 Chrome headless 截图完成，未访问生产服务：

- 预览地址：[http://127.0.0.1:4310/](http://127.0.0.1:4310/)
- [桌面 1536×1024](C:/Users/喻远飞/.codex/visualizations/2026/10/14/light-dashboard-20261014/desktop-1536x1024-final.png)
- [移动 390×844](C:/Users/喻远飞/.codex/visualizations/2026/10/14/light-dashboard-20261014/mobile-390x844-final.png)

检查项：

- 白色侧栏、浅灰画布、蓝色当前导航与面包屑/时区信息可见。
- 四项指标卡、趋势图双轴标签、蓝/青分布图与明细表可见。
- 桌面下方明细区在 1536×1024 视口内可同时看到 8 条记录和分页。
- 明细筛选在桌面窄面板中自动换行；移动端统计卡片为两列。
- 浅色图表遵循 `prefers-reduced-motion`，减弱动态时传入 `animation: false`。
- 浅色饼图使用固定蓝/青色板；默认深色图表的柱线组合与动画配置保持不变。

限制与未决项：移动 390×844 截图仍显示右侧统计卡、趋势第二控件和 UV 轴被裁切，本轮不宣称移动端通过验收；Chrome headless DOM rect/overflow 测量在当前环境超时，未伪造测量数据。截图使用本地 mock 数据，仅用于静态与交互布局验收，不代表后端数据质量或生产接口连通性。mock 预览保持 loopback 服务运行，临时 mock 文件不入 Git。
