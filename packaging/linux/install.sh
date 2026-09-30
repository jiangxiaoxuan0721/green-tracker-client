#!/usr/bin/env bash
# 一键安装 green-tracker-client（源码 + venv 形态）
#
#   ./install.sh                      用户级安装（默认 ~/.local/share/...）
#   sudo ./install.sh --system        系统级安装（/opt + /usr/bin）
#   ./install.sh --prefix /some/dir   自定义应用目录
#
# 安装内容：应用源码 + 独立虚拟环境 + 启动器 + 应用菜单/桌面快捷方式 + 配置模板
# 不会动的东西：已存在的配置文件、~/green_tracker_data 采集数据
set -euo pipefail

APP_NAME="green-tracker-client"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MIN_PYTHON="3.10"

SOURCE_DIR="$REPO_ROOT"
PREFIX="${PREFIX:-$HOME/.local/share/$APP_NAME}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
APPLICATIONS_DIR="${APPLICATIONS_DIR:-$HOME/.local/share/applications}"
ICON_DIR="${ICON_DIR:-$HOME/.local/share/icons/hicolor/scalable/apps}"
CONFIG_DIR="${CONFIG_DIR:-}"
PYTHON="${PYTHON:-python3}"
IN_PLACE=0
NO_CONFIG=0

usage() {
    sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix)           PREFIX="$2"; shift 2 ;;
        --bin-dir)          BIN_DIR="$2"; shift 2 ;;
        --applications-dir) APPLICATIONS_DIR="$2"; shift 2 ;;
        --icon-dir)         ICON_DIR="$2"; shift 2 ;;
        --source-dir)       SOURCE_DIR="$2"; shift 2 ;;
        --config-dir)       CONFIG_DIR="$2"; shift 2 ;;
        --python)           PYTHON="$2"; shift 2 ;;
        --in-place)         IN_PLACE=1; shift ;;
        --no-config)        NO_CONFIG=1; shift ;;
        -h|--help)          usage ;;
        *) echo "未知参数: $1" >&2; exit 2 ;;
    esac
done

# 系统级安装：postinst 里常用，一键切换到系统路径
if [[ "${SYSTEM:-0}" == "1" ]]; then
    PREFIX="/opt/$APP_NAME"
    BIN_DIR="/usr/bin"
    APPLICATIONS_DIR="/usr/share/applications"
    ICON_DIR="/usr/share/icons/hicolor/scalable/apps"
    NO_CONFIG=1
fi

log() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m错误:\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- 前置检查
command -v "$PYTHON" >/dev/null 2>&1 || die "未找到 $PYTHON，请先安装 Python $MIN_PYTHON 及以上"
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
    || die "Python 版本过低，需要 $MIN_PYTHON 及以上（当前: $("$PYTHON" -V 2>&1)）"
command -v tar >/dev/null 2>&1 || die "未找到 tar"

# ---------------------------------------------------------------- 应用文件
if [[ "$IN_PLACE" == "1" ]]; then
    log "就地安装，复用已有文件: $PREFIX"
    [[ -f "$PREFIX/main.py" ]] || die "$PREFIX 下没有 main.py，--in-place 需要源码已在目标目录"
else
    [[ -f "$SOURCE_DIR/main.py" ]] || die "$SOURCE_DIR 下没有 main.py，请检查 --source-dir"
    log "安装应用到: $PREFIX"
    mkdir -p "$PREFIX"
    tar -C "$SOURCE_DIR" \
        --exclude=./.git --exclude=./tests --exclude=./doc \
        --exclude=./dist --exclude=./build --exclude=./.pytest_cache \
        --exclude=./.venv --exclude=./.env \
        --exclude=__pycache__ --exclude='*.pyc' --exclude='*.pyo' \
        -cf - . | tar -C "$PREFIX" -xf -
fi

# ---------------------------------------------------------------- 虚拟环境
log "创建虚拟环境并安装依赖"
"$PYTHON" -m venv "$PREFIX/.venv"
"$PREFIX/.venv/bin/python" -m pip install --upgrade pip -q
"$PREFIX/.venv/bin/python" -m pip install -r "$PREFIX/requirements.txt" -q

# ---------------------------------------------------------------- 启动器
LAUNCHER="$BIN_DIR/$APP_NAME"
if [[ -n "$CONFIG_DIR" ]]; then
    DEFAULT_CONFIG="$CONFIG_DIR"
else
    # 写进启动器里，随启动用户展开（系统级安装时每个用户各用自己的配置）
    DEFAULT_CONFIG="\${HOME}/.config/$APP_NAME"
fi
mkdir -p "$BIN_DIR"
sed -e "s|@APP_DIR@|$PREFIX|g" -e "s|@CONFIG_DIR@|$DEFAULT_CONFIG|g" \
    "$PREFIX/packaging/linux/launcher.sh.in" > "$LAUNCHER"
chmod +x "$LAUNCHER"
log "启动器: $LAUNCHER"

# ---------------------------------------------------------------- 图标菜单
mkdir -p "$ICON_DIR" "$APPLICATIONS_DIR"
cp "$PREFIX/packaging/linux/$APP_NAME.svg" "$ICON_DIR/$APP_NAME.svg"
sed -e "s|@LAUNCHER@|$LAUNCHER|g" -e "s|@ICON@|$ICON_DIR/$APP_NAME.svg|g" \
    "$PREFIX/packaging/linux/$APP_NAME.desktop.in" \
    > "$APPLICATIONS_DIR/$APP_NAME.desktop"
chmod +x "$APPLICATIONS_DIR/$APP_NAME.desktop"
if [[ -d "${HOME}/Desktop" ]]; then
    cp "$APPLICATIONS_DIR/$APP_NAME.desktop" "${HOME}/Desktop/$APP_NAME.desktop"
    chmod +x "${HOME}/Desktop/$APP_NAME.desktop"
fi
log "应用菜单项: $APPLICATIONS_DIR/$APP_NAME.desktop"

# ---------------------------------------------------------------- 配置模板
if [[ "$NO_CONFIG" == "1" ]]; then
    log "跳过配置生成（首次启动时按当前用户自动创建）"
else
    TARGET_CONFIG="${CONFIG_DIR:-$HOME/.config/$APP_NAME}"
    log "生成配置模板: $TARGET_CONFIG"
    "$PYTHON" "$PREFIX/packaging/common/prepare_config.py" "$TARGET_CONFIG"
fi

cat <<EOF

安装完成。
  应用目录: $PREFIX
  启动命令: $LAUNCHER
  配置文件: ${CONFIG_DIR:-$HOME/.config/$APP_NAME}/.env
  指令策略: ${CONFIG_DIR:-$HOME/.config/$APP_NAME}/command_policy.json
请填写 .env 后从应用菜单启动；重装或升级不会覆盖已改过的配置。
EOF
