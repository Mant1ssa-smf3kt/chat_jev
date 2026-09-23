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


def test_trust_requirement_adds_extra_certs():
    from chat_jev.updater import trust_requirement
    own = 'identifier "io.x" and certificate leaf = H"' + "a" * 40 + '"'
    assert trust_requirement(own, []) == own
    assert trust_requirement(own, ["a" * 40]) == own                # 自己那张不重复
    req = trust_requirement(own, ["b" * 40])
    assert req == f'identifier "io.x" and (certificate leaf = H"{"a" * 40}" or certificate leaf = H"{"b" * 40}")'
    assert trust_requirement('cdhash H"abc"', ["b" * 40]) == 'cdhash H"abc"'      # ad-hoc：不动


def test_bundled_certs_reads_repo_file():
    from chat_jev.updater import bundled_certs
    assert bundled_certs()[0] == "ddee9fa1fe54ef299db1ac233e3369d5dd97f31e"
