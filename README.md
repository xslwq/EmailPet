# EmailPet

> AI Native 桌面邮件助手桌宠：基于 LangGraph 的人在环邮件 Agent、FastAPI 后端与 Electron 界面。

EmailPet 不是完整邮件客户端。它在本地轮询邮箱、总结和筛选邮件，用桌宠或 CLI 主动汇报重要内容；发送回复前始终要求用户批准草稿。

## 当前能力

- IMAP 新邮件轮询、UID 去重、HTML 正文转纯文本。
- LLM 摘要、重要性分类、操作建议与保守失败兜底。
- 不重要邮件自动归档；重要邮件等待回复、归档或跳过选择。
- 草稿批准、修改循环、SMTP 发送与用户写作偏好学习。
- 本地 SQLite checkpoint、邮件记录、画像、向量索引和 token 用量统计。
- 可选 embedding 驱动的邮件检索与自由对话 Agent。
- Electron 桌宠界面和 `emailpet` CLI。

当前能力、限制与待决问题以[产品事实](docs/product.md)为准；架构和接口分别见[架构与数据流](docs/architecture.md)和[公共契约](docs/contracts.md)。

## 技术结构

| 层 | 当前实现 |
|---|---|
| Agent | LangGraph、SQLite checkpoint、人在环 interrupt |
| Backend | Python、FastAPI、WebSocket、aioimaplib、smtplib |
| LLM | OpenAI 兼容协议；embedding 可独立配置 |
| Frontend | Electron、React、TypeScript、Vite、Zustand |
| Storage | 多个职责分离的本地 SQLite 数据库与 sqlite-vec |

依赖版本以 `backend/pyproject.toml` 和 `frontend/package.json` 为准，不在本文复制版本快照。

## 快速开始

### 后端

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp config.example.yaml config.yaml
# 编辑 config.yaml，填写 IMAP、SMTP、LLM；embedding 可选
python -m emailpet.main
```

安装后也可以使用 CLI：

```bash
emailpet start --config config.yaml
emailpet chat
emailpet status --config config.yaml
```

### 前端

```bash
cd frontend
npm ci

# 仅在浏览器启动 renderer
npm run dev

# Electron；若后端已手动启动，避免重复 spawn
EMAILPET_NO_SPAWN=1 npm run electron:dev
```

Electron 默认要求后端虚拟环境位于 `backend/.venv`，并从 `backend/config.yaml` 读取配置。

## 验证

```bash
python3 scripts/check_docs.py

cd backend
python -m pytest
ruff check .

cd ../frontend
npm run build
```

完整环境、流程与现场清理要求见[开发与验证](docs/development.md)。

## 面向 Agent 开发

- [`AGENTS.md`](AGENTS.md) 是唯一自动加载的项目工作契约。
- [`progress.md`](progress.md) 保存当前或最近一次会修改仓库的 session 状态。
- [`docs/README.md`](docs/README.md) 是可修改事实基线的索引。
- 功能新增、删除或行为变化必须在同一变更中同步受影响文档。
