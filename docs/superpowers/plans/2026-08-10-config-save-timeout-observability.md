# 配置保存超时与可观测性实现计划

**目标：** 保存和发布使用 60 秒超时、操作期间禁用按钮并显示状态，超时后回查确认结果，同时记录保存各阶段耗时；其他接口保持 10 秒。

**架构：** Axios 实例继续使用 10 秒默认值，配置写操作在调用点覆盖为 60 秒。前端通过保存前后的 `updated_at` 或发布前后的 `status/version` 判断超时请求是否最终提交。请求体中间件记录上传耗时，保存服务记录校验、加密和 flush 耗时，路由显式提交并汇总日志。

**技术栈：** Vue 3、Axios、Vitest、FastAPI、SQLAlchemy、pytest。

---

### 任务 1：写操作超时与超时确认

- 修改 `frontend/src/api/config.ts`，只为更新和发布传入 `timeout: 60000`。
- 修改 `frontend/src/api/request.ts`，保留 Axios 错误的 `code` 供超时识别。
- 创建 `frontend/src/utils/configOperation.ts` 及测试，封装超时识别和保存/发布结果确认。
- 修改 `frontend/src/views/ConfigManager.vue`，增加保存/发布忙碌状态、按钮禁用和回查提示。
- 先运行定点测试确认失败，再实现并运行全部前端测试与构建。

### 任务 2：保存接口分阶段耗时日志

- 修改 `backend/app/core/middleware.py`，将请求体读取毫秒数写入 ASGI state。
- 修改 `backend/app/services/config_service.py`，采集校验、加密和 flush 毫秒数。
- 修改 `backend/app/api/admin/config_mgr.py`，保存接口显式 commit，记录上传、校验、加密、flush、commit 和总耗时。
- 增加 pytest 用例验证指标和 commit 行为，先红后绿，再运行全部后端测试。

### 任务 3：交付

- 运行前后端完整测试、类型检查、生产构建与 diff 检查。
- 提交并推送当前分支，部署前后端，线上验证保存、发布、普通查询及耗时日志。
