"""EmailPet backend entry point — wires all components and runs the FastAPI server.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI

from emailpet.agent.embedding import EmbeddingClient
from emailpet.agent.graph import build_agent
from emailpet.agent.llm import LLMClient
from emailpet.agent.tools import AgentTools
from emailpet.config import Config
from emailpet.mail.imap_client import IMAPClient
from emailpet.mail.smtp_client import SMTPClient
from emailpet.storage.archive_log import ArchiveLog
from emailpet.storage.emails_store import EmailsStore
from emailpet.storage.email_vec_store import EmailVecStore
from emailpet.storage.uid_store import UIDStore
from emailpet.storage.user_profile_store import UserProfileStore
from emailpet.storage.token_usage_store import TokenUsageStore
from emailpet.ws import ConnectionManager, make_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("emailpet.main")

DEFAULT_CONFIG_PATH = Path("config.yaml")
STORAGE_DIR = Path(__file__).parent / "storage"
CHECKPOINT_DB = STORAGE_DIR / "checkpoint.db"
UID_DB = STORAGE_DIR / "uid_store.db"
ARCHIVE_DB = STORAGE_DIR / "archives.db"
PROFILE_DB = STORAGE_DIR / "profile.db"
EMAILS_DB = STORAGE_DIR / "emails.db"
VEC_DB = STORAGE_DIR / "vec.db"
TOKEN_DB = STORAGE_DIR / "token_usage.db"
# 硬编码 1536 维：OpenAI text-embedding-3-small/ada-002 标准维度，
# 也是当前向量索引的预设维度，暂不支持动态配置
EMBEDDING_DIM = 1536


class AppContext:
    """应用上下文容器，持有所有长生命周期对象以便在关闭时统一清理。

    职责：
    - 集中管理所有后端组件实例
    - 确保资源按正确顺序初始化和释放
    """

    def __init__(self) -> None:
        self.config: Optional[Config] = None                    # 配置对象
        self.imap: Optional[IMAPClient] = None                  # IMAP 邮件客户端，用于收取邮件
        self.smtp: Optional[SMTPClient] = None                  # SMTP 邮件客户端，用于发送邮件
        self.llm: Optional[LLMClient] = None                    # LLM 客户端，用于调用大模型
        self.tools: Optional[AgentTools] = None                 # Agent 可用工具集
        self.archive_log: Optional[ArchiveLog] = None           # 归档日志存储
        self.uid_store: Optional[UIDStore] = None               # 已处理邮件 UID 存储
        self.profile_store: Optional[UserProfileStore] = None   # 用户偏好配置存储
        self.emails_store: Optional[EmailsStore] = None         # 邮件内容存储
        self.email_vec_store: Optional[EmailVecStore] = None    # 邮件向量索引存储
        self.embedding_client: Optional[EmbeddingClient] = None # 嵌入模型客户端（可选，None 时降级）
        self.token_store: Optional[TokenUsageStore] = None      # Token 用量统计存储
        self.manager: Optional[ConnectionManager] = None        # WebSocket 连接管理器
        self.agent = None                                       # LangGraph Agent 实例（邮件处理）
        self.saver_cm = None                                    # Checkpoint saver 上下文管理器（邮件处理）
        self.free_chat_agent = None                             # LangGraph Agent 实例（自由对话）
        self.free_chat_saver_cm = None                          # Checkpoint saver 上下文管理器（自由对话）
        self.poll_task: Optional[asyncio.Task] = None           # 邮件轮询后台任务


def _build_context(config_path: Path) -> AppContext:
    """构建应用上下文，按依赖顺序初始化所有组件。

    参数：
        config_path: YAML 配置文件路径

    返回：
        初始化完成的 AppContext 实例
    """
    ctx = AppContext()
    ctx.config = Config.from_yaml(config_path)
    ctx.token_store = TokenUsageStore(TOKEN_DB)
    ctx.imap = IMAPClient(
        ctx.config.imap.host, ctx.config.imap.port,
        ctx.config.imap.username, ctx.config.imap.password,
    )
    ctx.smtp = SMTPClient(
        ctx.config.smtp.host, ctx.config.smtp.port,
        ctx.config.smtp.username, ctx.config.smtp.password,
    )
    ctx.llm = LLMClient(
        ctx.config.llm.base_url, ctx.config.llm.api_key, ctx.config.llm.model,
        token_store=ctx.token_store,
    )
    ctx.tools = AgentTools(ctx.imap, ctx.smtp)
    ctx.archive_log = ArchiveLog(ARCHIVE_DB)
    ctx.uid_store = UIDStore(UID_DB)
    ctx.profile_store = UserProfileStore(PROFILE_DB)
    ctx.emails_store = EmailsStore(EMAILS_DB)
    ctx.email_vec_store = EmailVecStore(VEC_DB, dimensions=EMBEDDING_DIM)
    # 嵌入客户端可选：配置中无 embedding 段时设为 None，功能降级
    if ctx.config.embedding is not None:
        ctx.embedding_client = EmbeddingClient(
            ctx.config.embedding.base_url,
            ctx.config.embedding.api_key,
            ctx.config.embedding.model,
            token_store=ctx.token_store,
        )
    else:
        ctx.embedding_client = None
    ctx.manager = ConnectionManager()
    return ctx


async def poll_loop(ctx: AppContext) -> None:
    """邮件轮询主循环：每隔 poll_interval_seconds 从 IMAP 拉取新邮件并喂给 Agent。

    职责：
    - 定期拉取未处理邮件
    - 逐封喂给 Agent 处理
    - 记录已处理邮件 UID 避免重复
    - 连续失败时通知用户

    参数：
        ctx: 应用上下文，包含所有必要组件
    """
    assert ctx.config and ctx.imap and ctx.uid_store and ctx.agent
    interval = ctx.config.poll_interval_seconds
    consecutive_failures = 0  # 连续失败计数器，用于故障通知
    while True:
        try:
            # 获取已处理过的邮件 UID 集合
            seen = ctx.uid_store.processed_uids()
            # 拉取新邮件
            emails, processed_uids = await ctx.imap.poll(seen)
            consecutive_failures = 0  # 成功时重置失败计数
            # 逐封邮件送入 Agent 处理
            for email in emails:
                thread_id = f"email_{email.uid}"
                config = {"configurable": {"thread_id": thread_id}}
                try:
                    initial_state = {"pending_emails": [email]}
                    await ctx.agent.ainvoke(initial_state, config)
                    # invoke 会运行到第一个 interrupt 或 END，无论哪种都标记为已处理
                except Exception as e:  # noqa: BLE001
                    logger.warning("agent.ainvoke failed for uid=%s: %s", email.uid, e)
            # 批量标记 UID 为已处理
            for uid in processed_uids:
                ctx.uid_store.mark_processed(uid)
        except Exception as e:  # noqa: BLE001
            consecutive_failures += 1
            logger.warning("poll iteration failed (%d in a row): %s", consecutive_failures, e)
            # 连续失败 3 次时通过 WebSocket 通知用户
            if consecutive_failures == 3 and ctx.manager is not None:
                await ctx.manager.push(
                    "agent_say",
                    {"text": f"邮箱连不上了（连续 {consecutive_failures} 次），请检查网络/账号配置。"},
                )
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期钩子：启动时构建组件，关闭时按逆序清理。

    启动顺序：
    1. 构建邮件处理 LangGraph Agent（带 Sqlite checkpoint）
    2. 若 embedding 配置存在，构建自由对话 LangGraph Agent（共享 checkpoint.db）
    3. 启动邮件轮询后台任务

    关闭顺序：
    1. 取消轮询任务
    2. 关闭 IMAP/SMTP 连接
    3. 清理 checkpoint saver（邮件处理）
    4. 清理 checkpoint saver（自由对话，若存在）
    """
    ctx: AppContext = app.state.ctx
    assert ctx.manager and ctx.llm and ctx.tools and ctx.archive_log
    # 构建邮件处理 Agent（带 sqlite checkpointer），传入所有必要的依赖
    ctx.agent, ctx.saver_cm = await build_agent(
        llm=ctx.llm,
        tools=ctx.tools,
        archive_log=ctx.archive_log,
        profile_store=ctx.profile_store,
        push_callback=ctx.manager.push,
        checkpoint_path=CHECKPOINT_DB,
        emails_store=ctx.emails_store,
        email_vec_store=ctx.email_vec_store,
        embedding_client=ctx.embedding_client,
    )
    # 构建自由对话 Agent（仅当 embedding 配置存在时）
    if ctx.embedding_client is not None:
        from emailpet.agent.free_chat_graph import build_free_chat_agent
        ctx.free_chat_agent, ctx.free_chat_saver_cm = await build_free_chat_agent(
            llm=ctx.llm,
            embedding_client=ctx.embedding_client,
            email_vec_store=ctx.email_vec_store,
            emails_store=ctx.emails_store,
            user_profile_store=ctx.profile_store,
            push_callback=ctx.manager.push,
            checkpoint_path=CHECKPOINT_DB,
        )
    # 后台启动邮件轮询任务
    ctx.poll_task = asyncio.create_task(poll_loop(ctx))
    logger.info(
        "EmailPet backend started; ws on %s:%s",
        ctx.config.server.ws_host, ctx.config.server.ws_port,
    )
    try:
        yield  # 服务运行期间在此挂起
    finally:
        # 优雅关闭：按启动逆序清理资源
        if ctx.poll_task is not None:
            ctx.poll_task.cancel()
            try:
                await ctx.poll_task
            except asyncio.CancelledError:
                pass
        if ctx.imap is not None:
            try:
                await ctx.imap.close()
            except Exception as e:  # noqa: BLE001
                logger.warning("imap close failed: %s", e)
        if ctx.smtp is not None:
            try:
                await ctx.smtp.close()
            except Exception as e:  # noqa: BLE001
                logger.warning("smtp close failed: %s", e)
        if ctx.saver_cm is not None:
            try:
                await ctx.saver_cm.__aexit__(None, None, None)
            except Exception as e:  # noqa: BLE001
                logger.warning("saver cleanup failed: %s", e)
        if ctx.free_chat_saver_cm is not None:
            try:
                await ctx.free_chat_saver_cm.__aexit__(None, None, None)
            except Exception as e:  # noqa: BLE001
                logger.warning("free_chat saver cleanup failed: %s", e)
        if ctx.token_store is not None:
            try:
                ctx.token_store.close()
            except Exception as e:  # noqa: BLE001
                logger.warning("token_store close failed: %s", e)
        logger.info("EmailPet backend stopped")


def create_app(config_path: Path = DEFAULT_CONFIG_PATH) -> FastAPI:
    """应用工厂：构建 AppContext 并组装 FastAPI 应用。

    参数：
        config_path: 配置文件路径，默认为 config.yaml

    返回：
        已配置好的 FastAPI 应用实例
    """
    ctx = _build_context(config_path)
    app = make_app(
        ctx.manager,
        lambda: ctx.agent,
        lambda: ctx.free_chat_agent,
    )
    app.state.ctx = ctx
    app.router.lifespan_context = lifespan
    return app


def main() -> None:
    """命令行入口：解析配置路径并启动 uvicorn 服务器。"""
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        print(
            f"Config file not found: {config_path}\n"
            f"Copy config.example.yaml to config.yaml and fill in your credentials.",
            file=sys.stderr,
        )
        sys.exit(1)
    app = create_app(config_path)
    cfg = app.state.ctx.config
    uvicorn.run(
        app,
        host=cfg.server.ws_host,
        port=cfg.server.ws_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
