# SecurityFill 产品化交付说明

## 全流程（已跑通）

```
注册/登录 → Workspace
  → 上传策略（PDF/TXT/MD/DOCX）
  → 导入问卷（CSV/XLSX）
  → 一键生成答案（LLM 或关键词）
  → 人工审阅并入库
  → 第二份问卷命中答案库
  → 导出 XLSX/CSV
  → 升级 Pro（Stripe 或 mock）
```

## 功能 Review 记录

### F1 认证 + 多租户 — ✅ PASS
- 注册/登录/退出；signed cookie 会话
- 每用户独立 Workspace
- 知识库/问卷按 `workspace_id` 隔离
- E2E：第二用户访问他人问卷 → 404

### F2 答案库 — ✅ PASS
- 审阅后自动 upsert 入库
- 生成时优先精确/模糊匹配库答案
- `from_library` 标记 + 使用次数
- E2E：5 条入库 → 第二份问卷 ≥3 命中（实测 5）

### F3 DOCX + 用量限制 + 仪表盘 — ✅ PASS
- DOCX 解析（段落+表格）
- Free 限额：文档/月问卷/题数/库容量
- 工作台展示 usage 行
- E2E：Free 第 4 份问卷 → 402

### F4 计费 — ✅ PASS
- Stripe Checkout（配置密钥时）
- 无密钥 mock 即时升 Pro
- Webhook 处理订阅完成/取消
- 定价页 UI

### F5 交付 — ✅ PASS
- `scripts/e2e_product_flow.py` 全绿
- 演示账号 seed：`demo@securityfill.local` / `demo1234`
- README + .env.example

## 启动

```bash
cd security-fill && source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- 产品首页：http://127.0.0.1:8000  
- 工作台：http://127.0.0.1:8000/app  
- E2E：`python scripts/e2e_product_flow.py`
