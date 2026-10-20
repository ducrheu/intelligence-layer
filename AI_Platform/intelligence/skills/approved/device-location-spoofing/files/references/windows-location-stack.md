# Windows 位置栈：两种改法，只有一个真有用

## 位置从哪来

`lfsvc`（Windows Location Service）向应用提供坐标，来源优先级大致是：物理 GPS > WiFi 定位（扫描周边 AP 反查） > IP 定位 > **默认位置**。应用侧通常走 `Windows.Devices.Geolocation`（地图、天气、Edge、Chrome 都吃这一套）。

## 改法一：默认位置（无驱动）

写 `HKLM\SYSTEM\CurrentControlSet\Services\lfsvc\Service\Configuration` 下的两个 **REG_SZ**：`DefaultLatitude`、`DefaultLongitude`（十进制字符串，7 位小数），然后重启 `lfsvc`。需要管理员。

**只在没有其他定位源时生效。** 台式机/笔记本只要连着 WiFi，WiFi 定位就会压过去，写了等于没写。判断方法：先看 `Get-NetAdapter` 有没有 Up 的无线网卡，有就别指望这一招。

## 改法二：虚拟 GNSS 驱动

以 UMDF 2.0 驱动注册一个「GPS 接收器」，优先级高于 WiFi/IP，应用看到的就是真实传感器。代价很硬：

- 必须 **关 Secure Boot + `bcdedit /set testsigning on` + 重启**；
- 改启动配置可能让 BitLocker 在下次开机索要 48 位恢复密钥（先 `manage-bde -protectors -disable C: -RebootCount 1` 或确认已备份）；
- 驱动是未签名的，杀软/Vanguard 类反作弊会盯上。

**给用户报方案时必须把这三条一起说**，只报「能改」是误导。多数场景（只是想让浏览器/某个网页看到别处）用 CDP 就够了，不值得为此拆掉启动安全链。

## 验证改没改成功

别只看 Windows 设置页面。用浏览器侧的实测：打开一个会索要定位的页面，读回坐标并与目标比对；同时确认 Chrome 是否走了代理（代理只改 HTTP 出口，不改定位）。

## 前置检查（PowerShell，从 WSL 调用要写全路径）

```powershell
# 管理员?
([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
# 无线网卡是否在线（决定默认位置有没有用）
Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | Select Name,InterfaceDescription
# 默认位置现值
Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\lfsvc\Service\Configuration' -ErrorAction SilentlyContinue | Select DefaultLatitude,DefaultLongitude
```

`powershell.exe` 不在 WSL 的 PATH 上，用 `/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe`。脚本要落到 `/mnt/c/Users/Public/` 再用 `-File` 跑，写进 WSL 的 `/tmp` Windows 看不见。
