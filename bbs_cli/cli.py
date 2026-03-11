from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import click

from .client import ApiClient, ApiError
from .config import CliConfig, ConfigStore


DEFAULT_BASE_URL = "http://127.0.0.1:60080"
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class AliasedGroup(click.Group):
    """Resolve top-level commands by unique prefix while keeping help clean."""

    hidden_aliases = {"post": "posts"}

    @staticmethod
    def _command_keys(name: str) -> tuple[str, ...]:
        parts = name.split("-")
        compact = "".join(parts)
        initials = "".join(part[:1] for part in parts if part)
        return (name, compact, initials)

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        command = super().get_command(ctx, cmd_name)
        if command is not None:
            return command

        alias_target = self.hidden_aliases.get(cmd_name)
        if alias_target is not None:
            return super().get_command(ctx, alias_target)

        matches: list[str] = []
        for name in self.list_commands(ctx):
            if any(key.startswith(cmd_name) for key in self._command_keys(name)):
                matches.append(name)
        if len(matches) == 1:
            return super().get_command(ctx, matches[0])
        if len(matches) > 1:
            ctx.fail(f"Too many matches: {', '.join(matches)}")
        return None


@dataclass
class AppContext:
    client: ApiClient
    store: ConfigStore
    config: CliConfig
    username: str | None
    config_path: Path


def _clean_dict(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None}


