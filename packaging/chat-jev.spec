# PyInstaller 配置：打出 dist/chat-jev.app。用 packaging/build.sh 跑，不要直接调。
import os

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
VERSION = os.environ["CHAT_JEV_VERSION"]

a = Analysis(
    [os.path.join(SPECPATH, "entry.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, ".env.example"), "."),
           (os.path.join(ROOT, "packaging", "certs.txt"), ".")],     # 自动更新信任哪些证书
    hiddenimports=collect_submodules("chat_jev"),
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="chat-jev", console=False,
          target_arch=os.environ.get("CHAT_JEV_ARCH"))
coll = COLLECT(exe, a.binaries, a.datas, name="chat-jev")
app = BUNDLE(
    coll,
    name="chat-jev.app",
    bundle_identifier="io.github.mant1ssa.chat-jev",
    icon=os.path.join(ROOT, "build", "chat-jev.icns"),
    version=VERSION,
    info_plist={
        "CFBundleName": "chat-jev",
        "CFBundleDisplayName": "chat-jev",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSUIElement": True,                      # 不进 Dock，只有菜单栏图标
        "LSMinimumSystemVersion": "14.0",
        "NSHumanReadableCopyright": "chat-jev",
    },
)
