from pathlib import Path

from bbs_cli.config import CliConfig, ConfigStore


def test_store_save_and_load_user_isolation(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path)
    store.save_user("alice", CliConfig(token="token-a", base_url="http://a"))
    store.save_user("bob", CliConfig(token="token-b", base_url="http://b"))

    alice = store.load_user("alice")
    bob = store.load_user("bob")

    assert alice.token == "token-a"
    assert alice.base_url == "http://a"
    assert bob.token == "token-b"
    assert bob.base_url == "http://b"


def test_store_set_last_username_and_load_state(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path)

    store.set_last_username("alice")
    store.set_last_username("bob")

    assert store.load_state().last_username == "bob"


def test_store_clear_user_token_only_current_user(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path)
    store.save_user("alice", CliConfig(token="token-a", base_url="http://a"))
    store.save_user("bob", CliConfig(token="token-b", base_url="http://b"))

    store.clear_user_token("bob")

    assert store.load_user("bob").token is None
    assert store.load_user("alice").token == "token-a"


def test_store_resolve_root_with_legacy_file_path(tmp_path: Path) -> None:
    legacy_path = tmp_path / "legacy" / "config.json"
    store = ConfigStore(legacy_path)

    assert store.root == legacy_path.parent


def test_store_migrate_legacy_to_user_when_user_config_absent(tmp_path: Path) -> None:
    legacy_root = tmp_path / "store"
    legacy_root.mkdir(parents=True, exist_ok=True)
    (legacy_root / "config.json").write_text(
        '{\n  "token": "legacy-token",\n  "base_url": "http://legacy"\n}\n',
        encoding="utf-8",
    )

    store = ConfigStore(legacy_root)
    migrated = store.migrate_legacy_to_user("alice")

    assert migrated is not None
    assert migrated.token == "legacy-token"
    assert migrated.base_url == "http://legacy"
    assert store.user_config_path("alice").exists()
    assert store.load_user("alice").token == "legacy-token"
