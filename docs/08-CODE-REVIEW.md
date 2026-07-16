# 🔍 SDK Platform 代码审查报告

> 审查时间：2026-06-30 | 审查工具：Claude Code | 审查范围：20 个 Python 文件

---

## 汇总

| 严重程度 | 数量 | 类别 |
|---------|------|------|
| 🔴 Critical | 3 | SQL注入风险(2) + CORS(1) |
| 🟠 High | 6 | 鉴权(2) + 速率限制(1) + 异常处理(1) + 数据一致性(1) + DoS(1) |
| 🟡 Medium | 9 | 输入校验(5) + 安全配置(2) + 性能(1) + 健壮性(1) |
| 🟢 Low | 10 | 代码规范(3) + 健壮性(3) + 架构(2) + 安全(2) |

---

## 🔴 Critical

### C1. `analysis_service.py:87-94` — SQL f-string 注入反模式
`dimension_expr` 通过 if-elif 硬编码暂安全，但 f-string 拼接 SQL 模式极易被后续维护者破坏。

### C2. `analysis_service.py:137-147` — WHERE 子句 f-string 拼接
`where_sql = " AND ".join(where_clauses)` + f-string 注入 SQL。当前每条子句用 `:param` 绑定暂安全，但反模式高危。

### C3. `admin_main.py:39-44` — CORS `allow_origins=["*"]`
任何网站可从前端请求 Admin API 并携带 Authorization header，存在 CSRF-like 攻击风险。

---

## 🟠 High

### H1. SDK 写接口（click/log）无任何鉴权
任何人均可伪造 app_id/device_id 写入数据，造成数据污染和存储膨胀。

### H2. 点击/日志上报接口无速率限制
缺少 rate limiting，可能被 DoS 攻击打满数据库连接池。

### H3. 过于宽泛的异常捕获吞没关键错误
`except Exception: rejected += 1` 无法区分"校验失败"和"数据库断开"。

### H4. admin_main.py ETL 初始刷新延迟 5 分钟
启动后先 sleep(300) 再刷新，前 5 分钟数据为空。

### H5. COS 上传与数据库写入不在同一事务
COS 成功但 DB 失败时，CDN 与数据库状态不一致。

### H6. config_data 无大小限制
可通过超大 JSON 发起 DoS 攻击。

---

## 🟡 Medium（代表性）

- **M1**: ADMIN_TOKEN 默认弱密码硬编码
- **M2**: Token 比较使用非常量时间字符串比较（时序攻击风险）
- **M3**: app_id/device_id 缺少长度和格式校验
- **M6**: sdk_main.py 缺少请求体大小限制
- **M8**: get_events 日期范围无上限

---

## 修复优先级建议

1. **立即修复**：C1 + C2（SQL注入反模式改 SQLAlchemy ORM）
2. **本周修复**：C3（CORS限制） + H1/H2（SDK鉴权+限流）
3. **下个迭代**：H3~H6 + M1~M9
4. **持续改进**：L1~L10

---

> 🍔 完整报告已保存，含每个问题的修复代码示例。
