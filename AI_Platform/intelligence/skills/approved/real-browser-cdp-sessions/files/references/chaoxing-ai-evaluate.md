# 超星 AI 实践作业（代码题）与 AI 互动故事（对话式）

两类新式任务都在 `mooc2-ans` 这边，与老的 UEditor 作业是两套完全不同的东西。共同点：**界面上看不到分数（有的连提交按钮都没有），真实状态与分数只能自己走接口取。**

## 通用：状态与分数的接口

两类的入口页面不同，但状态查询都落在同一条：

```
GET /mooc2-ans/ai-evaluate/v2/answer/load-data
    ?courseid=&clazzid=&cpi=&libraryUuid=&publishRelationUuid=&type=
```

`type=6` = 互动故事；代码题类用页面 URL 上那个 `publishRelationUuid` 即可。返回里有 `answerScore`（当前分）/ `answerCount` / `scoreCount` / `remainAnswerCount` / `remainScoreCount` / `recordUuid` / `recordStatus` / `answerRecords[]`（历次分数与提交时间）/ `publishSetting.reachStandard`（达标线）。

**注意参数大小写是混着来的**：`load-data` 吃小写 `courseid`/`clazzid`，同一个 `submit` 接口也用小写，而 `evaluate/stream` 吃驼峰 `courseId`/`clazzId`。回「xxx为空」就说明名字写错了，换一种再试，别怀疑鉴权。

## AI 实践作业（代码题）— `/ai-evaluate/v2/answer`

页面：`mooc2-ans.chaoxing.com/mooc2-ans/ai-evaluate/v2/answer?courseid=&clazzid=&cpi=&publishRelationUuid=`（标题「AI实践-代码编辑 作答」）。题面、达标线、可作答次数、练习起止时间都在 innerText 里。

- **先选语言**：`STRONG.selectBoxLang` 点开，选项 `Golang / Java / Python2 / Python3.6.9 / Python3.12.12 / C++ / JavaScript / PHP`，点选目标项。
- **代码编辑器是 CodeMirror**：`document.querySelector('.CodeMirror').CodeMirror.setValue(code)`。
- **最大的坑：`textarea.program_textarea` 不是代码编辑器**，它是右下那个「程序键盘读取输入」（stdin）框，且有 2000 字上限。把几千字代码填进去的表现是：编辑器仍空白、而计数器显示 `5377 / 2000`（超限）。填完代码记得把 stdin 框清空。
- 按钮：`自测运行`（`SPAN.centerBtn`）/ `保存代码` / 右上 `开始评估`（`SPAN.purpleBgBtn`）。右上还有 `作答记录`。
- `自测运行` 只跑不评分，结果面板给「编译通过 / 运行时间 / 内存 / 程序输出」；`开始评估` 才是交卷，之后出 AI 评估面板：功能实现 / 代码质量 / 问题考虑完整性 / 创新与优化 四维，满分 100，达标线一般 70。
- **交前先在本地把答案跑一遍并与暴力枚举对拍**：这类题分值全押在正确性上，一次对拍能省一轮评估机会。

## AI 互动故事（对话式）— `aiInteractStory`

入口：`pcStudentIndex` →「开始故事」→ `pcDialogue`。每章是「章节说明 + 本章完成条件」，达成条件（或对话满 10 轮）即过关；章节进度与每章条件在左栏 `node-item` 里可一次读全。

推进节奏：点底部 `.nextArrow` 进对话模式 → 若有 `.goOnBtn`（文字「点击继续」）就先点它解锁输入（输入框 class 带 `messageInputLock` = 未轮到你）→ 输入并发送 → 等角色回复 → 条件达成显示「已达成本章完成条件…即将进行下一章」→ 再点 `.nextArrow` 进下一章。

- 输入框 `textarea.messageInput`；**发送键是内层 `span.sendBtn`**，点父 `.sendOptionBtn` 不触发。
- **必须用真实输入事件**：`Input.focus` 到该输入框 + `Input.insertText`。直接改 value 或 `execCommand` 不更新 Vue 的 v-model，点发送会静默无效（输入框里文字还在、轮数不变）。
- **单条消息有长度上限（实测 ~760 字，超出被静默截断）**：长论述拆成几条发，发完回读确认没被截。
- 结束标志：最后一条回复后出现「恭喜你已完成全部故事内容」。

### 提交与评分（页面不显示分，得自己走）

- 进故事 / 继续作答都会**恢复同一条记录**（`recordUuid` 不变）——「开始故事」不是重练。
- 走完最后一章只是把对话送到「恭喜你已完成全部故事内容」，**不会自动交卷、也不会自动评分**。要拿分得两步（都在页面里 fetch；交卷用表单编码）：
  1. 交卷：`POST /mooc2-ans/ai-evaluate/v2/answer/submit`，体 `courseid=&clazzid=&cpi=&recordUuid=` → `{"data":1,"status":true}`，`recordStatus` 变 1。
  2. 触发评分：`POST https://mooc2-ans.chaoxing.com/ai-ans/ai-evaluate/v2/evaluate/stream?courseId=&clazzId=&cpi=&recordUuid=&isPreview=0&aiEnc=`，头 `Accept: text/event-stream`。**第一遍返回 SSE 流（评分就在这一下产生）；再调回 `event:error` + 「任务已评估完成」。**`clazzId` 不能省（省了 `isPreview=0` 也凑不齐，当场 400）。
- 评分是异步的：调用后 `scoreCount` / `answerRecords` 要等几十秒才变。
- **再来一次**：`POST /mooc2-ans/ai-evaluate/story/answer-again`，体吃 `courseId&classId&clazzid&cpi&libraryUuid&publishRelationUuid&recordUuid&type`。**已提交的记录会被它拒掉，回「任务已经提交」** —— 同一条记录不能重刷；新记录必须把整个故事重跑一遍（每遍约 8 轮对话，几分钟），所以「多刷几遍拿最高分」是分钟级成本，不是点一下就完事。
- **达标判定看 `answerScore` 与 `publishSetting.reachStandard`，不要靠页面文案**；满分（如 100/100）之后再刷只是往 `answerRecords` 堆重复记录，**先报分数再问要不要刷**。

## 顺带：找这类隐藏接口的通用手法

1. 在页面里 `performance.getEntriesByType("resource")` 列当前路由已加载的 `.../js/<hash>.js`，curl 下来后 `grep -o "ai-evaluate/[a-zA-Z0-9_/-]*"`，接口名一次列全（`load-data` / `submit` / `evaluate/stream` / `answer-again` / `story/*` 都是这么翻出来的）。
2. 再真点一次对应按钮、用 CDP 的 `Network.requestWillBeSent` 事件确认「参数名 + 编码方式」，然后就能在页面上下文里直接 `fetch` 复现，不必再走 UI。
