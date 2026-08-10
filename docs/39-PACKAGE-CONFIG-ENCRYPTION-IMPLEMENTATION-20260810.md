# SDK 分包配置与加密下发实施记录

> 日期：2026-08-10  
> 对应设计：`docs/38-PACKAGE-CONFIG-ENCRYPTION-DESIGN-20260810.md`  
> 实施分支：`codex/package-config-encryption`

## 1. 实施范围

本次仅实施 38 号设计文档确定的两项变更：配置加密保存/下发，以及配置按包名和版本隔离。未修改事件上报、日志上报、SDK 版本升级等其他业务。

## 2. 已完成内容

### 2.1 加密协议

- 新增 AES-256-GCM 加密组件。
- 使用 HKDF-SHA256 从现有 `SDK_CONFIG_TOKEN` 派生 32 字节密钥。
- 固定协议 salt 为 `sdk-config-encryption-v1`，info 为 `sdk-config/aes-256-gcm`。
- 每次加密使用新的 12 字节随机 nonce。
- 包名、版本和配置类型进入 AAD。
- 数据库完整配置使用 `config_type=full`；三份下发内容分别使用 `main`、`new_touch`、`new_text_rule`。

### 2.2 数据库和配置服务

- `sdk_configs` 增加 `package_name`、`encrypted_config`、`encryption_key_id`。
- 删除 ORM 中的明文 `config_data` 持久化字段。
- 唯一约束调整为 `(package_name, version)`。
- 已发布配置唯一索引调整为每个包名一条。
- 新建和修改草稿时立即加密；列表接口不返回配置内容；管理员详情接口鉴权后解密返回。
- 发布锁按包名哈希隔离，发布一个包只归档同包旧版本。
- 发布生成三个独立加密信封和三个包名/版本专属路径。
- 回滚重新生成版本和 nonce，不复用旧密文。

### 2.3 SDK API

- `POST /api/v1/config/meta` 请求体改为只接收必填 `package_name`。
- 服务端不再接收 `config_version`，不再替 SDK 判断版本。
- meta 返回包名、服务端版本、三个开关和三个专属地址。
- 删除旧的全局 `POST /api/v1/config/latest`。
- 新增三个通用的包名/版本/类型下发地址：

```text
GET /api/v1/config/packages/{package_name}/versions/{version}/main
GET /api/v1/config/packages/{package_name}/versions/{version}/new-touch
GET /api/v1/config/packages/{package_name}/versions/{version}/new-text-rule
```

- 本地下发地址继续要求 Bearer Token；返回值为加密信封，不包含配置明文。
- COS 对象路径为 `config/<package_name>/<version>/<type>.json`。

### 2.4 管理后台

- 增加包名筛选和新建草稿包名输入。
- 新建配置时包名必填，创建后普通编辑接口不能修改包名。
- 增加 JSON/表格模式切换。
- 表格支持字段路径、类型、字段值和删除/新增操作。
- 支持 string、number、boolean、null、object、array 类型及数组下标路径。
- 拒绝重复路径和父子路径冲突。
- 保存成功提示“配置已加密保存”。

### 2.5 数据迁移

- `scripts/init_db.sql` 已改为新部署直接使用密文表结构，不再插入明文初始配置。
- 新增 `scripts/migrate_package_encrypted_configs.sql` 创建迁移字段。
- 新增 `scripts/migrate_package_encrypted_configs.py`：强制指定默认包名和三个标准根字段，逐条加密并回读校验后替换约束；明文列在稳定验证后单独清理。

## 3. 迁移操作

迁移前必须备份数据库，并保证当前服务器 `.env` 中的 `SDK_CONFIG_TOKEN` 是 SDK 将继续使用的正式 Token。

```bash
cd /www/wwwroot/sdk-platform
source venv/bin/activate
pip install -r backend/requirements.txt

set -a
source .env
set +a

python scripts/migrate_package_encrypted_configs.py \
  --default-package-name com.example.app \
  --legacy-single-as-main
```

