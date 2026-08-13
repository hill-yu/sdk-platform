# 日志查看与配置树编辑器实施记录

> 日期：2026-08-13
>
> 功能分支：`codex/log-viewer-config-tree`
>
> 状态：代码与本地验证阶段，未部署生产

## 1. 实施范围

本次实现两个管理后台增强功能：

1. 新增独立“日志查看”页面，用于检索、分页、查看和复制 SDK 日志；
2. 将配置详情的路径表格编辑方式替换为三份固定配置文件的递归树编辑器，同时保留完整 JSON 编辑模式。

未修改 SDK 日志上报协议、事件表结构、配置发布协议、配置版本分配规则和 SDK 下发协议。

## 2. 独立日志查看页

- 路由：`/logs`，侧边栏提供独立入口；
- 固定查询 `event_type=log`；
- 支持 `package_name`、`log_level`、`device_id`、开始日期和结束日期筛选；
- 支持刷新、上一页、下一页和空结果提示，默认每页 20 条；
- 列表展示接收时间、级别、包名、设备 ID、SDK 版本、tag 和 message 摘要；
- 详情展示完整 `payload.extra` 原始字符串，并提供完整复制；
- 查询失败保留上一批有效结果，复制失败给出明确反馈。

Admin 查询接口新增可选参数：

```http
GET /api/admin/events?event_type=log&package_name=com.example.app&log_level=error&page=1&page_size=20
Authorization: Bearer <ADMIN_TOKEN>
```

`log_level` 仅允许 `debug`、`info`、`warn`、`error`，非法值返回 HTTP 422；过滤依据为日志事件 `payload.level`。事件响应补充返回 `sdk_version`。

## 3. 三份配置文件与递归树编辑

配置详情继续维护唯一、完整的 `config_data`，根字段固定为：

- `mainConfig`；
- `newTouchConfig`；
- `newTextRuleConfig`。

树模式一次编辑一个根配置文件，切换标签不会自动保存，也不会丢失内存中的其他标签修改。树节点覆盖 object、array、string、number、boolean 和 null 六种 JSON 类型。

已实现的树操作包括：

- 对象字段新增、改名和删除；
- 数组元素新增、深复制、删除、上移和下移；
- 容器展开与折叠；
- 节点类型切换；
- 空键、重复键、非法数字和稀疏数组校验；
- 删除非空容器或将非空容器改为标量前二次确认；
- published/archived 配置严格只读。

对象键直接作为 JSON 键处理，支持点号、方括号、空格和中文等合法特殊键名，不再使用点号路径做业务状态。数组操作保持索引连续，复制使用深拷贝。

## 4. 树模式与 JSON 模式

JSON 模式编辑完整三根 `config_data`。两种模式切换前均校验当前内容：

- JSON 语法错误或缺少固定根字段时，保留 JSON 输入并阻止切换、保存或发布；
- 树节点存在空键、重复键或非法数字草稿时，保留输入并阻止切换标签、切换模式、保存或发布；
- 合法数据在树形 → JSON → 树形往返后保持 JSON 数据语义一致。

配置详情请求增加顺序保护：快速切换配置时，仅最后一次请求允许更新页面状态，避免较慢的旧响应覆盖新选择。

## 5. 保存、加密与发布边界

保存仍沿用原有链路：前端提交完整三根 `config_data`，后端校验后使用 AES-256-GCM 加密并写入 PostgreSQL。保存接口仍使用 60 秒超时、保存期间禁用按钮，以及超时后重新查询确认结果的机制。

本次没有修改：

- `SDK_CONFIG_TOKEN`、HKDF-SHA256 派生参数和 AES-GCM 信封格式；
- `POST /api/v1/config/meta`；
- 三份加密配置下载接口；
- 发布时分配版本、按包名递增和历史回滚复用版本的规则；
- 日志上报请求体及数据库结构。

## 6. 测试与部署前检查

执行命令：

```bash
python -m pytest backend/tests -q
npm --prefix frontend test -- --run
npm --prefix frontend run build
rg -n "ConfigTableEditor|flattenConfig|rowsToConfig" frontend/src
rg -n "log_level" backend frontend docs/40-LATEST-API-INTEGRATION-GUIDE-20260810.md
git diff --check
```

2026-08-13 已在隔离工作树执行以下本地真实冒烟验证，未记录或输出任何 Token、密码或密钥：

- 启动 SDK API `127.0.0.1:8100`、Admin API `127.0.0.1:8101` 和前端 `127.0.0.1:5173`；
- `GET http://127.0.0.1:8101/api/admin/health` 返回 HTTP 200；
- `GET http://127.0.0.1:5173/logs` 返回 HTTP 200；
- 使用本地 Admin 鉴权查询 `GET /api/admin/events?event_type=log&log_level=info&page=1&page_size=20`，响应 `code=0`、`total=11`、`items=11`；首条结果包含 `sdk_version`，`payload.extra` 长度为 25，读取结果与数据库响应中的原始字符串一致；
- 使用专用本地测试包 `codex.task6.smoke.20260813b` 创建草稿 ID `7`，保存包含特殊键与嵌套数组的完整三根配置；重新读取后 `exact_roundtrip=true`，状态保持 `draft`；
- 整个冒烟过程没有调用 publish 接口。草稿 ID `7` 验证后已从本地数据库删除；此前用于排查 Windows PowerShell 中文请求编码的探测草稿 ID `6` 也已删除；
- 冒烟完成后 SDK API、Admin API、前端开发服务及临时启动的 PostgreSQL 均已关闭，隔离工作树中的临时 `.env` 已删除。

部署前还需确认生产环境 Admin Token、数据库迁移基线、反向代理路由和前端静态资源版本。部署后应使用专用测试包验证日志筛选和配置草稿保存；不得将冒烟测试草稿发布为正式版本。

## 7. 回滚边界

若上线后前端页面异常，可回滚本次前端静态资源与后端应用版本；本次没有新增数据库迁移，回滚不需要重写事件或配置数据。已经由旧协议发布的配置及其加密内容不应被批量重写。

本文只记录实现和本地验证结果，不代表生产部署已经完成。
