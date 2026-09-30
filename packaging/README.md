# 一键安装包

`green-tracker-client` 的分发与安装。分发形态为**源码 + venv**：目标机需 Python 3.10+
且首次安装时联网装依赖；优点是体积小、升级只需替换源码，不需要冻结 Qt 运行环境。

## 产物一览

| 平台 | 产物 | 安装方式 |
|------|------|---------|
| Debian / Ubuntu | `green-tracker-client_<ver>_all.deb` | `sudo dpkg -i xxx.deb`（可 `sudo apt remove` 卸载） |
| 通用 Linux | `green-tracker-client-<ver>-linux.tar.gz` | 解压后 `./install.sh` |
| Windows | `green-tracker-client-<ver>-windows.zip` | 解压后 PowerShell 运行 `install.ps1` |

构建（在仓库根目录）：

```bash
./packaging/build.sh                  # 全部产物
VERSION=1.2.3 ./packaging/build.sh    # 指定版本
```

## 安装做了什么

1. 拷贝应用源码到安装目录（排除 `tests/`、`doc/`、`dist/`、`__pycache__`、本机 `.env`）
2. 建独立虚拟环境 `.venv` 并按 `requirements.txt` 安装依赖
3. 生成启动器（Linux: `bin/green-tracker-client`；Windows: `green-tracker-client.cmd`）
4. 写应用菜单项与桌面快捷方式（含图标）
5. 生成配置模板 `.env` 与 `command_policy.json`，**已存在则原样保留**

## 目录布局

| | Linux 用户级（默认） | Linux 系统级（deb / `--system`） | Windows |
|---|---|---|---|
| 应用 + venv | `~/.local/share/green-tracker-client` | `/opt/green-tracker-client` | `%LOCALAPPDATA%\GreenTrackerClient` |
| 启动器 | `~/.local/bin/green-tracker-client` | `/usr/bin/green-tracker-client` | 安装目录下 `.cmd` |
| 配置 | `~/.config/green-tracker-client` | 每个用户自己的 `~/.config/...`（首次启动生成） | `%APPDATA%\GreenTrackerClient` |
| 采集数据 | `~/green_tracker_data` | 同左 | `%USERPROFILE%\green_tracker_data` |

配置目录由 `GREEN_TRACKER_CONFIG_DIR` 决定（启动器会自动带上），程序启动时会
`cd` 到该目录，因此安装后即使 CWD 不是仓库根也能读到 `.env` 与策略文件。

## 升级与卸载

```bash
# 升级：重新跑一次安装脚本即可，配置不会被覆盖
./install.sh

# 卸载：删应用与快捷方式，保留配置与采集数据
./uninstall.sh
./uninstall.sh --purge        # 连配置一起删

# deb
sudo dpkg -i green-tracker-client_<ver>_all.deb
sudo apt remove green-tracker-client
```

Windows 对应：`uninstall.ps1` / `uninstall.ps1 -Purge`。

## Windows 注意事项

`install.ps1` / `uninstall.ps1` 保持**纯 ASCII（输出为英文）**：Windows PowerShell 5.1 会把无 BOM
的 `.ps1` 当作系统 ANSI（中文环境即 GBK）解码，含中文会出现乱码，严重时字节错位导致
`ParserError` 直接无法运行。PowerShell 7（`pwsh`）无此问题，但为兼容 5.1 一律只用 ASCII。

安装时若提示「未对文件进行数字签名」，是默认执行策略 `Restricted` 拦截，按如下方式运行：

```powershell
cd <解压目录>\packaging\windows
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass   # 仅当前窗口生效
.\install.ps1
```

或在 cmd 中一次性绕过：`powershell -ExecutionPolicy Bypass -File .\install.ps1`。
也可在解压前右键 zip → 属性 → 勾选「解除锁定」，去掉「来自互联网」标记。

## 首次使用

1. 编辑配置目录下的 `.env`：填 `API_BASE_URL`、`SECRET_KEY`、`MQTT_DEVICE_*`
2. 按需调整 `command_policy.json`（指令启用开关，改完保存即生效，无需重启）
3. 从应用菜单启动，或在终端执行 `green-tracker-client`

## 目录结构

```
packaging/
├── build.sh                 统一构建入口（tar.gz / zip / deb）
├── common/
│   └── prepare_config.py    配置模板生成器（不覆盖已有文件）
├── linux/
│   ├── install.sh           一键安装（--system / --prefix / --in-place ...）
│   ├── uninstall.sh         卸载（--purge 清配置）
│   ├── launcher.sh.in       启动器模板
│   ├── green-tracker-client.desktop.in / .svg
│   ├── build_deb.sh         deb 构建
│   └── deb/DEBIAN/{control,postinst,prerm}
└── windows/
    ├── install.ps1          一键安装（-InstallDir / -ConfigDir / -NoShortcut）
    ├── uninstall.ps1        卸载（-Purge 清配置）
    └── green-tracker-client.cmd 由 install.ps1 生成
```

## 测试

- `tests/test_config_dir.py` —— 配置目录解析、策略文件回退链、`.env` 加载（config 与 mqtt 两侧）
- `tests/test_prepare_config.py` —— 模板生成与「不覆盖已有配置」
