"""自动更新：定期看 GitHub 上的最新 release，有新版就下载 DMG、换掉当前的 app、重启。

只在打包好的 app 里生效。安全上靠签名把关：新 app 必须是正在运行的这个 app 信任的证书签的——
它自己的证书，加上打包时 packaging/certs.txt 里 trust 的证书（换证书交接用）——否则拒绝安装。
同一张证书也让系统把新旧版本认成同一个程序，更新后辅助功能权限不用重新授权。
ad-hoc 签名的旧版本（0.3.0 及以前）没法自动更新，只会提示去手动下载。
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable

import httpx

REPO = "Mant1ssa-smf3kt/chat_jev"
# 不走 api.github.com：未登录每个 IP 每小时只有 60 次，公司/校园网一共用一份，很容易 403。
# releases/latest 网页会 302 到 releases/tag/<最新 tag>，安装包地址按命名规则拼出来，都不受这个限制。
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"

# 换 app 的脚本：等旧进程退出 → 把新 app 挪到原位（失败就还原）→ 重新打开
SWAP = """#!/bin/sh
PID="$1"; APP="$2"; NEW="$3"
i=0
while kill -0 "$PID" 2>/dev/null && [ $i -lt 150 ]; do sleep 0.2; i=$((i+1)); done
OLD="$APP.old-$$"
if mv "$APP" "$OLD"; then
  if mv "$NEW" "$APP"; then rm -rf "$OLD"; else mv "$OLD" "$APP"; fi
