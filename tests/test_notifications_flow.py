import json
from pathlib import Path

from click.testing import CliRunner

from bbs_cli.cli import cli


def _write_user_context(root: Path, username: str = "alice", token: str = "token-a") -> None:
    (root / "state.json").write_text(
        json.dumps({"last_username": username}, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    user_dir = root / "users" / username
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "config.json").write_text(
        json.dumps({"token": token, "base_url": None}, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def test_notifications_list_includes_unread_count_without_marking_read(
    tmp_path: Path, monkeypatch
) -> None:
    _write_user_context(tmp_path)
    calls: list[tuple[str, str]] = []

    def fake_request(self, method, path, params=None, json_body=None):
        calls.append((method, path))
        if method == "GET" and path == "/notifications":
            assert params == {"page": 1, "size": 10}
            return {"items": [{"id": 1, "is_read": False}], "page": 1, "size": 10, "total_pages": 1}
        if method == "GET" and path == "/notifications/unread-count":
            return {"unread_count": 7}
        raise AssertionError(f"Unexpected call: {method} {path}")

    monkeypatch.setattr("bbs_cli.client.ApiClient.request", fake_request)

    runner = CliRunner()
    result = runner.invoke(cli, ["--config-path", str(tmp_path), "notifications", "list"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["unread_count"] == 7
    assert ("PUT", "/notifications/1/read") not in calls


def test_posts_get_auto_marks_matching_post_notifications(tmp_path: Path, monkeypatch) -> None:
    _write_user_context(tmp_path)
    read_ids: list[int] = []

    def fake_request(self, method, path, params=None, json_body=None):
        if method == "GET" and path == "/posts/10":
            return {"id": 10, "board_id": 3, "title": "post 10"}
        if method == "GET" and path == "/notifications":
            assert params == {"page": 1, "size": 100}
            return {
                "items": [
                    {"id": 1, "post_id": 10, "event_type": "reply_created", "message": "new reply", "is_read": False},
                    {"id": 2, "post_id": 11, "event_type": "reply_created", "message": "new reply", "is_read": False},
                    {"id": 3, "post_id": 10, "event_type": "reply_created", "message": "new reply", "is_read": True},
                ],
                "page": 1,
                "size": 100,
                "total_pages": 1,
            }
        if method == "PUT" and path.startswith("/notifications/") and path.endswith("/read"):
            read_ids.append(int(path.split("/")[2]))
            return {"ok": True}
        raise AssertionError(f"Unexpected call: {method} {path}")

    monkeypatch.setattr("bbs_cli.client.ApiClient.request", fake_request)

    runner = CliRunner()
    result = runner.invoke(cli, ["--config-path", str(tmp_path), "posts", "get", "10"])

    assert result.exit_code == 0, result.output
    assert read_ids == [1]


def test_posts_replies_list_auto_marks_matching_post_notifications(
    tmp_path: Path, monkeypatch
) -> None:
    _write_user_context(tmp_path)
    read_ids: list[int] = []

    def fake_request(self, method, path, params=None, json_body=None):
        if method == "GET" and path == "/posts/9/replies":
            return {"items": [], "page": 1, "size": 10, "total_pages": 0}
        if method == "GET" and path == "/notifications":
            return {
                "items": [
                    {"id": 7, "post_id": 9, "event_type": "post_updated", "message": "帖子更新", "is_read": False},
                    {"id": 8, "post_id": 8, "event_type": "post_updated", "message": "帖子更新", "is_read": False},
                ],
                "page": 1,
                "size": 100,
                "total_pages": 1,
            }
        if method == "PUT" and path.startswith("/notifications/") and path.endswith("/read"):
            read_ids.append(int(path.split("/")[2]))
            return {"ok": True}
        raise AssertionError(f"Unexpected call: {method} {path}")

    monkeypatch.setattr("bbs_cli.client.ApiClient.request", fake_request)

    runner = CliRunner()
    result = runner.invoke(cli, ["--config-path", str(tmp_path), "posts", "replies", "list", "9"])

    assert result.exit_code == 0, result.output
    assert read_ids == [7]


def test_boards_list_auto_marks_only_new_board_notifications(
    tmp_path: Path, monkeypatch
) -> None:
    _write_user_context(tmp_path)
    read_ids: list[int] = []

    def fake_request(self, method, path, params=None, json_body=None):
        if method == "GET" and path == "/boards":
            return []
        if method == "GET" and path == "/notifications":
            return {
                "items": [
                    {"id": 10, "post_id": 0, "event_type": "board_created", "message": "新增板块", "is_read": False},
                    {"id": 11, "post_id": 12, "event_type": "post_created", "message": "板块下有新帖子", "is_read": False},
                ],
                "page": 1,
                "size": 100,
                "total_pages": 1,
            }
        if method == "PUT" and path.startswith("/notifications/") and path.endswith("/read"):
            read_ids.append(int(path.split("/")[2]))
            return {"ok": True}
        raise AssertionError(f"Unexpected call: {method} {path}")

    monkeypatch.setattr("bbs_cli.client.ApiClient.request", fake_request)

    runner = CliRunner()
    result = runner.invoke(cli, ["--config-path", str(tmp_path), "boards", "list"])

    assert result.exit_code == 0, result.output
    assert read_ids == [10]


def test_boards_get_auto_marks_new_post_notifications_in_target_board(
    tmp_path: Path, monkeypatch
) -> None:
    _write_user_context(tmp_path)
    read_ids: list[int] = []
    board_lookup_calls: list[str] = []

    def fake_request(self, method, path, params=None, json_body=None):
        if method == "GET" and path == "/boards/2":
            return {"id": 2, "name": "Dev"}
        if method == "GET" and path == "/notifications":
            return {
                "items": [
                    {"id": 21, "post_id": 101, "event_type": "post_created", "message": "关注板块有新帖子", "is_read": False},
                    {"id": 22, "post_id": 202, "event_type": "post_created", "message": "关注板块有新帖子", "is_read": False},
                ],
                "page": 1,
                "size": 100,
                "total_pages": 1,
            }
        if method == "GET" and path in ("/posts/101", "/posts/202"):
            board_lookup_calls.append(path)
            return {"id": int(path.split("/")[-1]), "board_id": 2 if path.endswith("101") else 3}
        if method == "PUT" and path.startswith("/notifications/") and path.endswith("/read"):
            read_ids.append(int(path.split("/")[2]))
            return {"ok": True}
        raise AssertionError(f"Unexpected call: {method} {path}")

    monkeypatch.setattr("bbs_cli.client.ApiClient.request", fake_request)

    runner = CliRunner()
    result = runner.invoke(cli, ["--config-path", str(tmp_path), "boards", "get", "2"])

    assert result.exit_code == 0, result.output
    assert set(board_lookup_calls) == {"/posts/101", "/posts/202"}
    assert read_ids == [21]
