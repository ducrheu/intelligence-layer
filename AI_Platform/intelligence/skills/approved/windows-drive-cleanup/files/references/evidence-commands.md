# 取证命令速查

```bash
# 哪些程序在跑
tasklist=/mnt/c/Windows/System32/tasklist.exe
"$tasklist" | grep -iE "kugou|iqiyi|qqlive|steam|weixin|pycharm|mysql|ollama"

# 读快捷方式目标（判断哪个副本在用）
strings -e l "$LNK" | grep -iE "pycharm|\.exe|D:"

# 目录是否含本体程序 / 卸载器
ls "$DIR" | grep -iE "uninstall|^[A-Za-z]*\.exe$"

# 目录里有没有用户产出（决定删整目录还是只删 .venv）
find "$DIR" -maxdepth 2 -type f -printf '%TY-%Tm-%Td %p\n' | sort -r | head

# 应用是否装在别处
find /mnt/c/Program\ Files "/mnt/c/Users/HUYI/AppData/Local" -maxdepth 2 -iname "*Xmind*"
ls -R "/mnt/c/Users/HUYI/AppData/Roaming/Microsoft/Windows/Start Menu" | grep lnk

# 缓存目录的自带说明（UTF-16LE 常见）
iconv -f UTF-16LE -t UTF-8 "$DIR/目录说明.txt"

# 回收量测量
df --output=avail -m /mnt/d | tail -1
```
