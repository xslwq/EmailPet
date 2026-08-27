# EmailPet Agent 工作契约

本仓库把版本化文档视为 Agent 可修改的当前事实基线，而不是历史快照。任何实现变化都必须同步修订受影响的事实；历史原因放入决策记录。

## 开始工作前

1. 阅读根目录 `progress.md`，确认上一 session 的状态、未完成项和工作区交接。
2. 阅读 `docs/README.md`，再按任务打开相关事实文档。
3. 检查 `git status --short`、当前分支和基准提交；已有修改都属于用户，除非有证据表明是当前 session 创建的。
4. 只有会修改仓库的 session 才更新 `progress.md`。该文件必须是 session 的第一项仓库改动：写入目标、范围、基准提交、开始前工作区和 `in_progress` 状态。

纯问答、解释和只读审查不修改 `progress.md`。

## 事实优先级

- 代码和配置描述当前实现，测试提供验证证据；两者冲突时明确记录，不替任一方猜测意图。
- `docs/product.md`、`docs/architecture.md`、`docs/contracts.md` 和 `docs/development.md` 描述当前有效事实。发现腐烂内容时，在当前变更中直接修正。
- 已确认但尚未实现的目标必须与当前实现分开；不确定内容放入“待决问题”。
- Git 历史和 `docs/decisions/` 用于解释过去的选择，不覆盖当前代码事实。
- 不在文档中维护测试总数、临时进度、构建产物清单等容易失效的信息。

## 功能与文档同步

新增、删除或改变任何功能时，必须在同一变更中更新所有受影响的版本化文档：

| 变更 | 至少检查 |
|---|---|
| 产品能力、用户流程、限制 | `docs/product.md` |
| Agent 图、组件边界、数据流、故障降级 | `docs/architecture.md` |
| WebSocket、CLI、配置、状态或持久化格式 | `docs/contracts.md` |
| 依赖、启动、测试、打包或开发流程 | `docs/development.md` 与相关 README |
| 跨模块、长期或难以逆转的选择 | `docs/decisions/` |

- 产品行为、架构、公共接口、配置、数据流或安全边界变更必须先更新设计说明，再实现代码。
- 普通局部变更可同步更新代码和文档，但交付时不得留下文档债。
- 纯内部重构若不影响任何事实文档，必须在 `progress.md` 的“文档影响”中写出可核查理由。
- 不为每个源码文件机械创建镜像文档；记录稳定行为、边界、契约与维护所需上下文。

## 实现与验证

- 保持改动聚焦，复用现有结构；不要为了匹配旧文档而擅自改变运行行为。
- 不提交 `backend/config.yaml`、API key、邮箱凭据或真实邮件内容。
- 后端最小验证：`cd backend && python -m pytest`。
- 后端静态检查：`cd backend && ruff check .`。
- 前端构建验证：`cd frontend && npm run build`。
- 文档结构检查：`python3 scripts/check_docs.py`。
- Session 收尾检查：`python3 scripts/check_docs.py --final`。
- 只运行与风险相称的检查；无法运行时在 `progress.md` 和交付说明中记录原因与未验证范围。

## Session 收尾与现场清理

每个功能实现完成后主动清理本 session 的现场；session 结束或阻塞前必须完成以下步骤：

1. 停止仅由本 session 启动且不再需要的后台进程。
2. 删除仅由本 session 创建的临时文件、调试脚本、日志、截图和一次性产物。
3. 移除临时调试代码、调试配置和无意留下的改动。
4. 检查 `git status --short` 和最终 diff，只保留预期交付内容。
5. 绝不删除 session 开始前已有的未跟踪文件、用户改动、依赖目录或共享缓存；所有权不明确时保留并记录。
6. 将长期事实和决策迁入 `docs/`，再更新 `progress.md` 的完成项、剩余项、验证、文档影响、清理结果和下一步。
7. 把状态设为 `completed` 或 `blocked`，运行 `python3 scripts/check_docs.py --final` 后再交付。

`progress.md` 是滚动快照，不是追加日志。中途不要求逐操作更新；新 session 覆盖旧快照前，必须先迁移仍有价值的信息。
