#!/usr/bin/env bash
# 一键构建所有分发产物到 dist/
#
#   ./build.sh                 版本取 git describe，回退 1.0.0
#   VERSION=1.2.3 ./build.sh
#
# 产物：
#   dist/green-tracker-client_<ver>_all.deb   Debian 系：sudo dpkg -i
#   dist/green-tracker-client-<ver>-linux.tar.gz   通用 Linux：解压后 ./install.sh
#   dist/green-tracker-client-<ver>-windows.zip    Windows：解压后 install.ps1
set -euo pipefail

APP_NAME="green-tracker-client"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"

VERSION="${VERSION:-}"
if [[ -z "$VERSION" ]]; then
    VERSION="$(git -C "$REPO_ROOT" describe --tags --abbrev=0 2>/dev/null || true)"
    VERSION="${VERSION#v}"
    VERSION="${VERSION:-1.0.0}"
fi

EXCLUDES=(
    --exclude=./.git --exclude=./tests --exclude=./doc
    --exclude=./dist --exclude=./build --exclude=./.pytest_cache
    --exclude=./.venv --exclude=./.env
    --exclude=__pycache__ --exclude='*.pyc' --exclude='*.pyo'
)

stage_payload() {   # $1 = 目标目录
    local target="$1"
    mkdir -p "$target"
    tar -C "$REPO_ROOT" "${EXCLUDES[@]}" -cf - . | tar -C "$target" -xf -
}

echo "==> 版本: $VERSION"
mkdir -p "$DIST_DIR"

# ---------------------------------------------------------------- Linux 通用包
LINUX_STAGE="$DIST_DIR/stage/${APP_NAME}-${VERSION}"
rm -rf "$LINUX_STAGE"
stage_payload "$LINUX_STAGE"
cat > "$LINUX_STAGE/install.sh" <<'EOF'
#!/bin/sh
exec "$(dirname "$0")/packaging/linux/install.sh" "$@"
EOF
cat > "$LINUX_STAGE/uninstall.sh" <<'EOF'
#!/bin/sh
exec "$(dirname "$0")/packaging/linux/uninstall.sh" "$@"
EOF
chmod +x "$LINUX_STAGE/install.sh" "$LINUX_STAGE/uninstall.sh"
tar -C "$DIST_DIR/stage" -czf \
    "$DIST_DIR/${APP_NAME}-${VERSION}-linux.tar.gz" "${APP_NAME}-${VERSION}"
echo "==> 产出: $DIST_DIR/${APP_NAME}-${VERSION}-linux.tar.gz"

# ---------------------------------------------------------------- Windows 包
WIN_STAGE="$DIST_DIR/stage/${APP_NAME}-${VERSION}-win"
rm -rf "$WIN_STAGE"
stage_payload "$WIN_STAGE"
cat > "$WIN_STAGE/install.ps1" <<'EOF'
& "$PSScriptRoot\packaging\windows\install.ps1" -SourceDir $PSScriptRoot @args
EOF
cat > "$WIN_STAGE/uninstall.ps1" <<'EOF'
& "$PSScriptRoot\packaging\windows\uninstall.ps1" @args
EOF
ZIP_FILE="$DIST_DIR/${APP_NAME}-${VERSION}-windows.zip"
rm -f "$ZIP_FILE"
if command -v zip >/dev/null 2>&1; then
    (cd "$DIST_DIR/stage" && zip -qr "$ZIP_FILE" "${APP_NAME}-${VERSION}-win")
else
    # 没有 zip 时退回 Python 标准库，保证一定能出包
    (cd "$DIST_DIR/stage" && python3 -m zipfile -c "$ZIP_FILE" "${APP_NAME}-${VERSION}-win")
fi
echo "==> 产出: $ZIP_FILE"

# ---------------------------------------------------------------- deb 包
VERSION="$VERSION" bash "$SCRIPT_DIR/linux/build_deb.sh"

echo ""
echo "全部产物已生成于: $DIST_DIR"
ls -lh "$DIST_DIR" | tail -n +2
