# 起一个可被 CDP 驱动的浏览器（Chrome / Edge）

## 为什么必须自己起

Chromium ≥136 拒绝在**默认 profile** 上开 `--remote-debugging-port`（Chrome 和 Edge 都算）。所以接不上用户已经开着的那几个窗口，唯一办法是**新起一个独立 profile 的实例**。代价：这个 profile 一开始是空的，任何登录态都要现做一次（扫码 / vault 填），**做完就长期留着**。

## 从 WSL 拉起

用 `terminal(background=true)` 跑 Windows 的 exe。**不要**加 `nohup` / `setsid` / `disown`（终端工具会拒 shell 级后台包装），Windows 路径用正斜杠：

```bash
# Edge（端口 9223，profile C:/EdgeCDP）
"/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
  --remote-debugging-port=9223 --user-data-dir=C:/EdgeCDP \
  --remote-allow-origins=* --no-first-run --no-default-browser-check about:blank
```

Chrome 同理（端口 9222 / `--user-data-dir=C:/OpenClawCDP`）。exe 的确切路径不要靠猜 —— 用下面的进程查询拿 `ExecutablePath`。`--remote-allow-origins=*` 别省，否则部分 CDP 客户端在握手处就被拒。

## 探活：轮询，别 blind sleep

```bash
for i in $(seq 6); do R=$(curl -s -m 3 http://127.0.0.1:9223/json/version); [ -n "$R" ] && break; sleep 3; done; echo "$R"
```

`Browser` 字段同时回答**起没起来**和**是谁**：`Chrome/154…` vs `Edg/154…`。起来了再 `CDP_PORT=9223 $PY cdp_cli.py list`。

## 查 Windows 侧进程与命令行

WSL 里 `powershell.exe` / `tasklist.exe` **不在 PATH 上**，用全路径：

```bash
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
"$PS" -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' or Name='chrome.exe'\" | Where-Object { \$_.CommandLine -match 'remote-debugging|user-data-dir' } | Select-Object -First 5 ExecutablePath,CommandLine | Format-List"
```

排查「为什么连不上」第一件事就是看命令行里的 `--user-data-dir=`：默认 profile 的实例根本不会开调试端口。只列进程：`/mnt/c/Windows/System32/tasklist.exe /FI "IMAGENAME eq msedge.exe" /FO CSV`。

## 拉起来之后要主动告诉用户的事

- **新 Edge profile 会自动登进他的微软账号并开始同步。** Windows 处于登录状态时 Edge 默认这么做，页面原话是「我们现在正在你的所有设备上同步你的浏览数据」。好处是收藏夹 / 密码很快可用；代价是这在他账号上多了一台**同步设备**。**主动报给他并让他定**：留（可去设置里登出，登出后就是空白浏览器）还是连 profile 一起删。这是用户可见的副作用，不能默默做掉。
- **别为每个网站开一个新浏览器。** 推荐长期留一个可调试 profile，要操作的站点在上面登录一次（扫码 / vault），登录态就一直在；除非某站点只有另一个浏览器才正常（政企 / 银联 / 需要 IE 模式的）。

## 重启 / 复活（浏览器已经不在时）

关掉调试 Chrome 的**最后一个标签页** = 浏览器进程退出，`/json/version` 变超时，看着像 CDP 挂了。批量清理标签时先数一下数量，留一个。

复活走 Windows 侧 `Start-Process`（比从 WSL 直接执行 exe 稳，不会把那条 terminal 调用拖到超时）：

```bash
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
# 先清残留（按命令行筛，别按进程名一刀切，否则会杀掉用户日常那个 Chrome）
"$PS" -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | Where-Object { \$_.CommandLine -like '*OpenClawCDP*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }"
sleep 4
"$PS" -NoProfile -Command "Start-Process -FilePath 'C:\Program Files\Google\Chrome\Application\chrome.exe' -ArgumentList '--remote-debugging-port=9222','--user-data-dir=C:\OpenClawCDP','--remote-allow-origins=*','--no-first-run','--no-default-browser-check'"
```

这套参数与 `Stop-Process`/`Start-Process` 手法就是闲鱼巡店兜底脚本 `xianyu_patrol.sh` 的 revive，出问题时可以直接照它抄。杀主进程连同子进程用 `/mnt/c/Windows/System32/taskkill.exe /F /PID <pid> /T`。

## 收尾

用完 `cdp_cli.py close <tid>` 关掉自己开的临时标签页，别在用户窗口里堆一堆；注意别关掉用户自己在看的那个，也**别关到只剩零个**（见上节）。
