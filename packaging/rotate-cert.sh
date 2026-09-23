#!/bin/bash
# 换签名证书，已装的 app 不用重装，自动更新会接上。分两步，中间要发一次版：
#
#   packaging/rotate-cert.sh prepare   生成新证书（~/.chat-jev-signing-next），在 certs.txt 里把它写成 trust
#   …照常发一版（还是旧证书签的）。已装的 app 更新到这版后，就会接受新证书签的更新
#   packaging/rotate-cert.sh switch    新旧证书对调，certs.txt 改成用新证书签。之后发的版本都用新证书
#
# 旧证书必须还在才能这样换。证书真丢了没有自动的办法，见 README「签名证书」。
# 换完以后辅助功能权限会失效一次（系统按证书认 app），app 会自动清掉旧记录、打开设置页，拨一下开关就行。
set -euo pipefail
cd "$(dirname "$0")/.."
. packaging/signing.sh

SIGN_DIR="${CHAT_JEV_SIGN_DIR:-$HOME/.chat-jev-signing}"
NEXT_DIR="$SIGN_DIR-next"

case "${1:-}" in
prepare)
  [ -f "$SIGN_DIR/signing.keychain-db" ] || { echo "✗ 找不到现在的证书 ${SIGN_DIR}，没法交接" >&2; exit 1; }
  [ ! -e "$NEXT_DIR" ] || { echo "✗ $NEXT_DIR 已经存在：上次 prepare 了还没 switch？" >&2; exit 1; }
  create_identity "$NEXT_DIR"
  NEW=$(identity_hash "$NEXT_DIR")
  printf 'trust %s\n' "$NEW" >> "$CERTS_FILE"
  echo "新证书 $NEW → ${NEXT_DIR}（现在就备份这个目录）"
  echo "下一步：提交 ${CERTS_FILE}，照常打包发一版；已装的 app 更新到那一版后，再跑 $0 switch"
  ;;
switch)
  [ -f "$NEXT_DIR/signing.keychain-db" ] || { echo "✗ 没有 ${NEXT_DIR}，先跑 $0 prepare" >&2; exit 1; }
  NEW=$(identity_hash "$NEXT_DIR")
  grep -q "^trust $NEW" "$CERTS_FILE" || { echo "✗ $CERTS_FILE 里没有 trust $NEW" >&2; exit 1; }
  # 带着 trust 的那次提交必须已经发过版，不然已装的 app 还不认新证书，会卡在旧版本
  COMMIT=$(git log -1 --format=%H -S "trust $NEW" -- "$CERTS_FILE")
  TAG=$(git describe --tags --abbrev=0 2>/dev/null || true)
  if [ -z "$COMMIT" ] || [ -z "$TAG" ] || ! git merge-base --is-ancestor "$COMMIT" "$TAG"; then
    echo "✗ 带 trust $NEW 的版本还没发布（最新 tag：${TAG:-无}）。先提交、发版，再 switch。" >&2
    exit 1
  fi
  OLD_BACKUP="$SIGN_DIR-old-$(date +%Y%m%d)"
  mv "$SIGN_DIR" "$OLD_BACKUP"
  mv "$NEXT_DIR" "$SIGN_DIR"
  OLD=$(certs_sign)
  { echo "# 签名证书指纹（SHA-1），见 README「签名证书」"
    echo "# sign  = 打包必须用的证书；build.sh 对不上就停"
    echo "# trust = 已装的 app 额外信任的证书：换证书时先把新证书写成 trust 发一版，已装的 app 才会接受新证书签的更新"
    echo "sign $NEW"
    echo "# $(date +%Y-%m-%d) 从 $OLD 换过来"; } > "$CERTS_FILE"
  echo "已换成新证书 ${NEW}；旧证书挪到 ${OLD_BACKUP}。提交 $CERTS_FILE 后正常发版即可。"
  ;;
*)
  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
  ;;
esac
