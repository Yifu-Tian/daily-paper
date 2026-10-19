# Ego Catching Research Radar

面向 **机器人机载第一视角下，移动／飞行物体的抓取与接取** 的中文图文日报。
OpenArm/OpenArmX 为应用背景；同时关注时延、预测不确定性、遮挡、sim-to-real、接触与接后保持。

GitHub Actions 在纽约时间每天 **07:00 生成，08:30 发布**，自动跟随夏令时。
`github-actions[bot]` 创建图文 Issue，指派并 @`Yifu-Tian`；邮件由 GitHub 官方通知系统发送。
无需本机开机，也无需 Gmail 自发邮件或 SMTP 密码。Actions 排队可能使实际发布时间晚于计划时间。

## 日报内容

每篇精读保留论文题目、作者／单位、arXiv 与 PDF 下载、Project／Code、problem formulation、
观测和动作、pipeline 每个模块的具体方法、训练数据与监督、实验结果及分析、中立的 robotics
reviewer judgment，以及可迁移到 OpenArm 的机制和最小实验。通常配两张注明出处的原图：
完整方法图和关键实验图／表。仿真、真机、接触与稳定保持分开说明。

论文之后补充相关推文、talk、视频、项目／代码、数据集、博客等，说明讲什么、研究启发、访问链接
和实际读取层级。不会把未观看的视频当作看过，也不会以发现卡替代完整论文分析。
优先近 7 天，必要时扩展至 30 天；安静时期最多补读一篇明确标为旧文的基础工作。没有合适论文时直说。

## 首次启用

1. 在 [Actions Secrets](https://github.com/Yifu-Tian/daily-paper/settings/secrets/actions)
   添加 `GEMINI_API_KEY`。密钥只放在 Secret，不能写入代码、Issue 或提交。
2. 在 [GitHub Notifications](https://github.com/settings/notifications) 开启参与／被 @ 的邮件通知。
   如果要指定 GWU 邮箱，先确认该邮箱已在 GitHub 验证，再配置通知默认邮箱或该仓库的 Custom routing。
3. 打开 [Daily Research Radar](https://github.com/Yifu-Tian/daily-paper/actions/workflows/radar.yml)，
   选择 **Run workflow → sample**，测试图文 Issue 和 GitHub 官方邮件通知；
   选择 **full** 则立即执行一次真实检索、全文阅读和发布。

初次推送会自动测试样刊。样刊核读日期明确标注，不假装是当天新论文；重复运行不重复创建 Issue。
常规运行直接查询 arXiv API、GitHub 搜索和配置的作者／项目页，再把实际取得的材料及原始 PDF
交给 Gemini Interactions API，
阅读全文、图表与实验，输出结构化分析。Reviewer 判断另用原始 PDF 在新上下文中生成，
不向该步骤提供初稿的评价，以减少沿用初稿夸大措辞的风险；这仍是 AI 辅助评估，不能代替专家审稿。
Poppler 从相同 PDF 字节提取原图。
配置在 [config.json](config.json)，选题和证据要求在 [prompts/research.md](prompts/research.md)。
API 调用可能消耗相应项目额度；模型和论文数均可配置。
默认发现阶段不依赖 Google Search grounding 的额外额度。推文、talk 和视频仅覆盖这些公开来源
实际暴露的正文或链接；不声称订阅了全部 X 账号或看过所有视频。增加作者／项目来源可修改
`primary_resource_pages`。普通模型 API 仍须有可用额度。

## 验证与归档

```bash
python3 -m unittest discover -s tests -v
python3 run.py prepare        # Requires GEMINI_API_KEY; generates public summaries locally.
python3 run.py publish        # In Actions, uses its built-in GITHUB_TOKEN.
```

`archive/YYYYMMDD/` 保留 Markdown、结构化摘要、配图及来源记录。
已成功发布的 receipt 重建去重列表，失败不标为已交付；发布前还会通过 Issue 标记核对中断前的成功请求。
`archive/*_sample/` 为样刊。原始 PDF、API 响应与工作文件不提交公开仓库；`.work/` 是本地检索审计目录。

工作流会回读新 Issue，核对 bot 身份、正文标记和 assignee。这个检查证明 **GitHub 发布成功**，
不能代替最终邮箱送达验证；邮件是否发送、发往哪个已验证邮箱，取决于你的 GitHub 通知设置。
正式链路失败会发布明确标记的运行状态 Issue，不编造完成的论文分析。

GitHub 官方说明：[定时与时区](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)、
[通知邮件的参与／指派原因](https://docs.github.com/en/subscriptions-and-notifications/reference/email-notification-headers)。

## 部署权限

本地 Git 凭据需要被授权访问这个新仓库。若推送返回 HTTP 403，请在
[Fine-grained tokens](https://github.com/settings/personal-access-tokens) 中把仓库加入该 token 的
Repository access，并给予 Contents、Workflows、Actions、Secrets 的读写权限。
这些是推送、触发／检查运行和加密设置 API Secret 所需的部署权限，不是发送日报时的权限。
工作流本身只使用仓库提供的 `GITHUB_TOKEN`，权限为 Contents 与 Issues；不保存个人 Git token。
