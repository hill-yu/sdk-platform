# 技术债记录

## D1: config_service 事务边界分散
- 位置: config_service.py
- 问题: Service 自行 commit + 依赖外层 get_db commit，两层事务边界
- 建议: 后续独立发布用例统一编排事务阶段
- 优先级: Low
- 创建日期: 2026-07-16

## D2: 对账定时任务
- 位置: config_mgr.py /reconcile 接口
- 问题: 当前对账为手动触发，无自动巡检机制
- 建议: 后续迭代增加定时对账任务（如每5分钟），发现不一致时自动告警（日志/通知）
- 优先级: Medium
- 创建日期: 2026-07-16

## D3: Outbox 模式 — COS 上传与 DB 事务解耦
- 位置: config_service.py publish_config / rollback_config
- 问题: 当前"先COS后DB"方案在 DB commit 失败时需独立 session 恢复，仍有窗口期风险
- 建议: 后续迭代引入 Outbox 模式：写 DB 时同时写入 outbox 事件表，独立 worker 读取 outbox 执行 COS 上传，保证最终一致性
- 优先级: Medium
- 创建日期: 2026-07-16
