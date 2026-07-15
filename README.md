# EmailPet

> AI Native 桌面邮件助手桌宠 —— 基于 LangGraph 的人在环 Agent + Electron 桌面宠物。

## 它是什么

不是邮件客户端。是一只会替你**看邮箱**的 Q 版桌宠：
- 后台 IMAP 拉新邮件，LLM 判断重不重要
- 重要邮件主动跳出来跟你汇报：「老板让你周三交方案」
- 你说"写回复" → Agent 起草 → 你点"同意"才发出去
- 不重要的（广告/通知）自动归档，不打扰你

## 技术栈

| 层 | 技术 |
|----|------|
| Agent | LangGraph 0.4 + AsyncSqliteSaver checkpoint + 双 interrupt 人在环 |
| Backend | Python 3.12 + FastAPI + WebSocket + aioimaplib + smtplib |
| LLM | OpenAI 兼容协议（任意 base_url 即插即用） |
| Frontend | Electron 30 + React 18 + TypeScript + Vite + Zustand |
| 通信 | WebSocket（双向，断线重连，事件队列） |
| 存储 | SQLite × 3：checkpoint / processed UID / silent archive log |

## 项目结构

```
EmailPet/
├── backend/
│   ├── pyproject.toml
│   ├── config.example.yaml      # 复制为 config.yaml 并填凭据
│   └── emailpet/
│       ├── main.py              # FastAPI + 30s poll loop + 生命周期
│       ├── config.py            # YAML → frozen dataclass
│       ├── ws.py                # ConnectionManager + 消息分发 + 50 条断线缓冲
│       ├── mail/
│       │   ├── models.py        # Email / Summary / Draft
│       │   ├── imap_client.py   # 异步 IMAP，UID 去重，HTML→纯文本
│       │   └── smtp_client.py   # smtplib 走 to_thread，UTF-8 主题/正文
│       ├── agent/
│       │   ├── state.py         # AgentState TypedDict
│       │   ├── tools.py         # reply / archive / mark_read
│       │   ├── llm.py           # OpenAI 兼容 + 1 次重试 + JSON 兜底
│       │   ├── nodes.py         # 6 节点 + 3 路由
│       │   └── graph.py         # StateGraph 装配 + 双 interrupt
│       └── storage/
│           ├── uid_store.py     # 已处理 UID 跟踪
│           └── archive_log.py   # 静默归档日志
└── frontend/
    ├── electron/{main,preload}.ts   # 无框透明窗 + 拖拽 + 后端进程托管
    └── src/
        ├── App.tsx              # 组合 Pet + 消息流 + 输入框
        ├── hooks/useAgent.ts    # WS 连接 + 消息分发 + 重连
        ├── store/chat.ts        # Zustand 聊天 store
        └── components/{Pet,Bubble,Input,FullTextModal}.tsx
```

## 快速开始

### 1. 后端

```bash
cd backend
# 系统 Python ≥ 3.12，没有就用 uv
uv venv --python 3.12
source .venv/bin/activate
pip install -e ".[dev]"

# 跑测试（103 个）
pytest
```

### 2. 配置

```bash
cd backend
cp config.example.yaml config.yaml
# 填入 IMAP/SMTP 账号 + LLM API key
```

### 3. 启动

```bash
# 终端 1：后端
cd backend && source .venv/bin/activate
python -m emailpet.main

# 终端 2：前端（开发期）
cd frontend
npm install
npm run electron:dev
```

正式打包后 Electron 主进程会自动 spawn 后端。

## Agent 状态机

```
poll_inbox（30s）
    │
    ▼
summarize (LLM #1)
    │
    ├─ is_important=false → silent_archive → END (不打扰)
    │
    └─ is_important=true → notify_summary → [interrupt #1]
                                              │
                                  ┌───────────┼───────────┐
                                  │           │           │
                                reply      archive       skip
                                  │           │           │
                                  ▼           ▼           ▼
                            draft_reply   execute     END
                                  │       _archive
                                  ▼
                            [interrupt #2]
                                  │
                          ┌───────┼───────┐
                          │       │       │
                       approve  modify  reject
                          │       │       │
                          ▼       │       ▼
                       execute    │     END
                       _reply     └─→ draft_reply (loop)
                          │
                          ▼
                         END

