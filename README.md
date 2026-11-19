# AI 资讯早报

每天香港时间 07:25 启动，目标 08:00 前发布上一完整自然日的中文早报。GitHub Actions 运行 Python，OpenAI Responses API 搜索中英文报道并逐篇生成摘要，GitHub Pages 提供静态页面。访问网页无需 API 密钥。

## 部署

1. 将本项目推送至独立的 GitHub 仓库 `ai-daily-brief` 的默认分支。工作流需有提交日报数据的权限。
2. 在领取额度的 OpenAI API 组织中选择项目。将项目密钥保存为仓库的 Actions Secret `OPENAI_API_KEY`。密钥仅注入生成步骤。组织余额和有效期见 [OpenAI 账单](https://platform.openai.com/settings/organization/billing/overview)。
3. 在仓库 Settings → Pages 选择 GitHub Actions。打开 Actions → AI 资讯早报 → Run workflow，默认分支上首次运行即可发布。任务摘要中可取得 Pages 地址。
4. 以后使用同一地址阅读。单期地址为 `issues/YYYY-MM-DD/`，往期索引为 `archive.html`。补跑旧日期会保留最新一期首页。

定时表达式为 UTC 每天 23:25，执行时按香港自然日计算新闻日期。GitHub 可能延迟调度。手动补跑可显式指定日期。

## 本地运行

在仓库根目录使用 Python 3.12 或更新版本。安装依赖后，通过安全环境变量或本地已忽略的 `.env.local` 提供项目密钥。

```sh
python -m pip install -r requirements.txt
python -m ai_brief
python -m ai_brief --date 2026-11-18
python -m ai_brief --render-only
python -m unittest discover -s tests
```

`--root` 可指定数据与输出目录。生成结果位于 `dist/`。部署以目录方式提供服务；本地可用 `python -m http.server 8000 --directory dist` 预览。

## 选题和计费

- `gpt-6.2-astra` 使用内置 `web_search` 分别检索中英文报道。每轮最多 4 次工具调用，优先抓取被引用的链接。只接受有明确时区的发布时间和足够正文的公开文章。缺少可核实发布时间的来源可能漏选。
- `gpt-6.2-sol` 根据文章材料判断目标日进展、聚合同一事件和同源转述。按入选来源的独立报道数排序，同分优先原始发布。逐篇摘要以原文为依据，校验摘要长度和证据摘录，最多展示 8 条。编辑判断包括模型推断，独立报道数限于本期检索样本。
- `progress/` 存放中断后可复用的链接、选题、已完成摘要与用量。`editions/` 保存完成的日报 JSON。只将 HTML 和 CSS 部署至 Pages。整期失败会保留上次站点；额度耗尽后工作流失败并保留断点。成功检索但没有合格新闻时发布空刊。
- 每期 JSON 和生成日志记录分模型请求数、输入和输出 token 以及搜索动作数。第一周按专用项目核对 [API Usage](https://platform.openai.com/usage)。未收到响应的请求无法由本地完整计量，以平台账单为准。[官方价格](https://developers.openai.com/api/docs/pricing) · [额度范围](https://developers.openai.com/api/docs/guides/chatgpt-api-credits)
