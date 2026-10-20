# Windows 屏幕捕获 / 用户媒体落盘位置（从 WSL 读）

`%USERPROFILE%` = `/mnt/c/Users/<用户名>`；`%LOCALAPPDATA%` = `%USERPROFILE%\AppData\Local`；`%APPDATA%` = `%USERPROFILE%\AppData\Roaming`。

## 截屏

| 位置 | 说明 |
|---|---|
| `%USERPROFILE%\Pictures\Screenshots\屏幕截图 YYYY-MM-DD HHMMSS.png` | 默认相册。PrtSc / Win+Shift+S **点保存**后的落点。中文系统里目录名也是英文 `Screenshots` |
| `%LOCALAPPDATA%\Packages\Microsoft.ScreenSketch_8wekyb3d8bbwe\TempState\Snips\屏幕截图 YYYY-MM-DD HHMMSS.png` | **Win+Shift+S 截了但没保存（只是复制到剪贴板）的临时图**。相册里看不到，条目会被系统清理 |
| `%USERPROFILE%\Pictures\屏幕截图\`、`%USERPROFILE%\OneDrive\图片\屏幕截图\` | 部分机器/开了 OneDrive 同步的另存点 |
| `%USERPROFILE%\AppData\Roaming\Hermes\composer-images\` | 拖进 Hermes 桌面端聊天框的图 |
| `~/.hermes/images/upload_YYYYMMDD_HHMMSS_*.png` | 通过 Hermes 消息上传的图（WSL 侧，名字自带本地时间） |

第三方截图工具（Snipaste / PixPin / QQ / 微信）各自有输出目录，用户改过默认值就落在别处——找不到时问一句比全盘猜快。

## 录屏

| 位置 | 说明 |
|---|---|
| `%USERPROFILE%\Videos\Captures\` | Xbox Game Bar（Win+G / Win+Alt+R）默认目录，可能是空的 |
| `%USERPROFILE%\Videos\屏幕录制\屏幕录制 YYYY-MM-DD HHMMSS.mp4` | 中文 Windows 的录屏目录（英文系统是 `Videos\Screen Recordings`）。**按名字模式搜，别写死英文名** |
| `%LOCALAPPDATA%\Packages\Microsoft.ScreenSketch_8wekyb3d8bbwe\TempState\Recordings\YYYYMMDD-HHMM-SS.mmm.mp4` | 屏幕草图/截屏工具的录屏暂存区，**文件名是 UTC**（`20260927-1419` = 本地 22:19）。判定窗口用 mtime，不用文件名 |

**副本判定**：`Videos\屏幕录制\` 与 `TempState\Recordings\` 里的同一段录屏体积常常完全一致（可能是同一份/硬链接）→ `md5sum` 两边确认后再报告，别列成两段。

## 聊天里收到的媒体

| 位置 | 说明 |
|---|---|
| `%USERPROFILE%\xwechat_files\<wxid>_<hash>\msg\video\YYYY-MM\<hash>.mp4` | 微信收到的视频；同目录还有 `<hash>_thumb.jpg`、`<hash>_raw.mp4`（未转码原件）。`<hash>.jpg` 是封面 |
| `%USERPROFILE%\xwechat_files\<wxid>_<hash>\business\favorite\temp\微信图片_YYYYMMDDHHMMSS_N.jpg` | 收藏/转存出来的图片，**文件名里的时间戳是本地时间**，有时用 |
| `%USERPROFILE%\Documents\WeChat Files\`、`Tencent Files\` | 旧版微信 / QQ 的落点 |

## 排除噪音

这些目录里全是当天 mtime 的**非用户媒体**，扫出来要过滤掉：`AppData\Local\Temp\`、`AppData\Local\Microsoft\Windows\ActionCenterCache\`、各类 `*Cache*` 软件图片缓存（音乐/输入法/商店图标）。
判定要点：真正的捕获文件名带**时间戳**（`2026-09-27 211157` 或 `_20260927091828_`），缓存文件是裸哈希或软件图标名。
