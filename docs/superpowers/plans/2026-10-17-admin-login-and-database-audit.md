# 后台账号登录与数据库审计实施计划

> 执行者使用 executing-plans/TDD；主会话只决策，既有执行窗口实施，既有审查窗口独立验收。

**目标：** 完成后台模块和数据库业务清单、风险审计，新增明亮风格真实账号登录并启动本地前后端测试。

**基线：** `2ea1e0cd62f04db6b794a7d93464cf47c09742ce`，从主 checkout 核实后建立 `codex/admin-login-db-audit-20261017` 独立 worktree。不能审阅旧 ae36c51/ef23 checkout。保持所有用户 dirty 文档不动。

## 批准设计与安全边界

1. 固定账户 `admin`。独立 `ADMIN_PASSWORD_HASH`，绝不复用 SDK_CONFIG_TOKEN/ADMIN_TOKEN，密码不写前端、不出日志、不进 Git。提供 getpass 交互式 hash 生成脚本。
2. 标准库 scrypt 固定 `N=32768,r=8,p=1,dklen=32,maxmem=67108864`、随机16字节salt；采用版本化严格格式，固定参数不可由客户端/存储文本任意调高。启动验证非空hash格式/参数/长度，CPU验证 `asyncio.to_thread`；未知用户也做同等密码工作，统一401。登录 JSON 用户名/密码有长度上限，密码不能静默trim。
3. 为兼容现有部署，可新增明确 `ADMIN_PASSWORD_LOGIN_ENABLED` 默认false：只有启用时要求合法hash并fail-closed，前端/me显示服务未配置错误，不退回prompt或弱默认密码。本地显式启用。已存在强ADMIN_TOKEN启动校验保持。
4. 高熵 opaque session id，服务端只保存sha256(id)及user/created/expires/CSRF，8小时绝对TTL。单实例内存store有定期/惰性清理和容量上限1000，过载失败关闭，不任意驱逐其他用户。退出服务端删除会话+清cookie；重启即失效。明确仅支持单admin进程，未来多实例需共享store，本次不加Redis/数据库表。无需无用途的签名secret。
5. 生产cookie `__Host-admin_session`、Secure、HttpOnly、SameSite=Strict、Path=/，不设Domain；本地HTTP仅 `DEBUG=true` 且显式 `ADMIN_SESSION_COOKIE_SECURE=false` 使用非__Host名称。非开发配置不得关闭Secure。
6. `/api/admin/auth/login` POST、`/auth/me` GET、`/auth/logout` POST。login不返回session/ADMIN_TOKEN；me只返回username/expires_at/csrf_token。所有auth响应Cache-Control:no-store。logout立即撤销。有效会话logout必须验证Origin+绑定CSRF；缺失/过期/无效会话的logout仍验证允许Origin，但不要求不存在的CSRF，清cookie后幂等成功，不触发登录重定向。health保持公开且仅返回既有非敏感status，不作为登录成功证据；登录成功必须由/me和受保护业务接口确认。
7. 会话cookie的所有POST/PUT/PATCH/DELETE（含logout）验证 `X-CSRF-Token` 与当前session绑定值，并验证 exact Origin 在显式 `ADMIN_AUTH_ALLOWED_ORIGINS` 列表；login也验证Origin，缺失/不匹配403。Origin不能根据未信任Host任意接受；本地Vite通过显式localhost/127.0.0.1端口白名单。GET不写数据。
8. legacy合法Bearer ADMIN_TOKEN保留用于API，优先验证：显式无效Bearer不回退cookie；无Bearer才用cookie，cookie写入必须CSRF。SDKtoken仍无admin权限。principal保持现有依赖返回str契约：legacy现有hash标识不变、session使用独立稳定admin标识，防created_by偏差。
9. 独立登录限流：按可信request.client IP+规范化用户名计失败5次/15分钟，并有IP总尝试速率和并发密码CPU工作上限，返回429+Retry-After。容量有界；不得直接复用SDK10req/s。应用不盲信X-Forwarded-For，生产反代可信链配置限制记录。
10. CORS明确origins、allow_credentials=True、不允许通配credential origins；保留现有必要methods/headers并确保CSRF头预检可用。只改admin认证，不动SDK API。
11. 前端移除prompt、ADMIN_TOKEN sessionStorage读取/写入和持久化能力；启动清旧admin_token。新增/login无AppLayout，路由守卫通过/me确认，不以本地布尔值替代后端校验；axios withCredentials，写请求携带内存csrf，普通10秒/保存发布60秒原约定不变。401清状态到/login，不造成auth/me/login死循环，安全内部returnTo不接受外域；网络错误不当作错误密码。
12. 登录页沿用蓝白tokens：简洁居中表单、SDK运营中台、账号/密码、显示隐藏密码、登录加载禁用、错误提示和键盘焦点；无虚假账号数据或默认真实密码。顶部提供当前admin/退出。手机390宽不裁切。

