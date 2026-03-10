import json
from pathlib import Path

from click.testing import CliRunner

from bbs_cli.cli import cli


def test_cli_login_save_writes_user_config_and_state(
    tmp_path: Path, monkeypatch
) -> None:
    def fake_request(self, method, path, params=None, json_body=None):
        assert method == "POST"
        assert path == "/auth/login"
        assert json_body == {"username": "alice", "password": "secret"}
        return {"token": "token-alice", "ok": True}

    monkeypatch.setattr("bbs_cli.client.ApiClient.request", fake_request)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--config-path",
            str(tmp_path),
            "auth",
            "login",
            "--username",
            "alice",
            "--password",
            "secret",
        ],
    )

    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    assert payload["token"] == "token-alice"
    assert payload["saved_to"] == str(tmp_path / "users" / "alice" / "config.json")

    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    user_cfg = json.loads(
        (tmp_path / "users" / "alice" / "config.json").read_text(encoding="utf-8")
    )
    assert state["last_username"] == "alice"
    assert user_cfg["token"] == "token-alice"


def test_cli_logout_without_username_errors(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--config-path", str(tmp_path), "auth", "logout"])

    assert result.exit_code != 0
    assert "Cannot determine current username. Please login first." in result.output
