# 开发与验证

## 环境与安装

- Python 要求由 `backend/pyproject.toml` 定义，当前为 3.12 或更高版本。
- Node 依赖和脚本由 `frontend/package.json` 与 lockfile 定义。
- 不在仓库提交真实 `backend/config.yaml`、数据库或构建产物。

后端：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp config.example.yaml config.yaml
```

前端：

```bash
cd frontend
npm ci
```

## 启动

后端：

```bash
cd backend
source .venv/bin/activate
python -m emailpet.main
```

开发期由浏览器查看 renderer：

```bash
cd frontend
npm run dev
```

Electron 脚本会先构建 renderer 再启动 Electron。默认由主进程从 `backend/.venv` 启动后端；手动运行后端时设置 `EMAILPET_NO_SPAWN=1` 避免重复进程：

```bash
cd frontend
EMAILPET_NO_SPAWN=1 npm run electron:dev
```

## 验证命令

```bash
# 文档结构与链接
python3 scripts/check_docs.py

# 文档检查器自身测试
python3 -m unittest scripts/test_check_docs.py

# session 最终状态、文档影响和清理声明
python3 scripts/check_docs.py --final

# 后端
cd backend
python -m pytest
ruff check .

# 前端
cd frontend
npm run build
```

按改动风险选择最小相关测试，但公共契约、Agent 图、存储或跨前后端变更应运行完整相关套件。不要在 README 中写固定测试数量；命令成功才是当前验证证据。

## 文档驱动变更

1. 从 `progress.md` 和 `docs/README.md` 确定当前上下文与负责文档。
2. 产品行为、架构、公共接口、配置、数据流或安全边界变化先更新事实文档。
3. 实现代码并增加或调整测试。
4. 重新核对受影响文档，删除已经失效的旧事实。
5. 在 `progress.md` 的“文档影响”列出更新文档；若没有文档变化，写明具体理由。
6. 运行适用测试和文档校验，记录命令与结果。

## Session 与清理

会修改仓库的 session 只在开始和结束或阻塞前更新一次 `progress.md`，中途不写流水账。开始时记录基准提交和已有用户改动；结束时记录结果、剩余项、验证、文档影响、清理与下一步。

每个完成功能的现场清理包括：

- 停止当前 session 启动且不再需要的服务、watcher 和后台任务。
- 删除当前 session 创建的临时调试文件、日志、截图和一次性脚本。
- 移除调试代码和非交付配置。
- 检查 `git status --short` 与 diff，只保留任务预期改动。
- 保留 session 前已有改动、未跟踪文件、依赖目录和共享缓存；无法确认所有权时不删除。

如果 session 意外中断，`progress.md` 的 `in_progress` 状态就是下一位 Agent 的恢复信号。恢复时先核对实际工作区，不假设快照中的计划已经执行。

## 文档编写约定

- 中文描述事实，英文保留路径、符号、命令和协议字段。
- 链接到少量稳定的代码证据，不复制实现全文。
- 当前事实直接改写；历史原因写入[决策记录](decisions/README.md)。
- 草稿放在 `docs/.drafts/`，不得被正式文档引用或视为事实。
