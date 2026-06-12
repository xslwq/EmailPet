"""EmailPet backend entry point — wires all components and runs the FastAPI server.

See docs/modules/backend/emailpet/main.md for full module doc.
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

from emailpet.agent.graph import build_agent
from emailpet.agent.llm import LLMClient
from emailpet.agent.tools import AgentTools
from emailpet.config import Config
from emailpet.mail.imap_client import IMAPClient
from emailpet.mail.smtp_client import SMTPClient
from emailpet.storage.archive_log import ArchiveLog
from emailpet.storage.uid_store import UIDStore
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


class AppContext:
    """Holds all long-lived objects so they can be cleaned up on shutdown."""

    def __init__(self) -> None:
        self.config: Optional[Config] = None
        self.imap: Optional[IMAPClient] = None
        self.smtp: Optional[SMTPClient] = None
        self.llm: Optional[LLMClient] = None
        self.tools: Optional[AgentTools] = None
        self.archive_log: Optional[ArchiveLog] = None
        self.uid_store: Optional[UIDStore] = None
        self.manager: Optional[ConnectionManager] = None
        self.agent = None
        self.saver_cm = None
        self.poll_task: Optional[asyncio.Task] = None


def _build_context(config_path: Path) -> AppContext:
    ctx = AppContext()
    ctx.config = Config.from_yaml(config_path)
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
    )
    ctx.tools = AgentTools(ctx.imap, ctx.smtp)
    ctx.archive_log = ArchiveLog(ARCHIVE_DB)
    ctx.uid_store = UIDStore(UID_DB)
    ctx.manager = ConnectionManager()
    return ctx


async def poll_loop(ctx: AppContext) -> None:
    """Forever-loop that polls IMAP every poll_interval_seconds and feeds the agent."""
    assert ctx.config and ctx.imap and ctx.uid_store and ctx.agent
    interval = ctx.config.poll_interval_seconds
    consecutive_failures = 0
    while True:
        try:
            seen = ctx.uid_store.processed_uids()
            emails, processed_uids = await ctx.imap.poll(seen)
            consecutive_failures = 0
            for email in emails:
                thread_id = f"email_{email.uid}"
                config = {"configurable": {"thread_id": thread_id}}
                try:
                    initial_state = {"pending_emails": [email]}
                    await ctx.agent.ainvoke(initial_state, config)
                    # invoke runs until first interrupt or END; either way mark processed
                except Exception as e:  # noqa: BLE001
                    logger.warning("agent.ainvoke failed for uid=%s: %s", email.uid, e)
            for uid in processed_uids:
                ctx.uid_store.mark_processed(uid)
        except Exception as e:  # noqa: BLE001
            consecutive_failures += 1
            logger.warning("poll iteration failed (%d in a row): %s", consecutive_failures, e)
            if consecutive_failures == 3 and ctx.manager is not None:
                await ctx.manager.push(
                    "agent_say",
                    {"text": f"邮箱连不上了（连续 {consecutive_failures} 次），请检查网络/账号配置。"},
                )
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan hook — build/teardown all components."""
    ctx: AppContext = app.state.ctx
    assert ctx.manager and ctx.llm and ctx.tools and ctx.archive_log
    # Build the agent (with sqlite checkpointer)
    ctx.agent, ctx.saver_cm = await build_agent(
        llm=ctx.llm,
        tools=ctx.tools,
        archive_log=ctx.archive_log,
        push_callback=ctx.manager.push,
        checkpoint_path=CHECKPOINT_DB,
    )
    # Start poll loop in background
    ctx.poll_task = asyncio.create_task(poll_loop(ctx))
    logger.info(
        "EmailPet backend started; ws on %s:%s",
        ctx.config.server.ws_host, ctx.config.server.ws_port,
    )
    try:
        yield
    finally:
        # Graceful shutdown
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
        logger.info("EmailPet backend stopped")


def create_app(config_path: Path = DEFAULT_CONFIG_PATH) -> FastAPI:
    """Factory: build the AppContext and wire up the FastAPI app."""
    ctx = _build_context(config_path)
    app = make_app(ctx.manager, lambda: ctx.agent)
    app.state.ctx = ctx
    app.router.lifespan_context = lifespan
    return app


def main() -> None:
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
