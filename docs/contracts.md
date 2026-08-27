# 公共契约

本文记录跨模块或用户可见的当前接口。内部函数签名以代码为准，不在这里逐项复制。

## 配置

默认配置路径为后端进程当前目录下的 `config.yaml`。示例见 `backend/config.example.yaml`；真实文件被 Git 忽略。

| 路径 | 必需 | 当前约束 |
|---|---|---|
| `mail.imap.{host,port,username,password}` | 是 | `port` 为 1–65535 整数 |
| `mail.smtp.{host,port,username,password}` | 是 | `port` 为 1–65535 整数 |
| `mail.poll_interval_seconds` | 否 | 正整数，默认 30 |
| `llm.{base_url,api_key,model}` | 是 | OpenAI 兼容接口 |
| `server.ws_host` | 否 | 默认 `127.0.0.1` |
| `server.ws_port` | 否 | 1–65535 整数，默认 8765 |
| `embedding.{base_url,api_key,model}` | 否 | 三个字段必须同时存在；当前索引要求 1536 维 |

## CLI

安装后入口为 `emailpet`：

| 命令 | 行为 |
|---|---|
| `emailpet start --config PATH` | 使用指定配置启动后端 |
| `emailpet chat --host HOST --port PORT` | 连接 `/ws`，发送 `user_say` 并渲染服务端事件 |
| `emailpet status --config PATH` | 显示画像、邮件统计、配置摘要和 token 用量 |
| `emailpet version` | 显示包版本 |

`python -m emailpet.main [CONFIG_PATH]` 是后端模块入口；默认读取 `config.yaml`。

## WebSocket

服务端只暴露 `GET /ws` 的 WebSocket 升级端点，没有业务 HTTP API。所有消息为带 `type` 字段的 JSON object。

客户端到服务端：

| `type` | 字段 | 行为 |
|---|---|---|
| `decision_intent` | `thread_id`, `intent: reply|archive|skip` | 恢复邮件 Agent 的意图中断点 |
| `decision_draft` | `thread_id`, `decision: approve|modify|reject`, `feedback?` | 恢复草稿中断点；`modify` 可带反馈 |
| `user_say` | `text` | 写入 `chat_default` 自由对话线程 |
| `resync` | 无 | 刷新最多 50 条离线缓冲消息 |
| `ping` | 无 | 无响应的保活消息 |

服务端到客户端：

| `type` | 主要字段 | 来源 |
|---|---|---|
| `summary` | `thread_id`, `email`, `summary`, `body_text`, `suggested_action`, `needs_reply` | 重要邮件通知 |
| `draft` | `thread_id`, `draft`, `reason` | 回复草稿 |
| `sent` | `thread_id`, `email_id` | SMTP 发送成功 |
| `agent_say` | `text` | 归档、跳过、拒绝或系统提示 |
| `chat_reply` | `thread_id`, `reply`, `retrieved`, `retrieved_count` | 自由对话回复 |
| `error` | `code`, `message` | 校验或外部调用失败 |

当前契约缺口：CLI 能处理 `chat_reply`，但 `frontend/src/hooks/useAgent.ts` 的 `ServerMessage` 和映射没有该分支，因此 Electron 会丢弃自由对话回复。修复时必须同步本文和前端消息类型。

## Agent 状态与线程

- 邮件状态包含待处理邮件、当前邮件/摘要、用户意图、草稿、草稿决定、反馈和历史；所有字段在图执行期间渐进填充。
- 自由对话状态包含追加式 `messages`、`retrieved_emails` 和 `thread_id`。
- 邮件线程 ID 为 `email_<uid>`；自由对话线程 ID 固定为 `chat_default`。
- 两个 Agent 使用同一个 `checkpoint.db`，依靠线程 ID 隔离。

## 本地持久化

| 文件 | 当前职责 |
|---|---|
| `checkpoint.db` | 两个 LangGraph 的 checkpoint |
| `uid_store.db` | 已处理 IMAP UID 去重 |
| `archives.db` | 自动静默归档记录 |
| `profile.db` | 单用户称呼、签名、语气、敬语和常用短语 |
| `emails.db` | 邮件正文、摘要、分类、重要性、用户行为、回复正文和索引时间 |
| `vec.db` | 基于 sqlite-vec 的邮件向量，固定 1536 维 |
| `token_usage.db` | 按调用类型记录 LLM/embedding 用量 |

这些数据库当前没有迁移框架或公开兼容性承诺。修改表结构前必须记录迁移与回滚决策，不能只改建表 SQL。

## 更新触发条件

修改配置字段、默认值、CLI 命令、WebSocket 消息、Agent state、thread ID、数据库职责或外部副作用时，必须先更新本文并补充相应测试。