将示例包名替换为现有配置实际所属包名。`--legacy-single-as-main` 只在业务方明确确认后使用，它会把旧单份配置整体映射为 `mainConfig`，另外两份设为空对象；不传该参数时，缺少三个标准根字段会使迁移整体回滚。迁移脚本不会打印 Token 或配置明文。迁移成功后再部署新版后端和前端；不要先启动依赖新字段的新版服务。

新版稳定运行并完成数据库抽样验证后，才能显式删除旧明文列：

```bash
python scripts/migrate_package_encrypted_configs.py \
  --cleanup-plaintext \
  --confirm-cleanup DROP_CONFIG_DATA
```

执行清理后不能只回滚代码，必须通过迁移前数据库备份恢复旧表结构。

## 4. 新接口示例

```bash
curl -X POST 'https://sdk.deeppopgame.xyz/api/v1/config/meta' \
  -H "Authorization: Bearer $SDK_CONFIG_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"package_name":"com.example.app"}'
```

SDK 比较响应中的 `version` 与本地成功启用版本。版本不同才访问响应中的三个地址，并在解密、认证和 JSON 校验全部成功后更新本地版本。

## 5. 测试记录

- 加密组件测试覆盖随机 nonce、正常往返、错误 Token、nonce/AAD/包名/版本/类型篡改。
- 服务测试覆盖数据库无明文字段及不同包名使用不同下发路径。
- SDK API 测试覆盖包名必填、鉴权、未知包名、专属 URL 和加密下发。
- 前端测试覆盖 JSON 与字段路径表格双向转换、类型保持和路径冲突。
- `docs/SDK-CONFIG-CRYPTO-TEST-VECTOR.json` 提供固定 Token、nonce、AAD、明文和密文，供外部 iOS/Android SDK 验证跨语言实现。
- 全量验证命令与最终结果在交付前重新运行并记录到最终交付说明中。

## 6. 回滚步骤

1. 停止新版 SDK API 和 Admin API。
2. 恢复迁移前数据库备份；不能仅回滚代码，因为旧代码依赖已删除的 `config_data` 列。
3. 切回旧版本代码并恢复旧前端构建产物。
4. 启动服务并验证旧 `POST /api/v1/config/meta` 和旧配置下发链路。

## 7. 注意事项

- `SDK_CONFIG_TOKEN` 同时用于接口鉴权和派生配置密钥；修改 Token 后，旧密文不能用新 Token 解密。
- 必须先完成 SDK 客户端 AES-256-GCM/HKDF 解密适配，再切换生产配置下发协议。
- 本仓库不包含 iOS/Android SDK 客户端源码，因此客户端解密、原子缓存替换和失败保留旧配置需由 SDK 仓库使用公开测试向量完成验收；本次实现不将该外部工作虚报为已完成。
- 管理后台读取配置详情时会通过 HTTPS 获得解密后的编辑数据，但数据库、COS/CDN 和 SDK 下发内容均为密文。
- npm 依赖审计中的既有告警及 Vite 包体积警告不属于本次需求范围，本次未做依赖大版本升级或拆包重构。

## 8. 生产部署记录

部署日期：2026-08-10  
生产包名：`test.package`

- 部署前数据库备份：`/root/sdk_platform_before_package_encryption_20260810_060424.dump`
- 旧单份配置经业务方确认，整体映射为 `mainConfig`，另外两份为空对象。
- 数据迁移结果：6 条记录全部生成密文，1 条 published、1 条 draft、4 条 archived，状态未丢失。
- 观察期保留旧 `config_data` 列，尚未执行 cleanup。
- 生产后端测试：66 项通过。
- 生产前端测试：3 项通过，Vite 构建成功。
- SDK API 与 Admin API 服务均为 active，宝塔 Nginx 配置检查成功。
- 公网 `POST /api/v1/config/meta` 返回 200；三个加密配置地址均返回 200。
- 旧 `/api/v1/config/latest` 返回 404；缺少包名的 meta 请求返回 422。
- Admin 配置列表和详情返回 200；数据库 6 条密文信封中未发现业务字段明文标记。
