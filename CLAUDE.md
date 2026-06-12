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
