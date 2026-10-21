# 2026-10-21 生产部署记录：2400791

## 发布结果

- 源码 release：`2400791137fbb59c2f37f7cd217daa3bf6ae55de`
- GitHub `master` 已安全快进并推送到同一 SHA。
- 生产 `current` 已切换到该 release；未重建源码包，未重复部署。
- 四个 systemd 服务均为 `active`：SDK API、Admin、log export worker、log parse worker。
- SDK/Admin HTTPS health 均返回 `200`。

固定构建包：

- `C:\Users\喻远飞\.codex\release-prep\sdk-platform-2400791\source.zip`
- `C:\Users\喻远飞\.codex\release-prep\sdk-platform-2400791\frontend-dist.zip`
- `C:\Users\喻远飞\.codex\release-prep\sdk-platform-2400791\manifest.txt`

## 数据库与文件备份

备份根目录：`/www/backups/sdk-platform/20261021-1042`

- `database.dump`：370,775,809 bytes；`pg_restore --list` 成功，217 条目。
- `database.dump` SHA-256：`7bf3c1a70a91c27fc8c76954a45803a22ed9a11502605c1e768c2afb1b9debaa`
- `database.dump.list` SHA-256：`35d631fa45654c8bd4b3312ddd53688d5283be88fe4b7832ab76f166de4e0460`
- `export-dir.tgz` SHA-256：`7063d9dc30168a9ec2e9360fef2025d107c37a15084bf662276c48a57047f491`
- 旧 release、Nginx 实际配置、systemd unit/drop-in、持久化导出目录均已备份。
- 初始 `.env` 备份误为 symlink，已修正为普通文件；权限为 600，内容 SHA-256：`da1830abc833e2907e6ef7202540bc2eee19a6f8f413ea0e05f14a9afee76af9`。
- 生产持久 `.env` 已调整为 `root:www-data`、640，供服务用户读取。
- 数据库完整 restore 演练未执行；本次只完成 dump 与 `pg_restore --list` 验证。

## 数据库迁移

- 执行：`scripts/migrate_log_export_jobs.sql`
- 迁移前 `package_names` 类型为 `jsonb`。
- 旧任务 141 条，非法范围 0，NULL 0。
- 迁移后 `all_packages` 字段和 `chk_log_export_jobs_package_scope` 约束均存在。
- 迁移使用 2 秒 lock timeout、15 秒 statement timeout。

## 认证与配置

- 本机管理员密码文件：`C:\Users\喻远飞\.codex\secrets\sdk-admin-password-20261021.txt`
- 本机 scrypt 哈希文件：`C:\Users\喻远飞\.codex\secrets\sdk-admin-password-hash-20261021.txt`
- 服务器临时 hash 文件已删除；不在本记录中保存密码、哈希、token 或其他密钥。
- 旧 `ADMIN_TOKEN`、`SDK_CONFIG_TOKEN` 保持一致。
- 正式 origin：`https://sdk.deeppopgame.xyz`；Secure cookie 已启用。

## 生产验收

- 登录 200、`/me` 200、logout 200。
- 错误 CSRF 返回 403；logout 后 `/me` 返回 401。
- 旧成功 CSV 下载 200，1,563,557 bytes。
- 单包 raw：248 行，下载 200。
- 单包 H1：486 行，下载 200。
- 全包 raw：2175 行，下载 200。
- 全包 H1：4281 行，下载 200。
- 四类 CSV 的行数、表头、北京时间小时范围及单包筛选均通过。
- SDK 正确 token 通过鉴权；错误 token 返回 401。
- 已发布包 `com.ly.freeflicks@1.0.4` 的 meta、main、new-touch、new-text-rule 均返回 200，JSON 有效。

前端线上资产与本地构建一致：

- `index-HoWTecDg.css`：`ff971c938647a5bf681a775c2880a2f6f49d95e13278df0671c8471090479dbc`
- `index-Pz1S0U4k.js`：`bcecf19fb98ff48f08048edae64a7d727f2b7f94c7db6a3339c336436e91feac`

## 残余限制

- 生产机仍有一个 8102 端口的旧、非 systemd Admin 进程；公开 Nginx 未引用该端口，本次未修改或终止。
- 本次未做浏览器视觉验收，仅完成 HTTPS/API/CSV/资产 hash 验收。
- 主 checkout 的既有 dirty/untracked 文档和文件未清理；冲突文件已在仓库外备份，未覆盖或 reset。
