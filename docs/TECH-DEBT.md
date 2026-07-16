# 技术债记录

## D1: config_service 事务边界分散
- 位置: config_service.py
- 问题: Service 自行 commit + 依赖外层 get_db commit，两层事务边界
- 建议: 后续独立发布用例统一编排事务阶段
- 优先级: Low
- 创建日期: 2026-07-16
