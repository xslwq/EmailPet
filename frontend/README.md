# EmailPet Frontend

Electron + React + TypeScript 桌宠界面，通过 `ws://127.0.0.1:8765/ws` 与后端通信。

## 安装

```bash
cd frontend
npm ci
```

## 运行与构建

```bash
# 仅启动 Vite renderer
npm run dev

# TypeScript 检查与 renderer 构建
npm run build

# 构建 renderer 并启动 Electron
EMAILPET_NO_SPAWN=1 npm run electron:dev
```

未设置 `EMAILPET_NO_SPAWN` 时，Electron 主进程会从 `backend/.venv` 启动后端；连续崩溃三次后停止重启并退出。

当前 renderer 支持重要邮件摘要、全文、意图选择和草稿审批。已知的 `chat_reply` 事件缺口记录在[公共契约](../docs/contracts.md)。开发与清理流程见[开发与验证](../docs/development.md)。
