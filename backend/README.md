# EmailPet Backend

Python 后端负责 IMAP 轮询、两条 LangGraph 工作流、WebSocket、SMTP 工具调用和本地持久化。

## 安装与配置

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp config.example.yaml config.yaml
```

`config.yaml` 包含本地凭据且不会进入 Git。字段契约见[公共契约](../docs/contracts.md)。

## 运行

```bash
python -m emailpet.main

# 或安装后的 CLI
emailpet start --config config.yaml
emailpet status --config config.yaml
emailpet chat
```

## 验证

```bash
python -m pytest
ruff check .
```

架构、Agent 路由和降级行为见[架构与数据流](../docs/architecture.md)，完整开发流程见[开发与验证](../docs/development.md)。
