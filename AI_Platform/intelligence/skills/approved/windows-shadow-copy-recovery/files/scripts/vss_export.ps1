# 枚举 Windows 卷影副本，并把其中指定文件的旧版本导出到临时目录（需管理员）。
# 从 WSL 调起（用户桌面会弹 UAC）：
#   powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','C:\Users\<u>\AppData\Local\Temp\vss_export.ps1'"
# 结果：同目录 report.txt 记录每份快照的导出情况；导出的文件 mtime 就是快照时刻。

$ErrorActionPreference = 'Continue'
$dir = Join-Path $env:TEMP 'vss_probe'
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$out = Join-Path $dir 'report.txt'
"== run at: $(Get-Date -Format s) ==" | Out-File -Encoding utf8 $out

# 注意：vssadmin 输出随系统语言变化，只能按设备路径正则提取，不要匹配英文标签
$text = (vssadmin list shadows 2>&1 | Out-String)
$text | Out-File -Encoding utf8 -Append $out
$paths = [regex]::Matches($text, '\\\\\?\\GLOBALROOT\\Device\\HarddiskVolumeShadowCopy\d+') |
         ForEach-Object { $_.Value } | Select-Object -Unique
"== shadow copies found: $($paths.Count) ==" | Out-File -Encoding utf8 -Append $out

# 改成你要找回的文件；路径相对卷根（没有盘符）。
# 每条提权都要用户再点一次 UAC，所以把同一应用可能用得上的文件一次列全（多导几百 KB 成本极低）：
#   主数据库 + 密码库 Login Data / Login Data For Account + 表单库 Web Data + Preferences + 应用专属快照目录
# 漏一个文件 = 多一次 UAC 打扰。
$targets = @(
  'Users\HUYI\AppData\Local\Microsoft\Edge\User Data\Default\Network\Cookies',
  'Users\HUYI\AppData\Local\Microsoft\Edge\User Data\Default\History',
  'Users\HUYI\AppData\Local\Microsoft\Edge\User Data\Default\Login Data',
  'Users\HUYI\AppData\Local\Microsoft\Edge\User Data\Default\Login Data For Account',
  'Users\HUYI\AppData\Local\Microsoft\Edge\User Data\Default\Web Data',
  'Users\HUYI\AppData\Local\Microsoft\Edge\User Data\Default\Preferences'
)

$i = 0
foreach ($p in $paths) {
  foreach ($rel in $targets) {
    $src = $p.TrimEnd('\') + '\' + $rel
    $dst = Join-Path $dir ("snap{0}_{1}" -f $i, (Split-Path $rel -Leaf))
    try {
      Copy-Item -LiteralPath $src -Destination $dst -Force -ErrorAction Stop
      $sz = (Get-Item -LiteralPath $dst).Length
      $mt = (Get-Item -LiteralPath $dst).LastWriteTime
      "OK  $src -> $dst  ($sz bytes, snapshot mtime $mt)" | Out-File -Encoding utf8 -Append $out
    } catch {
      "NO  $src : $($_.Exception.Message)" | Out-File -Encoding utf8 -Append $out
    }
  }
  $i++
}
"== done ==" | Out-File -Encoding utf8 -Append $out
