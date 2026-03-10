import json
from pathlib import Path
from datetime import datetime, timezone

from click.testing import CliRunner

from bbs_cli.cli import cli


def _write_state(root: Path, username: str) -> None:
    (root / "state.json").write_text(
        json.dumps({"last_username": username}, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_history(root: Path, username: str) -> dict[str, str]:
    history_path = root / "users" / username / "history.json"
    data = json.loads(history_path.read_text(encoding="utf-8"))
    return data["post_last_visited"]


def test_posts_get_records_history_for_current_user(tmp_path: Path, monkeypatch) -> None:
    _write_state(tmp_path, "alice")

    def fake_request(self, method, path, params=None, json_body=None):
        assert method == "GET"
        assert path == "/posts/101"
        return {"id": 101, "title": "hello"}

    monkeypatch.setattr("bbs_cli.client.ApiClient.request", fake_request)

    runner = CliRunner()
    result = runner.invoke(cli, ["--config-path", str(tmp_path), "posts", "get", "101"])

    assert result.exit_code == 0, result.output
    history = _read_history(tmp_path, "alice")
    assert "101" in history
    assert history["101"]


def test_posts_replies_list_updates_same_post_timestamp(
    tmp_path: Path, monkeypatch
) -> None:
    _write_state(tmp_path, "alice")

    class _FakeDatetime:
        _values = [
            datetime(2026, 3, 9, 10, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 3, 9, 11, 0, 0, tzinfo=timezone.utc),
        ]
        _index = 0

        @classmethod
        def now(cls, tz=None):
            value = cls._values[cls._index]
            cls._index += 1
            return value

    def fake_request(self, method, path, params=None, json_body=None):
        assert method == "GET"
        assert path == "/posts/9/replies"
        return {"items": []}

    monkeypatch.setattr("bbs_cli.client.ApiClient.request", fake_request)
    monkeypatch.setattr("bbs_cli.cli.datetime", _FakeDatetime)

    runner = CliRunner()
    first = runner.invoke(
        cli, ["--config-path", str(tmp_path), "posts", "replies", "list", "9"]
    )
    assert first.exit_code == 0, first.output
    first_value = _read_history(tmp_path, "alice")["9"]

    second = runner.invoke(
        cli, ["--config-path", str(tmp_path), "posts", "replies", "list", "9"]
    )
    assert second.exit_code == 0, second.output
    second_value = _read_history(tmp_path, "alice")["9"]

    assert first_value == "2026-03-09T10:00:00+00:00"
    assert second_value == "2026-03-09T11:00:00+00:00"


def test_post_history_isolated_between_users(tmp_path: Path, monkeypatch) -> None:
    def fake_request(self, method, path, params=None, json_body=None):
        assert method == "GET"
        return {"ok": True}

    monkeypatch.setattr("bbs_cli.client.ApiClient.request", fake_request)
    runner = CliRunner()

    _write_state(tmp_path, "alice")
    alice_result = runner.invoke(
        cli, ["--config-path", str(tmp_path), "posts", "get", "77"]
    )
    assert alice_result.exit_code == 0, alice_result.output

    _write_state(tmp_path, "bob")
    bob_result = runner.invoke(
        cli, ["--config-path", str(tmp_path), "posts", "replies", "list", "77"]
    )
    assert bob_result.exit_code == 0, bob_result.output

    alice_history = _read_history(tmp_path, "alice")
    bob_history = _read_history(tmp_path, "bob")
    assert "77" in alice_history
    assert "77" in bob_history
    assert (tmp_path / "users" / "alice" / "history.json").exists()
    assert (tmp_path / "users" / "bob" / "history.json").exists()


def test_post_history_skip_when_username_missing(tmp_path: Path, monkeypatch) -> None:
    def fake_request(self, method, path, params=None, json_body=None):
        return {"id": 55}

    monkeypatch.setattr("bbs_cli.client.ApiClient.request", fake_request)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--config-path", str(tmp_path), "--token", "t", "posts", "get", "55"]
    )

    assert result.exit_code == 0, result.output
    assert not (tmp_path / "users").exists()


def test_posts_history_returns_all_post_visits(tmp_path: Path) -> None:
    _write_state(tmp_path, "alice")
    history_path = tmp_path / "users" / "alice" / "history.json"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        json.dumps(
            {
                "post_last_visited": {
                    "7": "2026-03-09T10:00:00+00:00",
                    "8": "2026-03-09T11:00:00+00:00",
                }
            },
            ensure_ascii=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["--config-path", str(tmp_path), "posts", "history"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["username"] == "alice"
    assert payload["post_last_visited"]["7"] == "2026-03-09T10:00:00+00:00"
    assert payload["post_last_visited"]["8"] == "2026-03-09T11:00:00+00:00"


def test_posts_history_returns_single_post_visit(tmp_path: Path) -> None:
    _write_state(tmp_path, "alice")
    history_path = tmp_path / "users" / "alice" / "history.json"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        json.dumps(
            {"post_last_visited": {"9": "2026-03-09T12:00:00+00:00"}},
            ensure_ascii=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--config-path", str(tmp_path), "posts", "history", "9"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["username"] == "alice"
    assert payload["post_id"] == 9
    assert payload["last_visited_at"] == "2026-03-09 20:00:00"


def test_posts_history_without_username_errors(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--config-path", str(tmp_path), "posts", "history"])

    assert result.exit_code != 0
    assert "Cannot determine current username. Please login first." in result.output
