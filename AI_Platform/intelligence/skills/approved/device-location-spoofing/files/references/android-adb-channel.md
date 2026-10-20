# Android 控制通道：WSL → Windows adb.exe

WSL 看不到 USB 设备，但 Windows 侧的 `adb.exe` 可以：adb server 跑在 Windows，扫的也是 Windows 的 USB。所以桥接方式就是“从 WSL 调 Windows 的 adb”。

## 一次性安装

```bash
curl -x http://127.0.0.1:7897 -L -o /tmp/pt.zip \
  https://dl.google.com/android/repository/platform-tools-latest-windows.zip
python3 -c "import zipfile; zipfile.ZipFile('/tmp/pt.zip').extractall('/mnt/c/')"
export ADB=/mnt/c/platform-tools/adb.exe && $ADB version
```

- WSL 默认**不走** Windows 系统代理，GitHub Release / dl.google.com 直连会卡在 0 字节直到超时；显式加 `-x http://127.0.0.1:7897`（Clash 端口按实际）。
- 没有 `unzip` 就用 python 的 `zipfile`，别为解压去装包。

## 手机上必须做的四步

1. 设置→关于手机→版本号 连点 7 次，解锁开发者选项。
2. 开发人员选项 → 打开 **USB 调试**。
3. 插线，弹「允许 USB 调试吗」→ 勾「始终允许」→ 允许。
4. 下拉通知栏把 USB 模式改成「传输文件」。

## 诊断：为什么 `adb devices` 是空的

```bash
$ADB kill-server; $ADB start-server; $ADB devices -l
```

再用 PowerShell 看设备树：

```powershell
Get-PnpDevice -PresentOnly | Where-Object { $_.FriendlyName -match 'HUAWEI|Honor|ADB|Android' } |
  Select-Object Status,Class,FriendlyName,InstanceId | Format-Table -AutoSize
```

- 只看到 `WPD`（如 `VID_12D1&PID_107E&MI_00`）和 `USB Mass Storage`：线通、文件传输可用，**但 USB 调试没开或没授权**。让用户回去开第 2/3 步。
- 出现 ADB Interface（`MI_02` 或专门的 ADB 设备）后才会有 `adb devices` 输出；此时若显示 `unauthorized`，是手机上的授权弹窗还没点。
- 华为/荣耀不需要 HiSuite HDB；那是另一套协议，和 adb 无关。

## 从 WSL 跑 PowerShell 的两个坑

- `powershell.exe` 不一定在 PATH：用绝对路径 `/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe`。
- 在 bash 里内联 PowerShell，`$null` / `$_` / 引号会先被 bash 吃掉，报出莫名其妙的语法错。把脚本写到 `/mnt/c/Users/Public/x.ps1`（UTF-8 with BOM）再 `-File` 执行。

## 通道通了之后能做什么（无 root）

- `adb install -r app.apk` 装 mock App。
- `adb shell appops set <pkg> android:mock_location allow` 直接把「模拟位置信息应用」设成它（省掉手动找菜单）。
- `adb shell cmd location providers add-test-provider gps --latitude <lat> --longitude <lon> --accuracy 10`（Android 11+ 有则可用）：不装 App 也能注入测试 provider，先 `help` 探一下该机型是否保留。
- 改设置：`adb shell settings put global wifi_scan_always_enabled 0` 一类，等价于手动关扫描。

adb 的能力边界：装包、改设置、注入测试 provider；**代替不了**在 App 里点地图选点（需要读屏/自动化，且厂商 ROM 常不兼容），也骗不过 App 自己的风控。
