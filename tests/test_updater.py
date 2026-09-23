"""更新器里不碰系统的那部分：版本比较、挑安装包。"""

from chat_jev.updater import is_newer, parse_version, pick_asset


def test_version_compare():
    assert parse_version("v0.3.1") == (0, 3, 1)
    assert is_newer("v0.3.1", "0.3.0") and is_newer("v0.10.0", "0.9.9")
    assert not is_newer("v0.3.0", "0.3.0") and not is_newer("v0.2.9", "0.3.0")


def test_pick_asset_matches_arch():
    rel = {"assets": [{"name": "chat-jev-0.3.1-macos-x86_64.dmg", "browser_download_url": "x86"},
                      {"name": "chat-jev-0.3.1-macos-arm64.dmg", "browser_download_url": "arm"},
                      {"name": "chat-jev-0.3.1-macos-arm64.zip", "browser_download_url": "zip"}]}
    assert pick_asset(rel, "arm64") == "arm"
    assert pick_asset(rel, "ppc") is None
