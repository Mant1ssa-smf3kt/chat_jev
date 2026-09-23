#!/bin/bash
# 打包 chat-jev.app 并做成 DMG：packaging/build.sh
# 产物：dist/chat-jev.app、dist/chat-jev-<版本>-macos-<架构>.dmg
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
ARCH=$(uname -m)
export CHAT_JEV_VERSION=$VERSION

rm -rf build dist
mkdir -p build
uv run python packaging/make_icon.py build/chat-jev.icns
uv run --group dev pyinstaller --noconfirm --clean --distpath dist --workpath build packaging/chat-jev.spec

# ad-hoc 签名：没有开发者证书也能跑。系统按签名记辅助功能权限，每个新版本要重新授权一次。
codesign --force --deep --sign - dist/chat-jev.app
codesign --verify --deep --strict dist/chat-jev.app

CHAT_JEV_SELFTEST=1 dist/chat-jev.app/Contents/MacOS/chat-jev

# DMG：打开后是 chat-jev.app 和「应用程序」的快捷方式，拖过去就装好了
DMG="dist/chat-jev-${VERSION}-macos-${ARCH}.dmg"
STAGE=build/dmg
rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -R dist/chat-jev.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -quiet -volname "chat-jev ${VERSION}" -srcfolder "$STAGE" -fs HFS+ -format UDZO -ov "$DMG"
hdiutil verify -quiet "$DMG"
echo "$DMG"
