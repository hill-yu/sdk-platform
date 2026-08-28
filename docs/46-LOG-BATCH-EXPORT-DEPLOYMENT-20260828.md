# SDK 原始日志批量导出接口与部署

## 一、功能与接口

后台日志页可检索并选择多个包名，结合设备 ID、日志等级和日期条件创建异步任务。独立 Worker 从 PostgreSQL 分批读取原始日志并生成 CSV。

以下接口统一要求 `Authorization: Bearer <ADMIN_TOKEN>`：

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/admin/log-packages?keyword={keyword}&limit=20` | 检索存在原始日志的包名 |
| POST | `/api/admin/log-exports` | 创建异步 CSV 导出任务 |
| GET | `/api/admin/log-exports/{job_id}` | 查询任务状态 |
| GET | `/api/admin/log-exports/{job_id}/download` | 下载成功任务的 CSV |

创建请求：

```json
{
  "package_names": ["com.example.app", "com.example.reader"],
  "device_id": "device-1",
  "log_level": "info",
  "date_from": "2026-08-01",
  "date_to": "2026-08-28"
}
```

只有 `package_names` 必传。状态为 `pending`、`running`、`success` 或 `failed`；只有 `success` 可下载，其他状态返回 409。CSV 表头为：

```text
id,package_name,device_id,sdk_version,level,tag,message,extra,client_ts,server_ts
```

`extra` 保持原始内容，不进行词库解析；时间输出为 UTC+8。

## 二、数据库迁移

```bash
psql "$DATABASE_URL" -f scripts/migrate_log_export_jobs.sql
psql "$DATABASE_URL" -c "\d sdk_log_export_jobs"
```

若 `.env` 使用 `postgresql+asyncpg://`，需换成等价的 `postgresql://` 地址交给 `psql`。

## 三、导出目录

```bash
sudo mkdir -p /www/wwwroot/sdk-api/exports
sudo chown -R www:www /www/wwwroot/sdk-api/exports
sudo chmod 750 /www/wwwroot/sdk-api/exports
```

在 `backend/.env` 增加：

```dotenv
LOG_EXPORT_DIR=/www/wwwroot/sdk-api/exports
```

宝塔实际运行用户不是 `www` 时，同时替换目录所属用户和 systemd 模板中的 `User`。

## 四、安装 Worker

按实际路径修改 `deploy/sdk-log-export-worker.service.example`，然后执行：

```bash
sudo cp deploy/sdk-log-export-worker.service.example /etc/systemd/system/sdk-log-export-worker.service
sudo systemctl daemon-reload
sudo systemctl enable --now sdk-log-export-worker
sudo systemctl restart sdk-admin
sudo systemctl status sdk-log-export-worker --no-pager
sudo journalctl -u sdk-log-export-worker -n 100 --no-pager
```

## 五、PowerShell 验收

```powershell
$BaseUrl = "https://sdk.deeppopgame.xyz"
$Headers = @{ Authorization = "Bearer $env:ADMIN_TOKEN" }
Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/admin/log-packages?keyword=test&limit=20" -Headers $Headers

$Body = @{
  package_names = @("test.package")
  log_level = "info"
  date_from = "2026-08-01"
  date_to = "2026-08-28"
} | ConvertTo-Json
$Created = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/admin/log-exports" -Headers $Headers -ContentType "application/json" -Body $Body
$JobId = $Created.data.id
Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/admin/log-exports/$JobId" -Headers $Headers
Invoke-WebRequest -Method Get -Uri "$BaseUrl/api/admin/log-exports/$JobId/download" -Headers $Headers -OutFile ".\sdk-logs-$JobId.csv"
Import-Csv ".\sdk-logs-$JobId.csv" | Select-Object -First 3
```

确认 CSV 只包含所选包名及筛选条件、`extra` 是原始内容、时间为 UTC+8，无 Admin Token 请求返回 401。

## 六、故障定位

- 一直 `pending`：检查 Worker 状态和数据库连接；
- 状态 `failed`：查看状态接口 `error_message` 和 Worker journal；
- 下载 404：检查 Admin API 与 Worker 的 `LOG_EXPORT_DIR` 是否一致以及目录权限；
- 下载 409：任务尚未完成。
