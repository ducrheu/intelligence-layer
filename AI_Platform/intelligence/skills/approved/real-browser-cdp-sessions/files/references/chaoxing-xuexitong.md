# 超星学习通（chaoxing）— 登录与任务

## 登录页

`https://passport2.chaoxing.com/login?fid=&refer=`

三种方式：手机号 / 超星号 + 密码、短信验证码、**学习通 App 扫码**。相关元素：

- 账号输入 `#phone`（placeholder「手机号/超星号」），密码 `#pwd`（type=password）。
- 二维码 `#qrCode img`，选择器 `img[src*=createqr]`；`src` 形如
  `https://passport2.chaoxing.com/createqr?uuid=<uuid>&fid=-1` —— **uuid 就从这里抠**。
- 页面里还有一堆 `type=hidden` 的 input（`fid`/`pid`/`refer`/`validate`/`uuid`/`enc` …），别当可见字段处理。

## 扫码结果轮询

`GET https://passport2.chaoxing.com/checkqr?uuid=<uuid>&_t=<毫秒时间戳>`，带 cookie。

**必须在 passport2 源下的页面里发这个请求**：从 `about:blank` 发是 `NetworkError`（null origin）。所以轮询那一轮先把标签页停在 `passport2.chaoxing.com` 上，再 XHR/fetch `checkqr`。

码过期或 uuid 被轮换后，checkqr 不再认得旧 uuid，扫码就永远落不下来 —— 重新取新码，别在旧 uuid 上重试。

## 登录态判据

访问 `https://i.chaoxing.com/`：未登录会 302 回
`https://passport2.chaoxing.com/login?fid=&newversion=true&refer=...`。

- 只有会话 cookie：`JSESSIONID`、`route`、`source`、`retainlogin` → **没登录**。
- 出现 `_uid` / `uf` / `vc3` / `UID` / `fid` / `lv` 之类 → 已登录。

门户 / 课程页在 `i.chaoxing.com`，课程内容与任务在 `mooc1.chaoxing.com`。

## 脚本用法

```bash
PY=<有 websockets 的 python>
BH_AGENT_WORKSPACE=/tmp/qr $PY scripts/chaoxing_qr.py        # 新开或复用 passport2 标签页，出码
BH_AGENT_WORKSPACE=/tmp/qr $PY scripts/chaoxing_qr.py reload # 强制刷新出新码
```

输出 `TARGET_ID` / `UUID` / `RECT` / `SAVED`。

- **复用已存在的 `passport2.chaoxing.com` 标签页**（脚本默认行为）：重开标签页会换 uuid，旧码作废。
- 拿到 `TARGET_ID` 后，后续几轮都用它：`cookies <tid> https://i.chaoxing.com`、`shot`、`eval`，**不要再 `new` 一个登录页**。

## 课程内导航（登录之后）

层级：`i.mooc.chaoxing.com`（门户）→ `mooc1-N.chaoxing.com`（课程）。**N 会变**，别写死。

- **课程列表**：门户首页 `i.mooc.chaoxing.com/space/index` 把课程列表放在 iframe 里（`https://mooc1-N.chaoxing.com/visit/courses?s=<token>`）。跨子域取不到 iframe 内容 → 直接把这个 iframe 的 `src` 拿去当当前页导航。课程卡片是
  `a[href*="/visit/stucoursemiddle?courseid=<courseId>&clazzid=<clazzId>"]`，href 里的 `courseId` / `clazzid` 后面各处都要用，先存下来。
- **课程左侧菜单**是「相对路径塞在 `data` 属性里」的写法（`<a href="javascript:;" data="/work/getAllWork?...">`），抠出来后拼上 host 就能跳：
  - 作业 `data="/work/getAllWork?classId=&courseId=&isdisplaytable=2&mooc=1&ut=s&enc=&cpi=&openc="`
  - 考试 `data="/exam-ans/exam/test?classId=&courseId=&ut=s&enc=&cpi=&openc="`
  - 资料 `/mooc-ans/coursedata?...&type=1`
  - 签到活动（独立域）`mobilelearn.chaoxing.com/widget/pcpick/stu/index?courseId=&jclassId=` → 页面显示「进行中(n) / 已结束(n)」。