fi
open "$APP"
"""


def parse_version(v: str) -> tuple[int, ...]:
    parts = []
    for p in v.strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def tag_from_redirect(location: str) -> str | None:
    """releases/latest 的 302 Location → tag 名；不是预期的地址就 None。"""
    m = re.search(r"/releases/tag/([^/?#]+)$", location)
    return m.group(1) if m else None


def asset_url(tag: str, arch: str) -> str:
    """build.sh 的 DMG 命名规则：chat-jev-<版本>-macos-<架构>.dmg"""
    return f"https://github.com/{REPO}/releases/download/{tag}/chat-jev-{tag.lstrip('vV')}-macos-{arch}.dmg"


def current_version() -> str:
    from Foundation import NSBundle
    return str(NSBundle.mainBundle().infoDictionary().get("CFBundleShortVersionString", "0"))


def app_path() -> Path:
    """正在运行的 .app（可执行文件在 chat-jev.app/Contents/MacOS/ 里）。"""
    return Path(sys.executable).resolve().parents[2]


def designated_requirement(app: Path) -> str | None:
    out = subprocess.run(["codesign", "-d", "-r-", str(app)], capture_output=True, text=True)
    for line in (out.stdout + out.stderr).splitlines():
        if line.startswith("designated => "):
            return line[len("designated => "):].strip()
    return None


def bundled_certs() -> list[str]:
    """打包进 app 的 certs.txt 里所有证书指纹（sign 和 trust 都算）。"""
    path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent / "packaging")) / "certs.txt"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in ("sign", "trust") and re.fullmatch(r"[0-9a-fA-F]{40}", parts[1]):
            out.append(parts[1].lower())
    return out


def trust_requirement(own: str, extra: list[str]) -> str:
    """校验新包用的签名要求：同一个 bundle id，证书是自己的或者 extra 里的任意一张。"""
    ident = re.search(r'identifier "([^"]+)"', own)
    leaf = re.search(r'certificate leaf = H"([0-9a-fA-F]{40})"', own)
    if ident is None or leaf is None:
        return own                                   # 看不懂的格式就只认自己
    hashes = list(dict.fromkeys([leaf.group(1).lower(), *extra]))
    if len(hashes) == 1:
        return own
    alts = " or ".join(f'certificate leaf = H"{h}"' for h in hashes)
    return f'identifier "{ident.group(1)}" and ({alts})'


class UpdateError(Exception):
    pass


class Updater:
    """check() 在后台线程跑；结果通过 notify(title, detail) 回到调用方（调用方负责切回主线程）。"""

    def __init__(self, notify: Callable[[str, str], None], quit_app: Callable[[], None]) -> None:
        self.notify = notify
        self.quit_app = quit_app
        self._busy = threading.Lock()

    def check_async(self, manual: bool = False) -> None:
        threading.Thread(target=self.check, args=(manual,), daemon=True).start()

    def check(self, manual: bool = False) -> None:
        if not self._busy.acquire(blocking=False):
            return                                   # 上一次还没跑完
        try:
            self._check(manual)
        except (UpdateError, httpx.HTTPError, OSError, subprocess.SubprocessError) as e:
            print(f"[update] {e}", file=sys.stderr)
            if manual:
                self.notify("检查更新失败", str(e)[:80])
        finally:
            self._busy.release()

    def _check(self, manual: bool) -> None:
        cur = current_version()
        with httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": "chat-jev"}) as http:
            r = http.get(RELEASES_PAGE, follow_redirects=False)
            latest = tag_from_redirect(r.headers.get("location", "")) if r.is_redirect else None
            if latest is None:
                raise UpdateError(f"GitHub 返回 {r.status_code}，没找到最新版本")
            if not is_newer(latest, cur):
                print(f"[update] 已是最新 {cur}（GitHub 上是 {latest}）", file=sys.stderr)
                if manual:
                    self.notify("已是最新版本", f"当前 {cur}")
                return
            url = asset_url(latest, platform.machine())

            app = app_path()
            req = designated_requirement(app)
            if req is None or "cdhash" in req:
                self.notify(f"有新版本 {latest}", "当前版本不支持自动更新，请到 GitHub 手动下载一次")
                print(f"[update] 当前 app 不是证书签名，不能自动更新：{RELEASES_PAGE}", file=sys.stderr)
                return
            if not os.access(app.parent, os.W_OK):
                self.notify(f"有新版本 {latest}", f"没有权限写 {app.parent}，请手动更新")
                return

            print(f"[update] {cur} → {latest}，下载 {url}", file=sys.stderr)
            req = trust_requirement(req, bundled_certs())
            self.notify(f"正在更新到 {latest}", "下载中，完成后会自动重启")
            with tempfile.TemporaryDirectory(prefix="chat-jev-update-") as tmp:
                dmg = Path(tmp) / "update.dmg"
                with http.stream("GET", url) as r:
                    if r.status_code == 404:
                        raise UpdateError(f"{latest} 没有 {platform.machine()} 的安装包")
                    r.raise_for_status()
                    with open(dmg, "wb") as f:
                        for chunk in r.iter_bytes(1 << 16):
                            f.write(chunk)
                staged = self._stage(dmg, Path(tmp) / "mnt", app)
        self._verify(staged, req)
        print(f"[update] 已校验签名，重启换成 {latest}", file=sys.stderr)
        self.notify(f"已下载 {latest}", "马上重启…")
        self._swap_and_quit(app, staged)

    def _stage(self, dmg: Path, mnt: Path, app: Path) -> Path:
        """挂载 DMG，把里面的 app 拷到当前 app 旁边（同一个磁盘，最后一步 mv 才是原子的）。"""
        staged = app.parent / f".{app.stem}-update.app"
        subprocess.run(["rm", "-rf", str(staged)], check=True)
        mnt.mkdir()
        subprocess.run(["hdiutil", "attach", "-quiet", "-nobrowse", "-readonly", "-mountpoint", str(mnt), str(dmg)],
                       check=True)
        try:
            src = mnt / app.name
            if not src.is_dir():
                raise UpdateError("安装包里没有 chat-jev.app")
            subprocess.run(["ditto", str(src), str(staged)], check=True)
        finally:
            subprocess.run(["hdiutil", "detach", "-quiet", str(mnt)], check=False)
        return staged

    def _verify(self, staged: Path, req: str) -> None:
        r = subprocess.run(["codesign", "--verify", "--deep", "--strict", f"-R={req}", str(staged)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            subprocess.run(["rm", "-rf", str(staged)], check=False)
            raise UpdateError("新版本的签名和当前不一致，拒绝安装：" + r.stderr.strip()[:200])

    def _swap_and_quit(self, app: Path, staged: Path) -> None:
        script = Path(tempfile.mkstemp(prefix="chat-jev-swap-", suffix=".sh")[1])
        script.write_text(SWAP)
        subprocess.Popen(["/bin/sh", str(script), str(os.getpid()), str(app), str(staged)],
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.quit_app()
