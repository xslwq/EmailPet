# 架构与数据流

## 当前结构

```text
IMAP ──poll──> FastAPI lifecycle ──invoke──> 邮件 LangGraph
                                            │
                       SQLite stores <──────┼──────> LLM / Embedding API
                                            │
Electron / CLI <──── WebSocket /ws ───── ConnectionManager
                                            │
                                      自由对话 LangGraph
                                            │
                                 邮件向量索引 + 用户画像
```

- Electron 主进程创建悬浮窗口，并默认从 `backend/.venv` 启动 Python 后端；后端连续崩溃三次后停止重启并退出应用。
- FastAPI 生命周期负责创建客户端、存储和两个 LangGraph Agent，启动邮件轮询任务，并在关闭时释放资源。
- `ConnectionManager` 只保留一个活动 WebSocket，离线消息缓冲上限为 50；新连接替换旧连接。
- 所有持久化当前都位于 `backend/emailpet/storage/` 的本地 SQLite 文件。

## 邮件处理 Agent

每封邮件使用 `email_<uid>` 作为 LangGraph `thread_id`。生产环境以 `AsyncSqliteSaver` 持久化状态，并在 `wait_intent` 与 `wait_decision` 之前中断。

```text
summarize
  ├─ 不重要 → silent_archive → END
  └─ 重要 → notify_summary → [等待 intent]
                                ├─ archive → execute_archive → END
                                ├─ skip → notify_skip → END
                                └─ reply → draft_reply → [等待 decision]
                                                           ├─ approve → execute_reply → END
                                                           ├─ reject → notify_reject → END
                                                           └─ modify → profile_update
                                                                         └─ draft_reply（循环）
```

关键行为：

- `summarize` 只消费 `pending_emails` 的第一封邮件；摘要失败时 LLM 层采用保守兜底，避免误判为不重要。
- 摘要会写入 `emails.db`。重要邮件通知成功后，如果 embedding 可用，会尽力创建向量索引；索引失败不阻塞主流程。
- 静默归档会调用 IMAP 工具、写入归档日志并更新邮件行为。
- 用户修改草稿时先尝试更新画像，再根据反馈重新生成草稿；画像更新失败不会发送邮件。
- 只有 `approve` 路径调用 SMTP。发送成功后尝试标记原邮件已读并记录回复正文。

## 自由对话 Agent

自由对话仅在配置了 embedding 时创建，固定使用 `chat_default` 线程，并与邮件 Agent 共用 checkpoint 数据库但使用不同 `thread_id`。

```text
retrieve → llm_reply → [等待下一条 user_say] → retrieve（循环）
```

- `retrieve` 对最后一条用户消息生成 embedding，从本地向量索引取最多 5 个邮件 UID。
- `llm_reply` 组合相关邮件摘要、用户画像和会话历史生成回复。
- embedding 或检索失败时降级为空上下文；LLM 回复失败时发送 `error` 事件。

## 生命周期与故障处理

- 邮件轮询单次成功后重置连续失败计数；连续失败三次时向前端推送一次连接错误提示。
- 每轮轮询把 IMAP 返回的已处理 UID 写入 `uid_store.db`，即使某封邮件的 Agent 调用失败也不会无限重复拉取。
- WebSocket 发送失败时消息回到缓冲队列；客户端连接或发送 `resync` 时刷新缓冲。
- embedding 未配置时邮件主流程继续工作，自由对话明确返回不可用提示。
- SQLite、IMAP、SMTP 和 checkpointer 在应用关闭时按生命周期释放；部分 store 没有在当前 shutdown 路径显式关闭，是现状而非设计保证。

## 安全与信任边界

- 邮件内容和用户输入是不可信文本，只能作为 LLM 上下文，不能改变工具授权边界。
- SMTP 发送必须经过第二个人在环中断的明确批准。
- 自动归档不重要邮件是当前唯一无需逐封确认的邮件副作用。
- 外部凭据只来自被 Git 忽略的 `backend/config.yaml`；文档、测试输出和日志不得复制真实凭据或邮件正文。

## 更新触发条件

修改 `main.py` 生命周期、任一 Agent 图、节点路由、外部副作用、存储边界、降级策略或进程托管方式时，必须同步更新本文；形成长期架构选择时同时增加[决策记录](decisions/README.md)。
