#!/usr/bin/env bash
# 卸载 green-tracker-client —— 只删应用与快捷方式，保留配置与采集数据
#
#   ./uninstall.sh                 卸载用户级安装
#   sudo ./uninstall.sh --system   卸载系统级安装
set -euo pipefail

APP_NAME="green-tracker-client"

PREFIX="${PREFIX:-$HOME/.local/share/$APP_NAME}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
APPLICATIONS_DIR="${APPLICATIONS_DIR:-$HOME/.local/share/applications}"
ICON_DIR="${ICON_DIR:-$HOME/.local/share/icons/hicolor/scalable/apps}"
PURGE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix)           PREFIX="$2"; shift 2 ;;
        --bin-dir)          BIN_DIR="$2"; shift 2 ;;
        --applications-dir) APPLICATIONS_DIR="$2"; shift 2 ;;
        --icon-dir)         ICON_DIR="$2"; shift 2 ;;
        --purge)            PURGE=1; shift ;;   # 连配置一起删（默认保留）
        -h|--help)          sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "未知参数: $1" >&2; exit 2 ;;
    esac
done

if [[ "${SYSTEM:-0}" == "1" ]]; then
    PREFIX="/opt/$APP_NAME"
    BIN_DIR="/usr/bin"
    APPLICATIONS_DIR="/usr/share/applications"
    ICON_DIR="/usr/share/icons/hicolor/scalable/apps"
fi

log() { printf '\033[1;33m==>\033[0m %s\n' "$*"; }
rm_if() { [[ -e "$1" ]] && { rm -rf "$1"; log "已删除: $1"; } || true; }

rm_if "$PREFIX"
rm_if "$BIN_DIR/$APP_NAME"
rm_if "$APPLICATIONS_DIR/$APP_NAME.desktop"
rm_if "$ICON_DIR/$APP_NAME.svg"
rm_if "${HOME}/Desktop/$APP_NAME.desktop"

CONFIG_DIR="${CONFIG_DIR:-$HOME/.config/$APP_NAME}"
if [[ "$PURGE" == "1" ]]; then
    rm_if "$CONFIG_DIR"
else
    log "已保留配置: $CONFIG_DIR（如需清除请加 --purge）"
fi
log "已保留采集数据: ${GREEN_TRACKER_DATA_DIR:-$HOME/green_tracker_data}"

echo "卸载完成。"
