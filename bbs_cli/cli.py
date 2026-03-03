from __future__ import annotations

import json
import sys
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import click

from .client import ApiClient, ApiError
from .config import CliConfig, ConfigStore


DEFAULT_BASE_URL = "http://127.0.0.1:60080"
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


@dataclass
class AppContext:
    client: ApiClient
    store: ConfigStore
    config: CliConfig
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


@click.group()
@click.option("--base-url", default=None, envvar="BBS_BASE_URL", help="API base URL.")
@click.option("--token", default=None, envvar="BBS_TOKEN", help="Auth token.")
@click.option(
    "--config-path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Config file path.",
)
@click.option("--timeout", default=20.0, type=float, show_default=True)
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
    cfg = store.load()
    resolved_base_url = base_url or cfg.base_url or DEFAULT_BASE_URL
    resolved_token = token or cfg.token
    app = AppContext(
        client=ApiClient(base_url=resolved_base_url, token=resolved_token, timeout=timeout),
        store=store,
        config=cfg,
        config_path=store.path,
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
@click.option("--save/--no-save", default=True, show_default=True)
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
        app.config.token = token
        app.store.save(app.config)
        result = {**result, "saved_to": str(app.config_path)}
    _emit_json(result)


@auth.command("me")
@click.pass_obj
def auth_me(app: AppContext) -> None:
    _run_request(app, "GET", "/auth/me")


@auth.command("logout")
@click.pass_obj
def auth_logout(app: AppContext) -> None:
    cfg = app.store.clear_token()
    _emit_json(
        {
            "ok": True,
            "message": "token cleared",
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


@boards.command("get")
@click.argument("board_id", type=int)
@click.pass_obj
def boards_get(app: AppContext, board_id: int) -> None:
    _run_request(app, "GET", f"/boards/{board_id}")


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
@click.option("--tags", multiple=True, help="Repeatable option.")
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
@click.option("--tags", multiple=True, help="Repeatable option.")
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


@click.group("post")
def post() -> None:
    """Alias of posts APIs."""


for _name in ("list", "get", "create", "update", "delete", "replies"):
    post.add_command(posts.commands[_name], name=_name)


cli.add_command(post)


if __name__ == "__main__":
    cli()

