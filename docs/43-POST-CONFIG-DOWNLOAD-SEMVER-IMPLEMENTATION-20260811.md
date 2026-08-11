# 配置下载 POST 化与按包版本实施记录

> 日期：2026-08-11
>
> 分支：`codex/post-config-download-semver`

## 1. 变更范围

本次严格实施两项需求：

1. 三类加密配置下载接口由 GET 改为 POST；
2. 配置正式版本按包名分别使用 `1.0.0` 起步的十进制三段序列。

Meta 接口保持 `POST /api/v1/config/meta`，加密算法、密钥派生、信封结构和配置 JSON 根字段均未改变。

## 2. 代码实施

### 2.1 版本规则

新增 `backend/app/services/config_version.py`：

- 严格解析 `major.minor.patch`；
- minor、patch 限定为 0～9；
- 支持 `1.0.9 → 1.1.0` 和 `1.9.9 → 2.0.0`；
- 最大版本按数值段比较，不使用字符串排序。

### 2.2 发布和回滚

- 发布在取得包级 PostgreSQL advisory transaction lock 后查询同包全部 `published/archived` 版本；
- 首次发布分配 `1.0.0`，后续从历史最大版本递增；
- 草稿不占正式版本；
- 回滚不复制记录、不生成版本，直接恢复历史记录和原密文；
- 下一次发布仍以该包历史最大版本为基准。

### 2.3 下载接口

以下接口只接受 POST，路径参数和鉴权保持不变：

```text
POST /api/v1/config/packages/{package_name}/versions/{version}/main
POST /api/v1/config/packages/{package_name}/versions/{version}/new-touch
POST /api/v1/config/packages/{package_name}/versions/{version}/new-text-rule
```

GET 请求返回 405。POST 请求没有请求体，必须携带 SDK Bearer Token。

### 2.4 历史迁移

新增 `scripts/migrate_config_versions.py`：

- 按包名分组并按发布时间、创建时间、ID 稳定排序；
- 每个包最早的正式记录映射为 `1.0.0`；
- 在写数据库之前预先解密并校验全部记录；
- 使用旧信封 AAD 解密，再以新版本 AAD 和新 nonce 重新加密；
- 通过临时版本避让 `(package_name, version)` 唯一约束；
- 全部更新处于同一事务，任何错误整体回滚；
- 同步更新 local 下发地址；
- 默认只预检，正式写入要求显式确认串；
- 当前迁移器拒绝 COS 模式，避免只改数据库而遗漏版本化对象。

预检：

```bash
set -a
source backend/.env
set +a
python scripts/migrate_config_versions.py
```

正式迁移：

```bash
python scripts/migrate_config_versions.py --apply --confirm MIGRATE_CONFIG_VERSIONS
```

命令输出只包含包数量、记录数量和版本范围，不输出密钥或配置内容。

## 3. TDD 记录

实施过程先加入失败测试，再编写最小实现：

| 范围 | 红灯证据 | 绿灯证据 |
|---|---|---|
| 版本工具 | 模块不存在，测试收集失败 | 12 项通过 |
| 发布/回滚 | 仍生成时间戳版本、回滚新增记录，4 项失败 | 10 项通过 |
| POST 下载 | POST 返回 405、GET 仍执行旧路由，3 项失败 | SDK API 与限流 20 项通过 |
| 历史迁移 | 迁移模块不存在，测试收集失败 | 迁移相关 9 项通过 |

## 4. 生产部署步骤

1. 记录生产 HEAD、工作区状态并保存脱敏补丁；
2. 使用 `pg_dump -Fc` 备份 `sdk_platform` 数据库；
3. 运行迁移预检；
4. 在维护窗口停止 `sdk-api` 和 `sdk-admin`；
5. 执行正式迁移；
6. 部署已验证分支并安装依赖；
7. 重启两个服务；
8. 验证 Meta、三个 POST 下载、三个 GET 405 和服务端解密；
9. 检查后台当前发布版本与 Meta 一致。

## 5. 回滚方案

如迁移或部署验证失败：

1. 停止两个 API 服务；
2. 恢复部署前代码目录或 Git 提交；
3. 从部署前 `pg_dump -Fc` 备份恢复数据库；
4. 启动原版本服务；
5. 验证原 Meta 和配置下载行为。

数据库备份与服务器补丁文件不得提交到 Git。

## 6. 验证结果

### 6.1 本地验证

```text
后端：93 passed
前端：4 个测试文件、11 项测试通过
前端构建：成功，662 个模块完成转换
```

全量测试首次运行发现两个旧测试替身缺少新增版本查询所需的 `scalars().all()` 接口；根因确认后只补齐测试替身，定点 2 项和后端全量 91 项均重新通过。

### 6.2 生产迁移

- 部署提交：`7005990`；
- 部署前保存了源码归档、工作区补丁和 PostgreSQL 自定义格式完整备份；
- 迁移预检：2 个包、8 条正式记录、8 条需要迁移；
- 正式迁移：2 个包、8 条记录全部完成；
- 迁移后重复预检：`changes=0`；
- `com.techflow.note.fight.apppp`：3 条正式历史记录，范围 `1.0.0–1.0.2`；
- `test.package`：5 条正式历史记录，范围 `1.0.0–1.0.4`。

### 6.3 生产数据库验证

```text
非法正式版本：0
同包重复版本：0
每包 published 数量异常：0
```

### 6.4 生产接口与解密验证

| 包名 | Meta 当前版本 | 三类 POST 下载 | 三类 GET | AES-GCM/AAD 解密 |
|---|---|---|---|---|
| `test.package` | `1.0.4` | 全部 200 | 全部 405 | 全部通过 |
| `com.techflow.note.fight.apppp` | `1.0.2` | 全部 200 | 全部 405 | 全部通过 |

OpenAPI 中配置下载路径只包含 POST。`sdk-api` 和 `sdk-admin` 均为 active，部署后最近日志未发现 `Traceback`、`ERROR` 或 `CRITICAL`。
