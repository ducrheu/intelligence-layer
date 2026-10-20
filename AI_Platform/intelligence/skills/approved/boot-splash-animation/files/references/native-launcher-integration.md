# 把 HTML 原型变成双击即用的启动动画（WebView2 外壳）

配合 SKILL.md 第 8 节。适用场景：效果是用 CSS/HTML 做的（辉光、渐变文字、视频合成），
而目标应用改不动。GDI+ 手绘复刻这些效果不现实，用 WebView2 外壳直接跑同一份 HTML。

## 1. 目录形状

```
splash-boot\
  SplashLauncher.exe          ← 外壳（源码见 templates/webview2-splash-launcher.cs）
  Microsoft.Web.WebView2.Core.dll
  Microsoft.Web.WebView2.WinForms.dll
  WebView2Loader.dll
  hermes.ini                  ← 一个目标一份配置
  openclaw.ini
  boot\hermes\index.html      ← 动画页（12 KB）
  boot\hermes\bg.mp4          ← 视频独立成文件
  boot\hermes\fallback.jpg    ← 兜底静态帧
```

ini 是扁平 `key=value`（`#` / `;` 开头为注释）：

```ini
exe=C:\...\Hermes.exe
dir=C:\...\win-unpacked
html=C:\...\splash-boot\boot\hermes\index.html
w=1280             ; 动画窗口尺寸（居中普通窗口，不是全屏）
h=820
warm=2500          ; 动画播到多少毫秒时预热拉起目标；0 = 立即
label=DeepSeek     ; WebView2 初始化期间顶在首屏的占位字标
```

## 2. WebView2 绑定的取材（唯一有坑的一步）

要 **.NET Framework 版**。NuGet 包 `microsoft.web.webview2` 解出三件套放 exe 同目录：

- `lib/net462/Microsoft.Web.WebView2.Core.dll`
- `lib/net462/Microsoft.Web.WebView2.WinForms.dll`
- `runtimes/win-x64/native/WebView2Loader.dll`

别的程序目录里能搜到同名 DLL（Windows Performance Toolkit、WSL Settings 都带了），
但那是 **.NET Core/Standard 版**，引用后报：

```
CS0012: 类型“System.ComponentModel.ISupportInitialize”在未被引用的程序集中定义。
必须添加对程序集“System.ComponentModel.Primitives, Version=4.2.1.0 ...”的引用。
```

**这不是缺引用，是版本不对——换包，不要加引用。**

包是 zip，而处理机上常没有 `unzip`：

```bash
curl -sL -o wv2.nupkg "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/1.0.2903.40/microsoft.web.webview2.1.0.2903.40.nupkg"
python3 -c "import zipfile;zipfile.ZipFile('wv2.nupkg').extractall('x')"
```

（系统级 WebView2 运行时是另一回事，检查 `C:\Program Files (x86)\Microsoft\EdgeWebView\Application\<ver>`
是否存在即可，通常已装。）

## 3. 编译：用系统 csc，注意它只认 C# 5

```bash
CSC=/mnt/c/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe
D='C:\...\splash-boot'
"$CSC" /nologo /target:winexe /platform:x64 /out:"$D\SplashLauncher.exe" \
  /r:"$D\Microsoft.Web.WebView2.Core.dll" \
  /r:"$D\Microsoft.Web.WebView2.WinForms.dll" \
  /r:System.dll /r:System.Windows.Forms.dll /r:System.Drawing.dll \
  "$D\SplashLauncher.cs"
```

**这个 csc 不支持**：局部函数、`out var`、字符串插值 `$""`、表达式体成员 `=>`。
踩到时它报一串 `CS1513: 应输入 }` / `CS1519`，看着像括号写错，实际是语言版本不够。
改回 C# 5 写法通常比换编译器快；真需要新语法就用 dotnet SDK 里的 Roslyn：

```bash
dotnet exec "C:\Program Files\dotnet\sdk\9.0.101\Roslyn\bincore\csc.dll" ...
```

（得多带框架程序集的 `--reference`。）产物只有 ~10 KB。

## 4. 动画页与外壳的握手段

动画页在播完后报信，外壳收到就拉起目标并自杀：

