# 安全与质量审计

审计范围：2026-07-20 静态审阅；2026-09-26 复审并落地修复。未执行渗透测试或依赖漏洞联网扫描。

## 严重

- 无已确认项。

## 中等（2026-09-26 已修复）

- ~~`app/config.py`：`APP_SECRET` 存在可预测的生产回退值~~ **已修复**：引入 `ENVIRONMENT` 环境变量；生产环境缺失或使用占位符时启动即失败，开发环境未配置时自动生成进程内临时随机密钥并打印提示。
- ~~`app/config.py`：默认启用演示账号且默认密码为 `demo1234`~~ **已修复**：生产环境强制关闭 `SEED_DEMO`，页面不再输出演示凭据（仅 SEED_DEMO 生效时渲染）。
- ~~`app/routers/api.py`：上传写入无文件大小控制~~ **已修复**：`_save_upload` 以 1 MiB 块流式落盘，知识库上限 20 MB、问卷上限 10 MB（`MAX_KNOWLEDGE_UPLOAD_BYTES` / `MAX_QUESTIONNAIRE_UPLOAD_BYTES` 可调），超限返回 413 并清理临时文件。
- ~~`app/routers/billing.py`：`/api/billing/mock-upgrade` 无条件开放~~ **2026-09-26 新发现并修复**：配置了真实 Stripe 密钥时，任何登录用户仍可调用 mock 接口免费升级 Pro。现已在 `stripe_enabled()` 时返回 403。

## 轻微（2026-09-26 处理）

- ~~上传原始文件名参与落盘路径~~ **已修复**：落盘文件名完全由服务端生成（UUID + 白名单后缀），客户端文件名不再进入路径。
- ~~问卷上传成功后临时文件残留于 `uploads/`~~ **已修复**：解析后无论成败均清理；问卷行数据已入库，原文件不再被引用。
- ~~会话 cookie 未标记 `Secure`~~ **已修复**：`SESSION_COOKIE_SECURE` 默认在生产环境自动开启（HTTPS 下才发送会话 cookie）。
- ~~登录接口无速率限制~~ **已修复**：新增 `app/services/rate_limit.py` 滑动窗口限速，同一邮箱+客户端 IP 5 分钟内最多 8 次失败尝试，超出返回 429。注意：仅单进程有效，多实例部署需换用共享存储实现。
- ~~`app/main.py` 使用已弃用的 `@app.on_event("startup")`~~ **已修复**：改为 `lifespan` 上下文管理器。

## 遗留事项（未修复，供后续迭代）

- `scripts/smoke_test.py` 上传接口未携带认证，实际必 401；CI 中以 `|| echo` 掩盖，E2E 是唯一权威门禁。应改造 smoke 测试登录后再调用，或直接删除。
- 生成接口 `draft_all` 在事件循环内逐题串行 await，大问卷会长时间阻塞整个服务；生产化需要后台任务队列（见 ARCHITECTURE.md 技术债务）。
- 测试仅有脚本级 smoke/E2E，仍缺 `tests/` 目录、pytest 用例与覆盖率配置；建议补充认证、跨工作区访问、上传上限与 Stripe webhook 的单测。
- 本地 SQLite、上传文件直存文件系统适合原型；生产多实例需要对象存储、迁移与病毒/内容扫描。
