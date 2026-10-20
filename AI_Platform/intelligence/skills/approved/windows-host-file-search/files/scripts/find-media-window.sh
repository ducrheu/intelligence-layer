#!/usr/bin/env bash
# 按 mtime 时间窗口在 Windows 主机 + WSL 家目录里找图片/视频（只读）。
#
# 用法:
#   find-media-window.sh "<起>" "<止>" [根目录 ...]
# 例:
#   find-media-window.sh "2026-09-27 21:00" "2026-09-27 23:00"
#   最近两小时: find-media-window.sh "$(date -d '-2 hours' '+%F %H:%M')" "$(date '+%F %H:%M')"
#   全天:       find-media-window.sh "2026-09-27 00:00" "2026-09-28 00:00"
#
# 输出列: 本地 mtime (精确到秒) | 字节 | 路径  —— 按时间排序。
# 注意: 时间窗口以 mtime 为准。ScreenSketch 的录屏文件名是 UTC,
#       与本机本地时间差 8 小时, 不要按文件名判断属于哪个窗口。
# find 遇到不可访问的 Windows 目录会返回 exit 1, 属正常, 不是失败。

set -u

START="${1:?起始时间, 例 "2026-09-27 21:00"}"
END="${2:?结束时间, 例 "2026-09-27 23:00"}"

if [ "$#" -gt 2 ]; then
  shift 2
  ROOTS=("$@")
else
  ROOTS=()
  for d in /mnt/c/Users/*/; do
    case "$d" in
      */Public/|*/Default/|*/Default\ User/|*/All\ Users/) continue ;;
    esac
    [ -d "$d" ] && ROOTS+=("$d")
  done
  [ -d /mnt/d ] && ROOTS+=("/mnt/d")
  [ -d "$HOME" ] && ROOTS+=("$HOME")
fi

if [ "${#ROOTS[@]}" -eq 0 ]; then
  echo "没有可扫描的根目录" >&2
  exit 1
fi

for root in "${ROOTS[@]}"; do
  find "$root" -maxdepth 8 -type f \
    \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.bmp' \
       -o -iname '*.webp' -o -iname '*.gif' -o -iname '*.heic' \
       -o -iname '*.mp4' -o -iname '*.mkv' -o -iname '*.mov' -o -iname '*.avi' \
       -o -iname '*.flv' -o -iname '*.wmv' \) \
    -newermt "$START" ! -newermt "$END" \
    -printf '%TY-%Tm-%Td %TH:%TM:%TS\t%10s\t%p\n' 2>/dev/null
done | sort
