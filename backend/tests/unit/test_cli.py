"""Tests for emailpet.cli - Click CLI 子命令测试。"""
from click.testing import CliRunner

from emailpet.cli import cli


def test_cli_version():
    """emailpet version 输出版本号。"""
    runner = CliRunner()
    result = runner.invoke(cli, ["version"])
    assert result.exit_code == 0
    assert "EmailPet" in result.output


def test_cli_help_lists_subcommands():
    """emailpet --help 列出所有子命令。"""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "start" in result.output
    assert "chat" in result.output
    assert "status" in result.output
    assert "version" in result.output


def test_cli_version_help():
    """emailpet version --help 显示帮助。"""
    runner = CliRunner()
    result = runner.invoke(cli, ["version", "--help"])
    assert result.exit_code == 0
    assert "版本" in result.output


def test_cli_status_no_config_friendly_error(tmp_path):
    """emailpet status 配置文件不存在时友好报错，不崩溃。"""
    runner = CliRunner()
    nonexistent = tmp_path / "nonexistent.yaml"
    result = runner.invoke(cli, ["status", "--config", str(nonexistent)])
    # 不 exit 1（我们 catch 了异常，click.echo 后 return）
    assert result.exit_code == 0
    assert "配置加载失败" in result.output


def test_cli_chat_help():
    """emailpet chat --help 显示 host/port 选项。"""
    runner = CliRunner()
    result = runner.invoke(cli, ["chat", "--help"])
    assert result.exit_code == 0
    assert "--host" in result.output
    assert "--port" in result.output


def test_cli_start_help():
    """emailpet start --help 显示 config 选项。"""
    runner = CliRunner()
    result = runner.invoke(cli, ["start", "--help"])
    assert result.exit_code == 0
    assert "--config" in result.output
