# Claude Fix Task: SDK Platform — 最后收尾（2项）

## 项目位置
D:\code\SDK\

## ⚠️ 每项修复后立即 git add + git commit

---

## Fix A: core/config.py — COS_SECRET_KEY 加 repr=False

文件: D:\code\SDK\backend\app\core\config.py

问题: COS_SECRET_KEY 缺少 repr=False，日志/调试输出可能泄露密钥

修改: 将第 25 行左右的:
```python
COS_SECRET_KEY: str = Field(default="", ...)
```
改为:
```python
COS_SECRET_KEY: str = Field(default="", repr=False)
```

提交: `git commit -m "fix: COS_SECRET_KEY加repr=False防密钥泄露到日志"`

---

## Fix B: admin_main.py — 强化 ADMIN_TOKEN 启动校验

文件: D:\code\SDK\backend\app\admin_main.py

问题: 启动校验只检查 "change-me"，弱 token 如 "sdk-platform-admin-token-2026" 也能通过

修改: 在 lifespan 的 ADMIN_TOKEN 校验中，加强为:
```python
if (not settings.ADMIN_TOKEN 
    or len(settings.ADMIN_TOKEN) < 32 
    or "change-me" in settings.ADMIN_TOKEN.lower()
    or "admin" in settings.ADMIN_TOKEN.lower()):
    raise RuntimeError(
        "ADMIN_TOKEN 未设置或过于简单！请用 python -c \"import secrets; print(secrets.token_urlsafe(32))\" 生成强随机 Token，\n"
        "然后在 .env 中设置: ADMIN_TOKEN=<生成的token>"
    )
```

提交: `git commit -m "fix: 强化ADMIN_TOKEN启动校验，要求最少32字符随机串"`
