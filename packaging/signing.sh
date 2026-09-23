# 签名证书的公共函数，build.sh 和 rotate-cert.sh 都 source 这个文件。
#
# 证书是自签名的（不是 Apple 的），放在仓库外的钥匙串里，默认 ~/.chat-jev-signing：
#   signing.keychain-db   钥匙串（证书 + 私钥）
#   keychain-password     钥匙串密码
# 整个目录要备份：丢了已装的 app 就收不到自动更新了（见 README「签名证书」）。

IDENTITY="chat-jev self-signed"
CERTS_FILE="packaging/certs.txt"

# create_identity <目录>：在目录里生成一张新证书
create_identity() {
  dir="$1"
  mkdir -p "$dir" && chmod 700 "$dir"
  /usr/bin/openssl rand -hex 24 > "$dir/keychain-password" && chmod 600 "$dir/keychain-password"
  tmp=$(mktemp -d)
  cat > "$tmp/cert.cnf" <<CNF
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
  /usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -days 7300 -config "$tmp/cert.cnf" \
    -keyout "$tmp/key.pem" -out "$tmp/cert.pem" 2>/dev/null
  /usr/bin/openssl pkcs12 -export -inkey "$tmp/key.pem" -in "$tmp/cert.pem" -out "$tmp/id.p12" -passout pass:p12
  pw=$(cat "$dir/keychain-password")
  security create-keychain -p "$pw" "$dir/signing.keychain-db"
  security set-keychain-settings "$dir/signing.keychain-db"          # 不自动上锁
  security unlock-keychain -p "$pw" "$dir/signing.keychain-db"
  security import "$tmp/id.p12" -k "$dir/signing.keychain-db" -P p12 -T /usr/bin/codesign >/dev/null
  security set-key-partition-list -S apple-tool:,apple: -s -k "$pw" "$dir/signing.keychain-db" >/dev/null
  rm -rf "$tmp"
}

# identity_hash <目录>：证书的 SHA-1 指纹（小写），也就是签名要求里的 certificate leaf = H"..."
identity_hash() {
  dir="$1"
  security unlock-keychain -p "$(cat "$dir/keychain-password")" "$dir/signing.keychain-db"
  security find-identity -p codesigning "$dir/signing.keychain-db" \
    | awk -v id="\"$IDENTITY\"" 'index($0, id) { print tolower($2); exit }'
}

# certs_sign：certs.txt 里规定打包必须用的证书指纹
certs_sign() {
  [ -f "$CERTS_FILE" ] && awk '$1 == "sign" { print tolower($2); exit }' "$CERTS_FILE"
}
