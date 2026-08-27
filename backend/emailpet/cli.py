"""EmailPet CLI 入口。

提供命令行界面，支持启动后端、终端对话、查看状态等子命令。
不依赖 Electron 前端，纯终端可用。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click


@click.group()
def cli() -> None:
    """EmailPet - AI Native 邮件桌宠 CLI。"""


@cli.command()
@click.option("--config", default="config.yaml", help="配置文件路径")
def start(config: str) -> None:
    """启动后端服务（等同 python -m emailpet.main）。"""
    from emailpet.main import main as main_fn
    # main() 读 sys.argv[1] 作为 config 路径，这里复用
    sys.argv = ["emailpet", config]
    main_fn()


@cli.command()
@click.option("--host", default="127.0.0.1", help="后端 WebSocket host")
@click.option("--port", default=8765, help="后端 WebSocket port")
def chat(host: str, port: int) -> None:
    """终端对话模式：连后端 ws，跟小猫聊天（不启动 Electron）。

    收到的 summary/draft/chat_reply 等事件会渲染成终端文本。
    输入文本回车即发送 user_say 事件。
    Ctrl+C 退出。
    """
    asyncio.run(_chat_loop(host, port))


async def _chat_loop(host: str, port: int) -> None:
    """终端 chat 主循环：连 ws + 并发收发。"""
    import websockets

    uri = f"ws://{host}:{port}/ws"
    try:
        async with websockets.connect(uri) as ws:
            click.echo(f"连上后端 {uri}")
            click.echo("跟小猫说点什么（Ctrl+C 退出）\n")
            # 后台任务：持续接收并渲染后端事件
            recv_task = asyncio.create_task(_receiver(ws))
            try:
                loop = asyncio.get_event_loop()
                while True:
                    # input() 是阻塞的，扔到线程池避免阻塞事件循环
                    text = await loop.run_in_executor(None, input, "> ")
                    if not text.strip():
                        continue
                    await ws.send(json.dumps({"type": "user_say", "text": text}))
            except (EOFError, KeyboardInterrupt):
                pass
            finally:
                recv_task.cancel()
    except Exception as e:
        click.echo(f"连接失败：{e}")


async def _receiver(ws) -> None:
    """持续接收 ws 消息并渲染。"""
    try:
        async for msg in ws:
            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                continue
            _render_event(data)
    except Exception:
        pass


def _render_event(data: dict) -> None:
    """把后端 ws 事件渲染成终端文本。"""
    t = data.get("type")
    if t == "chat_reply":
        # 自由对话回复
        click.echo(f"\n🐱 {data.get('reply', '')}")
        if data.get("retrieved"):
            click.echo(f"  (检索到 {data.get('retrieved_count', 0)} 封相关邮件)")
    elif t == "agent_say":
        # 小猫口头确认（skip/reject/archive 等）
        click.echo(f"\n🐱 {data.get('text', '')}")
    elif t == "summary":
        # 重要邮件摘要
        email = data.get("email", {})
        click.echo(f"\n📬 新邮件：{email.get('subject', '')}")
        click.echo(f"  发件人：{email.get('from_name', '')} <{email.get('from_address', '')}>")
        click.echo(f"  摘要：{data.get('summary', '')}")
        needs_reply = data.get("needs_reply", False)
        action = data.get("suggested_action", "")
        click.echo(f"  建议操作：{action}" + (" (需要回复)" if needs_reply else " (无需回复)"))
    elif t == "draft":
        # 回复草稿
        click.echo(f"\n✉️ 草稿：{data.get('draft', '')}")
        click.echo(f"  理由：{data.get('reason', '')}")
    elif t == "sent":
        # 发送成功
        click.echo(f"\n✅ 已发送邮件")
    elif t == "error":
        # 错误
        click.echo(f"\n❌ 错误：{data.get('message', '')}")


@cli.command()
@click.option("--config", default="config.yaml", help="配置文件路径")
def status(config: str) -> None:
    """查看状态：用户画像、邮件统计、配置摘要。"""
    from emailpet.config import Config
    from emailpet.storage.user_profile_store import UserProfileStore
    from emailpet.storage.emails_store import EmailsStore

    try:
        cfg = Config.from_yaml(config)
    except Exception as e:
        click.echo(f"配置加载失败：{e}")
        return

    # storage 目录：优先用 config 同级的 backend/emailpet/storage
    storage = Path(__file__).parent / "storage"

    click.echo("=== EmailPet 状态 ===")

    # 用户画像
    try:
        profile_store = UserProfileStore(storage / "profile.db")
        profile = profile_store.get()
        click.echo(f"\n👤 用户画像：")
        click.echo(f"  称呼：{profile.get('display_name') or '(未设置)'}")
        click.echo(f"  签名：{profile.get('signature') or '(未设置)'}")
        click.echo(f"  语气：{profile.get('tone') or '(未设置)'}")
        honorific = profile.get("honorific")
        click.echo(f"  敬语：{honorific if honorific is not None else '(未设置)'}")
        click.echo(f"  常用话术：{profile.get('common_phrases') or '[]'}")
        click.echo(f"  更新时间：{profile.get('updated_at', '(未知)')}")
    except Exception as e:
        click.echo(f"\n👤 用户画像：(加载失败：{e})")

    # 邮件统计
    try:
        import sqlite3
        conn = sqlite3.connect(str(storage / "emails.db"))
        click.echo(f"\n📬 邮件统计：")
        cur = conn.execute(
            "SELECT user_action, COUNT(*) FROM emails GROUP BY user_action ORDER BY user_action"
        )
        for action, count in cur.fetchall():
            click.echo(f"  {action}: {count} 封")
        # 未索引的重要邮件
        cur = conn.execute(
            "SELECT COUNT(*) FROM emails WHERE indexed_at IS NULL AND is_important = 1"
        )
        unindexed = cur.fetchone()[0]
        if unindexed > 0:
            click.echo(f"  待索引：{unindexed} 封")
        conn.close()
    except Exception as e:
        click.echo(f"\n📬 邮件统计：(加载失败：{e})")

    # 配置摘要
    click.echo(f"\n🔧 配置：")
    click.echo(f"  LLM：{cfg.llm.model} @ {cfg.llm.base_url}")
    click.echo(f"  Embedding：{cfg.embedding.model if cfg.embedding else '(未配置)'}")
    click.echo(f"  IMAP：{cfg.imap.username} @ {cfg.imap.host}")
    click.echo(f"  SMTP：{cfg.smtp.username} @ {cfg.smtp.host}")
    click.echo(f"  轮询间隔：{cfg.poll_interval_seconds}s")
    click.echo(f"  WebSocket：{cfg.server.ws_host}:{cfg.server.ws_port}")

    # Token 消耗
    try:
        from emailpet.storage.token_usage_store import TokenUsageStore
        token_store = TokenUsageStore(storage / "token_usage.db")
        summary = token_store.summary()
        click.echo(f"\n💰 Token 消耗：")
        if not summary:
            click.echo(f"  (暂无 token 记录)")
        else:
            grand_total = 0
            for call_type, stats in summary.items():
                count = stats["count"]
                total = stats["total_tokens"]
                avg = stats["avg_tokens"]
                chars = stats["input_chars"]
                if total > 0:
                    click.echo(f"  {call_type}: {count} 次, {total} tokens (avg {avg}/call)")
                    grand_total += total
                else:
                    click.echo(f"  {call_type}: {count} 次, {chars} chars input")
            if grand_total > 0:
                click.echo(f"  总计: {grand_total} tokens")
        token_store.close()
    except Exception as e:
        click.echo(f"\n💰 Token 消耗：(加载失败：{e})")


@cli.command()
def version() -> None:
    """显示版本号。"""
    click.echo("EmailPet 0.2.0")


def main() -> None:
    """CLI 入口（pyproject.toml [project.scripts] 指向这里）。"""
    cli()


if __name__ == "__main__":
    main()
