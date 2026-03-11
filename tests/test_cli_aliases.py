from pathlib import Path

from click.testing import CliRunner

from bbs_cli.cli import cli


def test_top_level_group_aliases_show_help() -> None:
    runner = CliRunner()
    aliases = ["a", "u", "b", "p", "r", "fb", "n", "h", "s"]
    for alias in aliases:
        result = runner.invoke(cli, [alias, "--help"])
        assert result.exit_code == 0, f"{alias}: {result.output}"


def test_ambiguous_prefix_shows_clear_error() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["f", "--help"])
    assert result.exit_code != 0
    assert "Too many matches" in result.output


def test_help_stays_clean_without_alias_duplication() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0, result.output
    output = result.output
    assert "  auth" in output
    assert "  users" in output
    assert "  boards" in output
    assert "  posts" in output
    assert "  favorite-boards" in output
    assert "  notifications" in output
    assert "  health" in output
    assert "  search" in output
    assert "\n  a " not in output
    assert "\n  u " not in output
    assert "\n  b " not in output
    assert "\n  p " not in output
    assert "\n  fb " not in output
    assert "\n  n " not in output
    assert "\n  h " not in output
    assert "\n  s " not in output


def test_hidden_post_alias_still_works(tmp_path: Path, monkeypatch) -> None:
    def fake_request(self, method, path, params=None, json_body=None):
        assert method == "GET"
        assert path == "/posts/12"
        return {"id": 12}

    monkeypatch.setattr("bbs_cli.client.ApiClient.request", fake_request)

    runner = CliRunner()
    result = runner.invoke(cli, ["-C", str(tmp_path), "post", "get", "12"])
    assert result.exit_code == 0, result.output


def test_search_alias_works(tmp_path: Path, monkeypatch) -> None:
    def fake_request(self, method, path, params=None, json_body=None):
        assert method == "GET"
        assert path == "/search"
        assert params == {"keyword": "python"}
        return {"keyword": "python", "posts": [], "replies": []}

    monkeypatch.setattr("bbs_cli.client.ApiClient.request", fake_request)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["-C", str(tmp_path), "s", "-k", "python"],
    )
    assert result.exit_code == 0, result.output


def test_root_short_options_and_health_alias(tmp_path: Path, monkeypatch) -> None:
    def fake_request(self, method, path, params=None, json_body=None):
        assert method == "GET"
        assert path == "/health"
        assert self.base_url == "http://127.0.0.1:60080"
        assert self.token == "token-x"
        return {"status": "ok"}

    monkeypatch.setattr("bbs_cli.client.ApiClient.request", fake_request)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["-B", "http://127.0.0.1:60080", "-T", "token-x", "-C", str(tmp_path), "-W", "5", "h", "check"],
    )
    assert result.exit_code == 0, result.output


def test_posts_create_short_tag_option(tmp_path: Path, monkeypatch) -> None:
    def fake_request(self, method, path, params=None, json_body=None):
        assert method == "POST"
        assert path == "/posts"
        assert json_body == {
            "board_id": 1,
            "title": "hello",
            "content": "world",
            "tags": ["x", "y"],
        }
        return {"id": 1}

    monkeypatch.setattr("bbs_cli.client.ApiClient.request", fake_request)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["-C", str(tmp_path), "p", "create", "-b", "1", "-t", "hello", "-c", "world", "-g", "x", "-g", "y"],
    )
    assert result.exit_code == 0, result.output
