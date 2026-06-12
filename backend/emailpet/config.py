"""YAML config loading for EmailPet backend.

See docs/modules/backend/emailpet/config.md for full module doc.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class IMAPConfig:
    host: str
    port: int
    username: str
    password: str


@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    username: str
    password: str


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class ServerConfig:
    ws_host: str = "127.0.0.1"
    ws_port: int = 8765


@dataclass(frozen=True)
class Config:
    imap: IMAPConfig
    smtp: SMTPConfig
    llm: LLMConfig
    server: ServerConfig = field(default_factory=ServerConfig)
    poll_interval_seconds: int = 30

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Config file not found: {p}")
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in {p}: {e}") from e
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> "Config":
        _require(data, "mail")
        mail = data["mail"]
        _require(mail, "imap", path="mail")
        _require(mail, "smtp", path="mail")
        imap = _build_mail(mail["imap"], "imap")
        smtp = _build_mail(mail["smtp"], "smtp")
        _require(data, "llm")
        llm = _build_llm(data["llm"])
        server_data = data.get("server", {})
        server = ServerConfig(
            ws_host=server_data.get("ws_host", "127.0.0.1"),
            ws_port=_validate_port(server_data.get("ws_port", 8765), "server.ws_port"),
        )
        poll_interval = mail.get("poll_interval_seconds", 30)
        if not isinstance(poll_interval, int) or poll_interval <= 0:
            raise ValueError("mail.poll_interval_seconds must be a positive int")
        return cls(imap=imap, smtp=smtp, llm=llm, server=server, poll_interval_seconds=poll_interval)


def _require(data: dict, key: str, path: str | None = None) -> None:
    if key not in data:
        full = f"{path}.{key}" if path else key
        raise ValueError(f"Missing required config field: {full}")


def _build_mail(data: dict, kind: str) -> IMAPConfig | SMTPConfig:
    for f in ("host", "port", "username", "password"):
        if f not in data:
            raise ValueError(f"Missing required config field: mail.{kind}.{f}")
    port = _validate_port(data["port"], f"mail.{kind}.port")
    cls = IMAPConfig if kind == "imap" else SMTPConfig
    return cls(host=data["host"], port=port, username=data["username"], password=str(data["password"]))


def _build_llm(data: dict) -> LLMConfig:
    for f in ("base_url", "api_key", "model"):
        if f not in data:
            raise ValueError(f"Missing required config field: llm.{f}")
    return LLMConfig(base_url=data["base_url"], api_key=str(data["api_key"]), model=data["model"])


def _validate_port(port: Any, field_name: str) -> int:
    if not isinstance(port, int) or port < 1 or port > 65535:
        raise ValueError(f"Invalid port for {field_name}: {port!r} (must be 1-65535)")
    return port
