#!/usr/bin/env bash
# 构建 Debian 安装包：dist/green-tracker-client_<version>_all.deb
#
#   ./build_deb.sh             版本取 git describe，回退 1.0.0
#   VERSION=1.2.3 ./build_deb.sh
set -euo pipefail

APP_NAME="green-tracker-client"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEB_TEMPLATE="$SCRIPT_DIR/deb"
DIST_DIR="$REPO_ROOT/dist"

VERSION="${VERSION:-}"
if [[ -z "$VERSION" ]]; then
    VERSION="$(git -C "$REPO_ROOT" describe --tags --abbrev=0 2>/dev/null || true)"
    VERSION="${VERSION#v}"
    VERSION="${VERSION:-1.0.0}"
fi

STAGE="$DIST_DIR/deb-build/$APP_NAME"
rm -rf "$STAGE"
mkdir -p "$STAGE/opt/$APP_NAME" "$STAGE/DEBIAN"

echo "==> 版本: $VERSION"

# 应用文件（排除测试、过程文档、缓存与本机 .env）
tar -C "$REPO_ROOT" \
    --exclude=./.git --exclude=./tests --exclude=./doc \
    --exclude=./dist --exclude=./build --exclude=./.pytest_cache \
    --exclude=./.venv --exclude=./.env \
    --exclude=__pycache__ --exclude='*.pyc' --exclude='*.pyo' \
    -cf - . | tar -C "$STAGE/opt/$APP_NAME" -xf -

# 控制文件
cp "$DEB_TEMPLATE/DEBIAN/control" "$STAGE/DEBIAN/control"
sed -i "s/@VERSION@/$VERSION/" "$STAGE/DEBIAN/control"
for script in postinst prerm; do
    cp "$DEB_TEMPLATE/DEBIAN/$script" "$STAGE/DEBIAN/$script"
    chmod 0755 "$STAGE/DEBIAN/$script"
done
chmod 0644 "$STAGE/DEBIAN/control"

mkdir -p "$DIST_DIR"
DEB_FILE="$DIST_DIR/${APP_NAME}_${VERSION}_all.deb"
rm -f "$DEB_FILE"
dpkg-deb --build --root-owner-group "$STAGE" "$DEB_FILE" >/dev/null

echo "==> 产出: $DEB_FILE"
echo "    安装: sudo dpkg -i $DEB_FILE"
