# EmailPet

## currentDate
Today's date is 2026/06/12.

## 文档先行（硬性要求）

**没有文档就没有代码。**

- 每个模块在写代码**之前**，必须先在 `docs/modules/<module-path>.md` 里写完详细说明
- 文档必须覆盖：模块职责、输入输出、依赖、内部数据结构、关键算法/流程、边界与异常
- 文档与代码同步：改代码必须先改文档
- `docs/` 目录**不入 git**（已在 `.gitignore`），仅本地保存
- 设计 spec 在 `docs/superpowers/specs/`
- 模块文档在 `docs/modules/`，路径与代码路径镜像（例如 `backend/emailpet/agent/nodes.py` 对应 `docs/modules/backend/emailpet/agent/nodes.md`）

## 项目目标

EmailPet：基于 LangGraph 的 AI Native 桌面邮件助手桌宠。设计 spec 见 `docs/superpowers/specs/2026-06-12-emailpet-mvp-design.md`。

## MVP 状态（2026-06-12）

**结构完整、自动化测试覆盖完成。** 待用户做真实环境联调（Task 4-1/4-2/4-3）。

- Backend：13 模块，103 个 pytest 自动化测试全过
- Frontend：7 React 组件 + Zustand store + Electron 主进程，TypeScript 严格模式编译干净，Vite build 通过
- Agent：LangGraph 6 节点 + 2 interrupt 点 + AsyncSqliteSaver checkpoint
- 待联调：填 `backend/config.yaml`（真实 IMAP/SMTP 凭据 + LLM key）→ 启动后端 → 启动 Electron 前端 → 走完 happy path（重要邮件 → 摘要 → 写回复 → approve → 发送）

## 关键命令

```bash
# 跑全部后端测试
cd backend && source .venv/bin/activate && pytest

# 启动后端（需要先 cp config.example.yaml config.yaml 并填凭据）
python -m emailpet.main

# 启动前端（开发期，需要后端已在跑）
cd frontend && npm run electron:dev
```