```js
setTimeout(function(){
  try{
    if (window.chrome && window.chrome.webview && window.chrome.webview.postMessage){
      window.chrome.webview.postMessage('done');
    }
  }catch(e){}
}, 5400);   // 动画全长 + 少量余量
```

外壳侧：`WebMessageReceived` → `StartTarget()` → `Close()`。另挂一个 **watchdog 计时器**
（12 s），页面压根没加载出来时也能拉起目标——webview 挂掉不能让用户开不了应用。

## 5. 预热：总耗时 = 动画时长

不预热的话用户要等「动画 5.4 s + 应用冷启动 2–3 s」。改成动画播到 2.5 s 就
`Process.Start` 拉起目标，动画结束时它已就绪。

- 窗口 `TopMost = true` 盖住抢跑的应用窗口。
- 启动快的应用仍可能提前冒出来打断动画 → **`warm` 必须可配置**，让用户自己调大。
- Electron 类应用实测 ≥2.5 s 才有意义。

## 6. 目标路径：读 .lnk，不要猜

```powershell
$s = New-Object -ComObject WScript.Shell
$l = $s.CreateShortcut("C:\Users\X\Desktop\App.lnk")
$l.TargetPath; $l.Arguments; $l.WorkingDirectory
```

用户机器上的应用常常既不在 PATH 也不在默认安装位置（Electron 应用可能在
`%LOCALAPPDATA%\<vendor>\...\win-unpacked\`）。安装目录同样可用 `WScript.Shell` 的
`CreateShortcut(...).Save()` 建带参数的 .lnk（参数跟目标之间要有空格）。

改用户**原有**快捷方式前，先把原目标路径字符串抄下来备着，并在说明里写清怎么还原。

## 7. 验收（看不到用户桌面时）

| 可观测量 | 命令 | 证明了什么 |
|---|---|---|
| 引擎起来了 | `Get-Process msedgewebview2` 计数（应十几个） | WebView2 初始化成功、页面在渲染 |
| 预热生效 | 目标临时换成 `cmd.exe /c timeout /t 14 /nobreak`，T+3.5 s 查 `Get-Process timeout` | 动画还在播时目标已被拉起 |
| 自动退场 | `Start-Process -PassThru` + `HasExited` 轮询计时 | `done` 收到且启动动作完成 |
| 窗口真是窗口不是全屏 | `EnumWindows` 按 PID 枚举 + `GetWindowRect` | 实际尺寸/位置（无边框窗口 `MainWindowHandle` 恒为 0，读不到）|

这些都是**进程级**证据。从 WSL 启动的 Windows GUI 窗口落在隔离窗口站，截图只能拿到壁纸，
所以**必须明确告诉用户哪一步只有他双击才能确认**，不要把进程级验证说成效果验收。

## 8. 窗口几何：居中的普通窗口，不要全屏

**这是本用户的明确规格，不是可选项。** 最初做成全屏无边框铺满，被纠正为
「播放界面不是固定全屏，而是在应用界面里」——全屏盖住任务栏、像劫持了整个桌面。

- `FormBorderStyle.None` + `StartPosition.CenterScreen` + `ClientSize = new Size(w, h)`，
  默认 **1280×820**；`w=` / `h=` 进 ini（屏幕尺寸和习惯差异很大，不要写死）。
- 目标应用若是无边框自定义标题栏（Electron 的 `titleBarStyle:'hidden'`），动画窗口也要
  无边框才观感连续，再加 Win11 圆角：

```csharp
[DllImport("dwmapi.dll")]
static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int val, int size);
// OnHandleCreated 里：
int pref = 2;   // DWMWCP_ROUND
DwmSetWindowAttribute(this.Handle, 33, ref pref, sizeof(int));
```

- 加 **Esc 跳过**：`KeyPreview = true`，`KeyDown` 里判 `Keys.Escape` → 直接拉起目标并关闭。
  5 秒里用户想跳过时不该被迫等。
- **动画页要能适应非 16:9**（比例由用户改）。用 `vw`/`vh` 定位的元素在 1280×820 下会重排，
  交付前按目标窗口尺寸截一张确认版式没崩。

**验收注意**：`CenterScreen` 的位置**不要拿物理像素反推**。2560×1440 @150% 缩放时逻辑分辨率
是 1706×960，1280 宽的居中窗口落在 `left=213` 而不是 320 —— 算不吻合不代表居中有 bug。

