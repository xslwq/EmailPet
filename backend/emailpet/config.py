"""YAML config loading for EmailPet backend.

See docs/modules/backend/emailpet/config.md for full module doc.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass(frozen=True)
class IMAPConfig:
    """IMAP 服务器配置，用于收取邮件。"""
    host: str
    port: int
    username: str
    password: str


@dataclass(frozen=True)
class SMTPConfig:
    """SMTP 服务器配置，用于发送邮件。"""
    host: str
    port: int
    username: str
    password: str


@dataclass(frozen=True)
class LLMConfig:
    """大语言模型 API 配置。"""
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class ServerConfig:
    """WebSocket 服务器配置。"""
    ws_host: str = "127.0.0.1"
    ws_port: int = 8765


@dataclass(frozen=True)
class EmbeddingConfig:
    """嵌入模型 API 配置（可选）。"""
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class Config:
    """EmailPet 根配置对象，聚合所有子配置。"""
    imap: IMAPConfig
    smtp: SMTPConfig
    llm: LLMConfig
    server: ServerConfig = field(default_factory=ServerConfig)
    poll_interval_seconds: int = 30
    embedding: Optional[EmbeddingConfig] = None

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        """从 YAML 文件加载配置。

        参数：
            path: YAML 文件路径

        返回：
            解析后的 Config 实例

        异常：
            FileNotFoundError: 文件不存在
            ValueError: YAML 格式错误或配置结构无效
        """
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Config file not found: {p}")
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in {p}: {e}") from e
        if not isinstance(data, dict):
            raise ValueError(
                f"Invalid config in {p}: root must be a mapping, got {type(data).__name__}"
            )
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> "Config":
        """从字典构建 Config 实例（内部解析流程）。

        解析顺序：
        1. 必需：mail.imap / mail.smtp / llm
        2. 可选：server / embedding / poll_interval_seconds
        """
        mail = _require_mapping(data, "mail")
        imap_data = _require_mapping(mail, "imap", path="mail")
        smtp_data = _require_mapping(mail, "smtp", path="mail")
        imap = _build_mail(imap_data, "imap")
        smtp = _build_mail(smtp_data, "smtp")
        llm_data = _require_mapping(data, "llm")
        llm = _build_llm(llm_data)

        server_kwargs: dict[str, Any] = {}
        if "server" in data:
            server_data = _require_mapping(data, "server")
            if "ws_host" in server_data:
                server_kwargs["ws_host"] = server_data["ws_host"]
            if "ws_port" in server_data:
                server_kwargs["ws_port"] = _validate_port(
                    server_data["ws_port"], "server.ws_port"
                )
        server = ServerConfig(**server_kwargs)

        # embedding 是可选配置，无此字段时返回 None
        embedding: Optional[EmbeddingConfig] = None
        if "embedding" in data:
            emb_data = _require_mapping(data, "embedding")
            for f in ("base_url", "api_key", "model"):
                if f not in emb_data:
                    raise ValueError(f"Missing required config field: embedding.{f}")
            embedding = EmbeddingConfig(
                base_url=emb_data["base_url"],
                api_key=str(emb_data["api_key"]),
                model=emb_data["model"],
            )

        config_kwargs: dict[str, Any] = {"imap": imap, "smtp": smtp, "llm": llm, "server": server, "embedding": embedding}
        if "poll_interval_seconds" in mail:
            poll_interval = mail["poll_interval_seconds"]
            if not isinstance(poll_interval, int) or poll_interval <= 0:
                raise ValueError("mail.poll_interval_seconds must be a positive int")
            config_kwargs["poll_interval_seconds"] = poll_interval
        return cls(**config_kwargs)


def _require(data: dict, key: str, path: str | None = None) -> None:
    """检查字典中是否存在指定键，不存在则抛 ValueError。"""
    if key not in data:
        full = f"{path}.{key}" if path else key
        raise ValueError(f"Missing required config field: {full}")


def _require_mapping(data: dict, key: str, path: str | None = None) -> dict:
    """要求键存在且值为 dict 类型（用于嵌套配置段校验）。

    参数：
        data: 父字典
        key: 要检查的键
        path: 用于错误信息的路径前缀

    返回：
        嵌套的 dict 值

    异常：
        ValueError: 键不存在或值不是 dict
    """
    _require(data, key, path=path)
    value = data[key]
    full = f"{path}.{key}" if path else key
    if not isinstance(value, dict):
        raise ValueError(
            f"Invalid config field {full}: must be a mapping, got {type(value).__name__}"
        )
    return value


def _build_mail(data: dict, kind: str) -> IMAPConfig | SMTPConfig:
    """构建 IMAPConfig 或 SMTPConfig 实例。"""
    for f in ("host", "port", "username", "password"):
        if f not in data:
            raise ValueError(f"Missing required config field: mail.{kind}.{f}")
    port = _validate_port(data["port"], f"mail.{kind}.port")
    cls = IMAPConfig if kind == "imap" else SMTPConfig
    return cls(host=data["host"], port=port, username=data["username"], password=str(data["password"]))


def _build_llm(data: dict) -> LLMConfig:
    """构建 LLMConfig 实例。"""
    for f in ("base_url", "api_key", "model"):
        if f not in data:
            raise ValueError(f"Missing required config field: llm.{f}")
    return LLMConfig(base_url=data["base_url"], api_key=str(data["api_key"]), model=data["model"])


def _validate_port(port: Any, field_name: str) -> int:
    """校验端口号必须在 1-65535 范围内。

    参数：
        port: 待校验的端口值
        field_name: 用于错误信息的字段名

    返回：
        校验通过的整数端口

    异常：
        ValueError: 类型错误或超出范围
    """
    if not isinstance(port, int) or port < 1 or port > 65535:
        raise ValueError(f"Invalid port for {field_name}: {port!r} (must be 1-65535)")
    return port