def _format_datetime_string(value: str) -> str:
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SHANGHAI_TZ)
    dt = dt.astimezone(SHANGHAI_TZ)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _format_output_value(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {k: _format_output_value(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_format_output_value(item) for item in value]
    if isinstance(value, str) and key is not None and key.endswith("_at"):
        try:
            return _format_datetime_string(value)
        except ValueError:
            return value
    return value


def _emit_json(data: Any) -> None:
    formatted = _format_output_value(data)
    click.echo(json.dumps(formatted, ensure_ascii=False, indent=2))


def _parse_json_input(json_input: str) -> dict[str, Any]:
    if json_input.startswith("@"):
        source = json_input[1:]
        if source == "-":
            raw = sys.stdin.read()
        else:
            try:
                raw = Path(source).read_text(encoding="utf-8")
            except OSError as exc:
                raise click.UsageError(f"Cannot read JSON file: {source}") from exc
    else:
        raw = json_input

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise click.UsageError(f"Invalid --json payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise click.UsageError("--json payload must be a JSON object.")
    return payload


def _read_stdin_content() -> str | None:
    if sys.stdin.isatty():
        return None
    return sys.stdin.read()


def _record_post_visit(app: AppContext, post_id: int) -> None:
    if app.username is None:
        return
    visited_at = datetime.now(tz=timezone.utc).isoformat()
    app.store.set_post_last_visited(app.username, post_id, visited_at)


def _run_request(
    app: AppContext,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> None:
    try:
        result = app.client.request(
            method,
            path,
            params=_clean_dict(params or {}),
            json_body=_clean_dict(json_body or {}),
        )
        _emit_json(result)
    except ApiError as exc:
        _emit_json(
            {
                "ok": False,
                "status_code": exc.status_code,
                "error": exc.message,
                "detail": exc.detail,
            }
        )
        raise click.Abort() from exc


def _resolve_user_id(app: AppContext, user_id: int | None) -> int:
    if user_id is not None:
        return user_id
    try:
        me = app.client.request("GET", "/auth/me")
    except ApiError as exc:
        raise click.UsageError(
            "Cannot determine current user. Please login first or pass --user-id."
        ) from exc
    resolved = me.get("id") if isinstance(me, dict) else None
    if not isinstance(resolved, int):
        raise click.UsageError("Unable to resolve user id from /auth/me response.")
    return resolved


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def _notification_text(notification: dict[str, Any]) -> str:
    return " ".join(
        str(notification.get(key, "")).lower()
        for key in ("event_type", "message", "post_title")
    )


def _is_new_board_notification(notification: dict[str, Any]) -> bool:
    text = _notification_text(notification)
    board_words = ("board", "版块", "板块")
    create_words = ("new", "create", "created", "add", "新增", "创建")
    post_words = ("post", "帖子")
    return _contains_any(text, board_words) and _contains_any(text, create_words) and not _contains_any(
        text, post_words
    )


def _is_post_activity_notification(notification: dict[str, Any]) -> bool:
    text = _notification_text(notification)
    activity_words = ("reply", "comment", "update", "edit", "回复", "评论", "修改", "更新")
    return _contains_any(text, activity_words)


def _is_board_new_post_notification(notification: dict[str, Any]) -> bool:
    text = _notification_text(notification)
    board_words = ("board", "版块", "板块", "关注板块", "关注的板块")
    post_words = ("post", "帖子")
    create_words = ("new", "create", "created", "新增", "发布", "新帖")
    return _contains_any(text, board_words) and _contains_any(text, post_words) and _contains_any(
        text, create_words
    )


def _list_notifications_page(app: AppContext, page: int, size: int) -> dict[str, Any]:
    result = app.client.request(
        "GET",
        "/notifications",
        params={"page": page, "size": size},
    )
    if not isinstance(result, dict):
        raise ApiError(status_code=0, detail=result, message="Invalid notifications response")
    return result


def _list_all_notifications(app: AppContext, size: int = 100) -> list[dict[str, Any]]:
    page = 1
    total_pages = 1
    collected: list[dict[str, Any]] = []
    while page <= total_pages:
        payload = _list_notifications_page(app, page=page, size=size)
        items = payload.get("items")
        if isinstance(items, list):
            collected.extend(item for item in items if isinstance(item, dict))
        tp = payload.get("total_pages")
        if isinstance(tp, int) and tp > 0:
            total_pages = tp
        else:
            break
        page += 1
    return collected


def _get_unread_notification_count(app: AppContext) -> int:
    payload = app.client.request("GET", "/notifications/unread-count")
    if isinstance(payload, dict):
        value = payload.get("unread_count")
        if isinstance(value, int):
            return value
    return 0


def _mark_notification_read(app: AppContext, notification_id: int) -> None:
    app.client.request("PUT", f"/notifications/{notification_id}/read")


def _safe_auto_mark_read(app: AppContext, predicate: Any) -> int:
    if not app.client.token:
        return 0
    try:
        notifications = _list_all_notifications(app)
    except ApiError:
        return 0

    marked = 0
    for notification in notifications:
        if notification.get("is_read") is True:
            continue
        if not predicate(notification):
            continue
        notification_id = notification.get("id")
        if not isinstance(notification_id, int):
            continue
        try:
            _mark_notification_read(app, notification_id)
            marked += 1
        except ApiError:
            continue
    return marked


def _auto_mark_post_notifications_read(app: AppContext, post_id: int) -> None:
    def _predicate(notification: dict[str, Any]) -> bool:
        noti_post_id = notification.get("post_id")
        if not isinstance(noti_post_id, int) or noti_post_id != post_id:
            return False
        return _is_post_activity_notification(notification) or _is_board_new_post_notification(
            notification
        )

    _safe_auto_mark_read(app, _predicate)


def _auto_mark_new_board_notifications_read(app: AppContext) -> None:
    _safe_auto_mark_read(app, _is_new_board_notification)


def _auto_mark_board_new_post_notifications_read(app: AppContext, board_id: int) -> None:
    post_board_cache: dict[int, int | None] = {}

    def _post_board_id(post_id: int) -> int | None:
        if post_id in post_board_cache:
            return post_board_cache[post_id]
        try:
            payload = app.client.request("GET", f"/posts/{post_id}")
        except ApiError:
            post_board_cache[post_id] = None
            return None
        result = payload.get("board_id") if isinstance(payload, dict) else None
        post_board_cache[post_id] = result if isinstance(result, int) else None
        return post_board_cache[post_id]

    def _predicate(notification: dict[str, Any]) -> bool:
        if not _is_board_new_post_notification(notification):
            return False
        post_id = notification.get("post_id")
        if not isinstance(post_id, int):
            return False
        return _post_board_id(post_id) == board_id

    _safe_auto_mark_read(app, _predicate)


@click.group(cls=AliasedGroup)
@click.option("-B", "--base-url", default=None, envvar="BBS_BASE_URL", help="API base URL.")
@click.option("-T", "--token", default=None, envvar="BBS_TOKEN", help="Auth token.")
@click.option(
    "-C",
    "--config-path",
    type=click.Path(path_type=Path, file_okay=True, dir_okay=True),
    default=None,
    help="Storage root path (or legacy config file path).",
)
@click.option("-W", "--timeout", default=20.0, type=float, show_default=True)
@click.pass_context
def cli(
    ctx: click.Context,
    base_url: str | None,
    token: str | None,
    config_path: Path | None,
    timeout: float,
) -> None:
    """BBS command line client."""
    store = ConfigStore(config_path)
    state = store.load_state()
    current_username = state.last_username
    cfg = CliConfig()
    if current_username is not None:
        user_cfg_path = store.user_config_path(current_username)
        if not user_cfg_path.exists():
            migrated = store.migrate_legacy_to_user(current_username)
            if migrated is not None:
                cfg = migrated
            else:
                cfg = store.load_user(current_username)
        else:
            cfg = store.load_user(current_username)
    elif store.has_legacy_config():
        # Read-only fallback for pre-migration installs.
        cfg = store.load_legacy()

    resolved_base_url = base_url or cfg.base_url or DEFAULT_BASE_URL
    resolved_token = token or cfg.token
    resolved_config_path = (
        store.user_config_path(current_username) if current_username is not None else store.path
    )
    app = AppContext(
        client=ApiClient(base_url=resolved_base_url, token=resolved_token, timeout=timeout),
        store=store,
        config=cfg,
        username=current_username,
        config_path=resolved_config_path,
    )
    ctx.obj = app


@cli.group()
def health() -> None:
    """Health APIs."""


@health.command("check")
@click.pass_obj
def health_check(app: AppContext) -> None:
    _run_request(app, "GET", "/health")


@cli.group()
def auth() -> None:
    """Authentication APIs."""


@auth.command("register")
@click.option("-u", "--username", required=True)
@click.option("-p", "--password", required=True)
@click.option("-n", "--nickname", required=True)
@click.option("-b", "--bio", default="")
@click.pass_obj
def auth_register(
    app: AppContext,
    username: str,
    password: str,
    nickname: str,
    bio: str,
) -> None:
    _run_request(
        app,
        "POST",
        "/auth/register",
        json_body={
            "username": username,
            "password": password,
            "nickname": nickname,
            "bio": bio,
        },
    )


@auth.command("login")
@click.option("-u", "--username", required=True)
@click.option("-p", "--password", required=True)
@click.option("-S", "--save/--no-save", default=True, show_default=True)
@click.pass_obj
def auth_login(app: AppContext, username: str, password: str, save: bool) -> None:
    try:
        result = app.client.request(
            "POST",
            "/auth/login",
            json_body={"username": username, "password": password},
        )
    except ApiError as exc:
        _emit_json(
            {
                "ok": False,
                "status_code": exc.status_code,
                "error": exc.message,
                "detail": exc.detail,
            }
        )
        raise click.Abort() from exc

    token = result.get("token")
    if save and token:
        cfg = app.store.load_user(username)
        cfg.token = token
        app.store.save_user(username, cfg)
        app.store.set_last_username(username)
        app.config = cfg
        app.username = username
        app.config_path = app.store.user_config_path(username)
        result = {**result, "saved_to": str(app.config_path)}
    _emit_json(result)


@auth.command("me")
@click.pass_obj
def auth_me(app: AppContext) -> None:
    _run_request(app, "GET", "/auth/me")


@auth.command("logout")
@click.pass_obj
def auth_logout(app: AppContext) -> None:
    if app.username is None:
        raise click.UsageError("Cannot determine current username. Please login first.")
    cfg = app.store.clear_user_token(app.username)
    app.config = cfg
    app.config_path = app.store.user_config_path(app.username)
    _emit_json(
        {
            "ok": True,
            "message": "token cleared",
            "username": app.username,
            "config_path": str(app.config_path),
            "base_url": cfg.base_url,
        }
    )


@cli.group()
def users() -> None:
    """Users APIs."""


@users.command("get")
@click.argument("user_id", type=int, required=False)
@click.pass_obj
def users_get(app: AppContext, user_id: int | None) -> None:
    resolved_user_id = _resolve_user_id(app, user_id)
    _run_request(app, "GET", f"/users/{resolved_user_id}")


@users.command("list")
@click.option("-p", "--page", default=1, show_default=True, type=int)
@click.option("-s", "--size", default=10, show_default=True, type=int)
@click.pass_obj
def users_list(app: AppContext, page: int, size: int) -> None:
    _run_request(app, "GET", "/users", params={"page": page, "size": size})


@cli.group()
def boards() -> None:
    """Boards APIs."""


@boards.command("list")
@click.pass_obj
def boards_list(app: AppContext) -> None:
    _run_request(app, "GET", "/boards")
    _auto_mark_new_board_notifications_read(app)


@boards.command("get")
@click.argument("board_id", type=int)
@click.pass_obj
def boards_get(app: AppContext, board_id: int) -> None:
    _run_request(app, "GET", f"/boards/{board_id}")
    _auto_mark_board_new_post_notifications_read(app, board_id)


@boards.command("create")
@click.option("-n", "--name", required=True)
@click.option("-d", "--description", default="")
@click.pass_obj
def boards_create(app: AppContext, name: str, description: str) -> None:
    _run_request(
        app,
        "POST",
        "/boards",
        json_body={"name": name, "description": description},
    )


@cli.group()
def posts() -> None:
    """Posts APIs."""


@posts.command("list")
@click.option("-p", "--page", default=1, show_default=True, type=int)
@click.option("-s", "--size", default=10, show_default=True, type=int)
@click.option("-b", "--board-id", type=int, default=None)
@click.option("-k", "--keyword", default=None)
@click.pass_obj
def posts_list(
    app: AppContext,
    page: int,
    size: int,
    board_id: int | None,
    keyword: str | None,
) -> None:
    _run_request(
        app,
        "GET",
        "/posts",
        params={"page": page, "size": size, "board_id": board_id, "keyword": keyword},
    )


@posts.command("get")
@click.argument("post_id", type=int)
@click.pass_obj
def posts_get(app: AppContext, post_id: int) -> None:
    _run_request(app, "GET", f"/posts/{post_id}")
    _auto_mark_post_notifications_read(app, post_id)
    _record_post_visit(app, post_id)


@posts.command("history")
@click.argument("post_id", type=int, required=False)
@click.pass_obj
def posts_history(app: AppContext, post_id: int | None) -> None:
    if app.username is None:
        raise click.UsageError("Cannot determine current username. Please login first.")

    history = app.store.load_user_history(app.username).post_last_visited
    if post_id is None:
        _emit_json({"username": app.username, "post_last_visited": history})
        return

    key = str(post_id)
    _emit_json(
        {
            "username": app.username,
            "post_id": post_id,
            "last_visited_at": history.get(key),
        }
    )


@posts.command("create")
@click.option("-b", "--board-id", type=int, default=None)
@click.option("-t", "--title", default=None)
@click.option("-c", "--content", default=None)
@click.option(
    "-j",
    "--json",
    "json_input",
    default=None,
    help="Raw JSON body string, @file.json, or @- (stdin).",
)
@click.option("-g", "--tags", multiple=True, help="Repeatable option.")
@click.pass_obj
def posts_create(
    app: AppContext,
    board_id: int | None,
    title: str | None,
    content: str | None,
    json_input: str | None,
    tags: tuple[str, ...],
) -> None:
    if json_input is not None:
        payload = _parse_json_input(json_input)
        _run_request(app, "POST", "/posts", json_body=payload)
        return

    if content is None:
        content = _read_stdin_content()
    if content is None or content == "":
        raise click.UsageError("Provide --content, stdin content, or --json.")
    if board_id is None or title is None:
        raise click.UsageError("Provide --board-id and --title, or use --json.")

    _run_request(
        app,
        "POST",
        "/posts",
        json_body={
            "board_id": board_id,
            "title": title,
            "content": content,
            "tags": list(tags),
        },
    )


@posts.command("update")
@click.argument("post_id", type=int)
@click.option("-t", "--title", default=None)
@click.option("-c", "--content", default=None)
@click.option("-g", "--tags", multiple=True, help="Repeatable option.")
@click.pass_obj
def posts_update(
    app: AppContext,
    post_id: int,
    title: str | None,
    content: str | None,
    tags: tuple[str, ...],
) -> None:
    tags_value: list[str] | None = list(tags) if tags else None
    if title is None and content is None and tags_value is None:
        raise click.UsageError("At least one of --title/--content/--tags is required.")
    _run_request(
        app,
        "PUT",
        f"/posts/{post_id}",
        json_body={"title": title, "content": content, "tags": tags_value},
    )


@posts.command("delete")
@click.argument("post_id", type=int)
@click.pass_obj
def posts_delete(app: AppContext, post_id: int) -> None:
    _run_request(app, "DELETE", f"/posts/{post_id}")


@posts.group("replies")
def posts_replies() -> None:
    """Replies under posts."""


@posts_replies.command("list")
@click.argument("post_id", type=int)
@click.option("-p", "--page", default=1, show_default=True, type=int)
@click.option("-s", "--size", default=10, show_default=True, type=int)
@click.pass_obj
def posts_replies_list(app: AppContext, post_id: int, page: int, size: int) -> None:
    _run_request(
        app,
        "GET",
        f"/posts/{post_id}/replies",
        params={"page": page, "size": size},
    )
    _auto_mark_post_notifications_read(app, post_id)
    _record_post_visit(app, post_id)


@posts_replies.command("create")
@click.argument("post_id", type=int)
@click.option("-c", "--content", required=True)
@click.pass_obj
def posts_replies_create(app: AppContext, post_id: int, content: str) -> None:
    _run_request(
        app,
        "POST",
        f"/posts/{post_id}/replies",
        json_body={"content": content},
    )


@cli.group()
def replies() -> None:
    """Replies APIs."""


@replies.command("update")
@click.argument("reply_id", type=int)
@click.option("-c", "--content", required=True)
@click.pass_obj
def replies_update(app: AppContext, reply_id: int, content: str) -> None:
    _run_request(
        app,
        "PUT",
        f"/replies/{reply_id}",
        json_body={"content": content},
    )


@replies.command("delete")
@click.argument("reply_id", type=int)
@click.pass_obj
def replies_delete(app: AppContext, reply_id: int) -> None:
    _run_request(app, "DELETE", f"/replies/{reply_id}")


@cli.group()
def favorites() -> None:
    """Post favorites APIs."""


@favorites.command("add")
@click.option("-i", "--post-id", required=True, type=int)
@click.pass_obj
def favorites_add(app: AppContext, post_id: int) -> None:
    _run_request(app, "POST", "/favorites", json_body={"post_id": post_id})


@favorites.command("remove")
@click.option("-i", "--post-id", required=True, type=int)
@click.pass_obj
def favorites_remove(app: AppContext, post_id: int) -> None:
    _run_request(app, "DELETE", "/favorites", params={"post_id": post_id})


@favorites.command("list")
@click.option("-u", "--user-id", required=False, type=int, default=None)
@click.option("-p", "--page", default=1, show_default=True, type=int)
@click.option("-s", "--size", default=10, show_default=True, type=int)
@click.pass_obj
def favorites_list(app: AppContext, user_id: int | None, page: int, size: int) -> None:
    resolved_user_id = _resolve_user_id(app, user_id)
    _run_request(
        app,
        "GET",
        "/favorites",
        params={"user_id": resolved_user_id, "page": page, "size": size},
    )


@cli.group("favorite-boards")
def favorite_boards() -> None:
    """Board favorites APIs."""


@favorite_boards.command("add")
@click.option("-b", "--board-id", required=True, type=int)
@click.pass_obj
def favorite_boards_add(app: AppContext, board_id: int) -> None:
    _run_request(app, "POST", "/favorite-boards", json_body={"board_id": board_id})


@favorite_boards.command("remove")
@click.option("-b", "--board-id", required=True, type=int)
@click.pass_obj
def favorite_boards_remove(app: AppContext, board_id: int) -> None:
    _run_request(app, "DELETE", "/favorite-boards", params={"board_id": board_id})


@favorite_boards.command("list")
@click.option("-u", "--user-id", required=False, type=int, default=None)
@click.option("-p", "--page", default=1, show_default=True, type=int)
@click.option("-s", "--size", default=10, show_default=True, type=int)
@click.pass_obj
def favorite_boards_list(app: AppContext, user_id: int | None, page: int, size: int) -> None:
    resolved_user_id = _resolve_user_id(app, user_id)
    _run_request(
        app,
        "GET",
        "/favorite-boards",
        params={"user_id": resolved_user_id, "page": page, "size": size},
    )


@cli.group()
def notifications() -> None:
    """Notifications APIs."""


@notifications.command("list")
@click.option("-p", "--page", default=1, show_default=True, type=int)
@click.option("-s", "--size", default=10, show_default=True, type=int)
@click.pass_obj
def notifications_list(app: AppContext, page: int, size: int) -> None:
    try:
        payload = _list_notifications_page(app, page=page, size=size)
        unread_count = _get_unread_notification_count(app)
    except ApiError as exc:
        _emit_json(
            {
                "ok": False,
                "status_code": exc.status_code,
                "error": exc.message,
                "detail": exc.detail,
            }
        )
        raise click.Abort() from exc

    payload["unread_count"] = unread_count
    _emit_json(payload)


@notifications.command("read-all")
@click.pass_obj
def notifications_read_all(app: AppContext) -> None:
    _run_request(app, "PUT", "/notifications/read-all")


@cli.command("search")
@click.option("-k", "--keyword", required=True)
@click.pass_obj
def search(app: AppContext, keyword: str) -> None:
    _run_request(app, "GET", "/search", params={"keyword": keyword})


if __name__ == "__main__":
    cli()

