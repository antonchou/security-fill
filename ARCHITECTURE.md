# 架构说明

SecurityFill 是一个多租户安全问卷自动填写 SaaS 原型：用户上传策略文档和问卷，系统检索本地知识/答案库并调用可选的 OpenAI 兼容接口生成草稿，人工审阅后导出表格。

## 核心模块与数据流

- `app/main.py`：FastAPI 应用、模板页面与路由装配。
- `app/routers/`：认证、知识库、问卷、导出和计费 HTTP 接口；请求先由 `app/auth.py` 的签名 cookie 解析用户和工作区。
- `app/services/knowledge.py`、`text_extract.py`：文件落盘、文本抽取和知识分块。
- `questionnaire.py`、`answer_engine.py`、`answer_library.py`：导入问题、检索已审答案/知识、生成草稿。
- `database.py`：SQLite ORM 模型，工作区是主要隔离边界。

数据流为：浏览器 -> 会话认证 -> 工作区限定的 ORM 查询 -> 上传文件/SQLite -> 检索或 LLM -> 人工审阅 -> CSV/XLSX 导出。

## 外部依赖

SQLite（默认）、文件系统数据目录、OpenAI 兼容 API（可选）、Stripe Checkout/Webhook（可选）；环境变量含 `APP_SECRET`、`OPENAI_*`、`STRIPE_*`、`DATA_DIR`。

## 已知技术债务

本地 SQLite 和上传文件持久化适合原型；生产多实例需要对象存储、迁移、后台任务及病毒/内容扫描。
