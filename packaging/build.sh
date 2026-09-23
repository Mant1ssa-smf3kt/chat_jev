#!/bin/bash
# 打包 chat-jev.app 并压成 zip：packaging/build.sh
# 产物：dist/chat-jev.app、dist/chat-jev-<版本>-macos-<架构>.zip
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
ARCH=$(uname -m)
export CHAT_JEV_VERSION=$VERSION

rm -rf build dist
uv run --group dev pyinstaller --noconfirm --clean --distpath dist --workpath build packaging/chat-jev.spec

# ad-hoc 签名：没有开发者证书也能跑。系统按签名记辅助功能权限，每个新版本要重新授权一次。
codesign --force --deep --sign - dist/chat-jev.app
codesign --verify --deep --strict dist/chat-jev.app

CHAT_JEV_SELFTEST=1 dist/chat-jev.app/Contents/MacOS/chat-jev

ZIP="dist/chat-jev-${VERSION}-macos-${ARCH}.zip"
ditto -c -k --keepParent dist/chat-jev.app "$ZIP"
echo "$ZIP"
