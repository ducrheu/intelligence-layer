# 小雅 / 理工智课 接口地图

全部为 2026-09-16 在 `whut.ai-augmented.com` 上实测记录（课程「数据仓库与数据挖掘」，
group_id `7056039952705969169`）。不同学校是同一套系统，只有域名和 `client_id` 不同。

## 域名与登录

| 用途 | 地址 |
|---|---|
| 课程站 | `https://<school>.ai-augmented.com/app/jx-web/...` |
| 统一登录 | `https://infra.ai-augmented.com/app/auth/oauth2/login?...&redirect_uri=https://<school>.ai-augmented.com/api/jw-starcmooc/user/authorCallback...` |

课程 URL 形状：

```
https://<host>/app/jx-web/mycourse/<courseId>/resource/<nodeId>
https://<host>/app/jx-web/mycourse/<courseId>/resource/<父nodeId>/<nodeId>   # 点开具体资源后
```

`courseId` 就是所有接口的 `group_id`。

登录态落在 cookie `WT-prd-access-token` / `WT-prd-refresh-token` 上，但**接口还要一个
自定义 `authorization` header**，只用 cookie 调 `/api/jx-iresource/...` 会返回
`Unauthorized`（纯文本，不是 JSON，`JSON.parse` 会炸）。

## 课程资源

| 接口 | 说明 |
|---|---|
| `GET /api/jx-iresource/resource/queryCourseResources/v2?group_id=<courseId>` | 整棵课程树。`data[]` 里每个节点带 `id / parent_id / name / type / mimetype / resource_type`，根节点 `name == "root"` |
| `GET /api/jx-iresource/resource/queryResource/v3?node_id=<nodeId>&group_id=<courseId>` | 单节点详情。**`quote_id` 是真正的文件句柄**，另有 `disk_url`（指向内网 `file_access`）、`mimetype`、`download` 权限位 |
| `GET /api/jx-iresource/resource/queryStatus?quote_id=<quoteId>&type=<n>` | 文件是否还在（`data.disk_status === 1` 才可下） |
| `POST /api/jx-iresource/resource/history/user/view` | 浏览记录上报，不需要复刻 |

节点类型（实测，非官方文档）：

| `type` | 含义 |
|---|---|
| 1 | 目录 / 章节 |
| 6 | 上传的文件（pdf、pptx 等，`mimetype` 有值） |
| 8 | 教学任务 / 讨论（`resource_type 10`） |
| 9 | 媒体（mp4 等，`mimetype` 为 null） |

`resource_type`：1 = pdf，2 = pptx，5 = mp4，10 = 任务。

## 下载

```
GET /api/jx-oresource/cloud/file_down/<quoteId>/v2?filename=<encodeURIComponent(name)>
  -> data.download_url   # oss.ai-augmented.com 上的短时效签名地址
     data.size           # 字节数，用来校验
```

拿到 `download_url` 后，页面里 `<a download>` 点一下交给浏览器下载即可（不要自己去
curl，签名串是凭证，也别打印出来）。

## 踩过的坑

- **`/api/jx-oresource/cloud/file_access/<quoteId>`**（`disk_url` 指向的那个）在浏览器里
  直接请求会返回 HTML「该资源不支持预览」，不是下载入口。
- **PPT 在线预览走第三方 ow365**（`x1.ow365.cn/?i=...&furl=<加密串>`）。`file_url/<quoteId>`
  返回的 `url` 字段是 `is_encryption: true` 的加密串，**不是 URL**，解密在 ow365 侧，这条路拿不到文件。
- 页面结构图是**画在 iframe 里的 SVG**（`.mindmap-paper iframe`），同源，可以直接
  `contentDocument` 读节点文字，比截图 OCR 靠谱。
- 页面上有个「当前页面显示区域较小」的 ant-modal 会挡住登录表单，登录前先点掉
  「知道了」。
- 有的资源页顶部会弹「文件预览确认」（确定 / 取消），点「确定」才会真正预览。

## 「课程概况」里的三块常是空的（2026-10-10 实测）

`课程概况`（前端路由 `/mycourse/<courseId>/home`）有 `*课程教学大纲 / *教学进度计划 / *考核方式` 三个
ant-collapse 折叠面板，**展开后内容全空**（star 前缀表示「必填但老师没填」）。别为这三块反复试点击 ——
一次读完按钮文本就能确认平台侧没公布考核方式，要成绩构成只能问老师或看教务系统。
`我的学情`（`/mycourse/<courseId>/scores`）给的是签到/任务完成度/学习时长，也不含成绩权重。