## 任务 1：模块与DB审计（只读代码）

- [ ] 完成 `docs/62-BACKEND-MODULE-DATABASE-AUDIT-20261017.md`（编号占用顺延）。列全部SDK/admin端点、后台worker/ETL/分区维护的业务、表、读写/锁/事务、索引、数据规模/筛选和风险；每条定位文件行。
- [ ] 明确已证实overview历史超时与静态风险、未实测项；不运行生产长查询，不宣称所有查询不卡顿。
- [ ] 最新usage七桶是已实现功能，审计row_number latest-per-device/countgroup/offset以及model在latest后过滤语义；metrics多scalar重复扫描和索引匹配是风险项，不顺手改SQL/统计。
- [ ] 包含连接池每进程20+10、ETL5分钟刷新、无日期count/distinct/全量配置历史/导出/解析暂存与发布锁、主键分区和留存清理；列安全EXPLAIN和独立副本压测方案。

## 任务 2：后端认证（TDD）

文件：`backend/app/core/config.py`、新`backend/app/services/admin_auth_service.py`、新`backend/app/api/admin/auth.py`、现有`backend/app/api/admin/deps.py`、`backend/app/admin_main.py`、`backend/.env.example`、新`backend/scripts/generate_admin_password_hash.py`、新`backend/tests/test_admin_auth.py`及配置测试。

- [ ] 先测试错误账号/密码统一响应、严格hash参数、空/弱hash启用时启动拒绝、禁用时503、不阻断legacyAPI；再写最小实现。
- [ ] 测试cookie属性/本地门控、会话TTL/篡改/登出撤销、CSRF错误/缺失/Origin伪造、合法Bearer兼容与无效Bearer不回退、SDKtoken拒绝、速率429/RetryAfter、容量/清理、密码不出响应日志。
- [ ] 覆盖既有admin router依赖，不能只保护/login页面；测试所有cookie写方法通过公共依赖执行CSRF。
- [ ] `python -m pytest tests/test_admin_auth.py tests/test_settings.py tests/test_admin_api.py -q`先红后绿，再全后端测试；PG集成测试若需独立测试库不连接生产，skip要明确。

## 任务 3：前端登录（TDD）

文件：新`frontend/src/views/Login.vue`/测试、新`frontend/src/api/auth.ts`、新`frontend/src/stores/adminAuth.ts`（可用Vue reactive不加Pinia）、`frontend/src/api/request.ts`、`frontend/src/router/index.ts`、`frontend/src/App.vue`、`frontend/src/components/AppLayout.vue`/测试和新增router/request测试。

- [ ] 测试未认证内部路由回/login、成功返回原内部路径、错误密码提示、网络失败区分、401一次跳转、logout、本地存储无secret、CSRF写请求、保存发布timeout不改。先红后绿。
- [ ] 不循环依赖router/request/authstore，可通过注入回调或独立事件协调；业务API不改参数/响应契约，不降低既有测试覆盖。
- [ ] 全量 `npm run test -- --run`、`npm run build`、`git diff --check`；只提交相关文件。

## 任务 4：本地真前后端与验收

- [ ] 检查已有本地端口/PG，使用专用本地库和独立测试凭据，不覆盖用户真实.env、不能用生产数据库/密码/token。只启动loopback进程、隐藏窗口；使用应用现有真实app含auth与路由，不以mock auth替代联调。
- [ ] 前端proxy与localbackend端口一致；本地session安全cookie显式开发配置；登录限流测试不能误锁用户正式账户。
- [ ] 为用户生成只用于本地的强测试密码，保存到用户可读取的本地私有文件且不入Git，最终仅提供该文件位置，不在共享消息或文档回显密码。密码生成/哈希不能输出其他secret。
- [ ] 使用bundled Playwright（不要向项目npm install QA包）跑桌面1536/手机390：错误密码、成功登录、四页面导航、刷新保会话、退出后API401、无会话深链保护。真实接口联调，操作本地测试DB，不生产写入。
- [ ] 对比Cookie HttpOnly/Secure策略、CSRF实际拒绝/放行、登录/过期错误提示、控件focus、无console异常和overflow；view_image最终登录页截图。
- [ ] 独立审查窗口锁定准确SHA从干净验证目录复跑front/back tests/build，审计docs62覆盖；记录`docs/63-ADMIN-LOGIN-LOCAL-ACCEPTANCE-20261017.md`（占用顺延）包含证据/限制/本地启动停止方法/预览URL。会话重启失效和单实例限制明确，不声称生产已验。
- [ ] 保持本地服务运行供用户测试；提交分支，不合并master、不推送、不部署，等用户另行授权。
