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

# 用固定的自签名证书签名（不是 Apple 的证书，所以仍然没公证）。
# 系统按「bundle id + 证书」认这个 app：换版本不用重新给辅助功能权限，自动更新也靠它校验新包是不是自己人打的。
# packaging/certs.txt 里的 sign 行钉死了该用哪张证书：对不上就停，绝不悄悄换证书（换了已装的 app 就收不到更新）。
. packaging/signing.sh
SIGN_DIR="${CHAT_JEV_SIGN_DIR:-$HOME/.chat-jev-signing}"
KEYCHAIN="$SIGN_DIR/signing.keychain-db"
PINNED=$(certs_sign || true)
if [ ! -f "$KEYCHAIN" ]; then
  if [ -n "$PINNED" ]; then
    echo "✗ 找不到签名证书 ${SIGN_DIR}（应该是指纹 $PINNED 的那张）。" >&2
    echo "  从备份恢复这个目录再打包。证书确实丢了、要换新的，看 README「签名证书」。" >&2
    exit 1
  fi
  echo "第一次打包，生成签名证书 → $SIGN_DIR"
  create_identity "$SIGN_DIR"
fi
HASH=$(identity_hash "$SIGN_DIR")
if [ -z "$PINNED" ]; then
  printf '# 签名证书指纹（SHA-1），见 README「签名证书」\nsign %s\n' "$HASH" > "$CERTS_FILE"
  PINNED=$HASH
fi
if [ "$HASH" != "$PINNED" ]; then
  echo "✗ $SIGN_DIR 里的证书是 ${HASH:-（没有名为「chat-jev self-signed」的证书）}，但 $CERTS_FILE 要求 ${PINNED}。拿错备份了？" >&2
  exit 1
fi
codesign --force --deep --keychain "$KEYCHAIN" --sign "$IDENTITY" dist/chat-jev.app
codesign --verify --deep --strict dist/chat-jev.app
codesign -d -r- dist/chat-jev.app 2>&1 | grep -q "certificate leaf = H\"$PINNED\"" \
  || { echo "✗ 签出来的证书不是 $PINNED" >&2; exit 1; }
echo "已签名，证书 $PINNED"

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
