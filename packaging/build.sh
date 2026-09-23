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
# 证书和私钥在仓库外的 ~/.chat-jev-signing，第一次打包时生成。丢了就只能换新证书，已装的 app 要手动重装一次。
SIGN_DIR="${CHAT_JEV_SIGN_DIR:-$HOME/.chat-jev-signing}"
KEYCHAIN="$SIGN_DIR/signing.keychain-db"
IDENTITY="chat-jev self-signed"
if [ ! -f "$KEYCHAIN" ]; then
  echo "生成签名证书 → $SIGN_DIR"
  mkdir -p "$SIGN_DIR" && chmod 700 "$SIGN_DIR"
  openssl rand -hex 24 > "$SIGN_DIR/keychain-password" && chmod 600 "$SIGN_DIR/keychain-password"
  TMP=$(mktemp -d)
  cat > "$TMP/cert.cnf" <<CNF
[req]
distinguished_name=dn
x509_extensions=ext
prompt=no
[dn]
CN=$IDENTITY
[ext]
basicConstraints=critical,CA:false
keyUsage=critical,digitalSignature
extendedKeyUsage=critical,codeSigning
CNF
  /usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -days 7300 -config "$TMP/cert.cnf" \
    -keyout "$TMP/key.pem" -out "$TMP/cert.pem" 2>/dev/null
  /usr/bin/openssl pkcs12 -export -inkey "$TMP/key.pem" -in "$TMP/cert.pem" -out "$TMP/id.p12" -passout pass:p12
  security create-keychain -p "$(cat "$SIGN_DIR/keychain-password")" "$KEYCHAIN"
  security set-keychain-settings "$KEYCHAIN"               # 不自动上锁
  security unlock-keychain -p "$(cat "$SIGN_DIR/keychain-password")" "$KEYCHAIN"
  security import "$TMP/id.p12" -k "$KEYCHAIN" -P p12 -T /usr/bin/codesign >/dev/null
  security set-key-partition-list -S apple-tool:,apple: -s -k "$(cat "$SIGN_DIR/keychain-password")" "$KEYCHAIN" >/dev/null
  rm -rf "$TMP"
fi
security unlock-keychain -p "$(cat "$SIGN_DIR/keychain-password")" "$KEYCHAIN"
codesign --force --deep --keychain "$KEYCHAIN" --sign "$IDENTITY" dist/chat-jev.app
codesign --verify --deep --strict dist/chat-jev.app
codesign -d -r- dist/chat-jev.app 2>&1 | grep '^designated'

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