- **别自己拼 `/mooc-ans/mooc2/work/list?...`** —— 参数不全时服务端直接回「无权限的操作！」。用菜单里给的那条路径。
- **作业列表**（`/work/getAllWork?...`）：每条作业是一个 `.titTxt` 块，父元素 innerText 里能抠出「开始时间 / 截止时间 / 作业状态（待做 | 已过期）」。做作业按钮是 `a.inspectTask[data="<workId>"][data2="<workAnswerId>"]`。
  列表里常有截止在一年后的**重复空壳**（老师复制出来的，状态同为「待做」）—— 按截止时间过滤后再报告，别把它们算进待办。
- **进作业**：click 那个 `a.inspectTask` → `/mooc-ans/work/doHomeWorkNew?courseId=&classId=&workId=&workAnswerId=&...&enc=<该题专属>&standardEnc=<该题专属>`。**`enc` / `standardEnc` 每题不同**，所以必须从列表页点进去，手拼 URL 会失败。题干、题量、必答点清单都在这个页面的 innerText 里，一次就抠全。
- **资料**里的文件不是直链，是超星云盘查看器：`onclick="toOpen('<文件名>','pdf',<objectId>,...,'<token>',...)"`。想拿原件得走它的下载流程，别指望 `curl` 那个 onclick。

### 新版 mooc2-ans 课程页（登录之后的另一个版式）

`https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/stu?courseid=&clazzid=&cpi=&enc=&t=&pageHeader=0&v=0&hideHead=0`

- 左侧菜单是 `<a title="作业|考试|章节|任务|资料|讨论" data-url="<模块基址>" href="javascript:void(0);">`，父 `<li dataname="zy" pageheader="8" data="…">`。**`data-url` 只有模块基址** —— `enc` / `cpi` / `stuenc` 要点一下才在 iframe 的 `src` 里长出来。所以：click 菜单项 → 读 `iframe.src` → 把那条完整 URL 导航到自己的标签页（跨域读不到 iframe 内容，但 cookie 跟着走）。
- 各模块点击后的 iframe `src`：
  - 作业 `mooc1.chaoxing.com/mooc2/work/list?courseId=&classId=&cpi=&ut=s&t=&stuenc=&enc=`
  - 章节 `mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse?courseid=&clazzid=&cpi=&ut=s&t=&stuenc=`
  - 任务 `mobilelearn.chaoxing.com/page/active/stuActiveList?courseid=&clazzid=&cpi=&ut=s&t=&stuenc=&fid=`
  - 资料 `mooc2-ans.chaoxing.com/mooc2-ans/coursedata/stu-datalist`
  - 讨论 `groupweb.chaoxing.com/course/topic/topicList?courseid=&clazzid=&cpi=&ut=s&t=&stuenc=&bbsid=&supportAI=true&enc=`（**`bbsid` / `cpi` / `enc` 缺一个就回「非法请求,参数不能为空」**，别裸开 `topicList`）
  - 错题集 `mooc2-ans.chaoxing.com/mooc2-ans/wrongque/page`
  - 学习记录 `stat2-ans.chaoxing.com/study-data/index`
  - 分组任务（实验报告册）`mobilelearn.chaoxing.com/page/renwuNew/stuRenwuList`
  - AI助教 `mooc1.chaoxing.com/course-ans/ai/getStuAiWorkBench`
- **「作业」模块可以是 0/0「暂无作业」**（老师改用「任务」发布时就是这样），此时作业只在任务列表里 —— 别据它为空就答「没有作业」。
- **任务列表**每条：`<li activeid="…" activetype="77" activestatus="1" content="{…}">`，文本里是任务名 + 「剩余:N天」或「结束时间:MM-DD HH:mm」。`activetype` 对照：**77 = AI 实践作业**，2 = 签到，11 = 选人。`content` 属性的 JSON 里 `sourceConfig` 带 `startTime`/`endTime`（毫秒）、`publishRelationUuid`、`libraryType`，`stuUrl`/`teaUrl` 指 `ai-evaluate/v2/redirect/active/{stu,tea}`。
- **AI 实践作业作答页**：`mooc2-ans.chaoxing.com/mooc2-ans/ai-evaluate/v2/answer?courseid=&clazzid=&cpi=&publishRelationUuid=`（标题「AI实践-代码编辑 作答」）。题面、达标线（如「多次练习最高分达到 70 分」）、可作答次数、练习起止时间都在 innerText 里。
- **章节树一次读全**：每个知识点 `div.chapter_item[id=cur<knowledgeId>]`，`onclick="toOld(<courseid>, <knowledgeId>, <clazzid>, 0)"`，内部 `input.knowledgeJobCount` 的 value = 该节待完成任务点数，`.catalog_points_yi` 同值。课页顶部「已完成任务点: n/m」是全课口径，逐节加总应与之吻合。
- **进单节**：`mooc1.chaoxing.com/mycourse/studentstudy?chapterId=<knowledgeId>&courseId=&clazzid=&cpi=&enc=&mooc2=1&hidetype=0&fanyaVersion=0&openc=`；卡片在跨域 iframe `mooc-ans/knowledge/cards?clazzid=&courseid=&knowledgeid=&num=0&ut=s&cpi=&v=&mooc2=1&isMicroCourse=false&editorPreview=0`（单独开标签页读；附件有的是 PDF 查看器 `ananas/modules/pdf/index.html`，有的是 PPT）。

## 「作业 / 任务 / 分组任务 / 讨论」是四个互不相通的入口

同一门课的同一批任务只会出现在其中一个里，清点前四个都要看。**用户在界面上点名的任务如果在这些入口都查不到，立刻停下来要一张他看到该任务的截图**，不要继续顺着接口和入口猜 —— 盲猜很烧轮次、命中率还低。

分组任务（实验报告册）单独一枚：

- 新版列表页本体只列「班级名 / 打开旧版 / 暂无任务」，数据走 `mobilelearn.chaoxing.com/v2/apis/active/student/activelist?fid=&courseId=&classId=`，**`activeTypes=35` = 分组任务**；不带 `activeTypes` 则返回全类型（77=AI 实践作业、2=签到、11=选人）。
- 页面上的「打开旧版」跳 PBL 系统 `fanyapbl.chaoxing.com/pbl/list?courseId=&ut=s`（表头：项目名称 / 研究时间 / 我的项目组 / 公开小组 / 被评小组）。
- **两个入口可能对同一个班同时为空**（`activeList: []` + PBL 零行）。空 ≠ 这门课没有分组任务：分组任务常挂在**章节任务点**上，只在 App 或某个特定入口露出。**停在这里去要截图，别把「空」当成结论报给用户。**
- 点任务列表里带 `taskuserid` 的章节条目会开到 `task.chaoxing.com/userStudyPlan/myPlanList?returnType=2&encryTaskUserId=`（标题「我的任务点」：该章学习任务说明 + 完成度 + 「收下奖励」），里面没有分组任务的子项。讨论模块里的是研讨题（「任务背景 + 讨论题目」），不是作业也不是分组任务，统计时清出去。

AI 实践作业（代码题）与 AI 互动故事（对话式）的作答、提交与评分接口，见 `references/chaoxing-ai-evaluate.md`。

## 任务类型与能做的事

课程下的「任务」通常分：

- **视频 / 章节进度** —— 机械性，可代做。
- **签到** —— 有窗口期，常带定位或手势 / 二维码，异地代签容易失败，先问清是哪种。
- **作业** —— 默认整篇做完并提交，简答 / 设计题的正文也照写（见 SKILL.md）。提交后回读确认状态变成「待批阅」。
- **章节测验 / 考试** —— **不代做**（见 SKILL.md 的红线）。把截止时间和任务名报给他，让他自己在手机上做最稳。

## 答题与提交（UEditor）

答题框是 **UEditor**，不是普通 textarea：

```js
const ed = UE.getEditor(document.querySelector('textarea').id); // textarea id 形如 answer<uid>
ed.setContent('<p>…</p>'); // 内容用 <p> 分段，别塞裸换行
ed.sync();                 // sync 之后 textarea.value 才被写入
```

- 编辑器默认可能不显示；先点 innerText 为「填写答案」的元素。
- 「暂时保存」= `a#tempsave`（onclick `noSubmit()`）；「提交作业」= onclick `validateTime(classId,courseId)`，**点完必弹确认框，要再点一次确定**。
- **字数按平台计数器卡**：页面实时显示「已输入 N 个字」，`N ≈ 汉字数 + 40`（`RFM` / `XGBoost` / `65%` / `APP` 这类拉丁数字串也计）。要卡进「500—800 字」就照 N 调：先填一次、读回 N、按差额删。
- **提交后回读**：列表里该条变「作业状态：待批阅」（按钮从「做作业」变「查看」）；内容用查看地址 `/mooc-ans/work/selectWorkQuestionYiPiYue?…&workId=…&workAnswerId=…` 回读；提交后 `workAnswerId` 从 `0` 变成真实 id，可作旁证。
- **列表渲染会滞后**（条目少几行、已交的条目暂时看不见），别据此判断状态，重载一次再看。
