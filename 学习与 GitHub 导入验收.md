# 学习与 GitHub 资料导入验收

## 已完成

- 公开 GitHub 扫描 → 固定 commit → 目录预览 → 用户勾选 → 本地资料导入。扫描阶段不下载文件正文。
- 资料使用现有 SQLite 全文索引；GitHub 文件保存来源快照、commit、固定 URL、分块起止行号。
- 重复 commit 的文件不会重复下载；新 commit 显示新增、修改、删除，旧版本保留。
- 单文件失败可继续其余文件；取消后状态为部分完成，成功资料保留，重试跳过已完成文件。
- 公开 URL、重定向、Token/Cookie、敏感配置和私钥拒绝；仓库内容不作为系统指令，也不执行脚本。
- 研究完成先保存报告，再异步生成学习建议；用户选择后正式加入已有学习项目。
- 学习完成后按开关和单元幂等创建一张关联复习卡，保存学习证据和 GitHub 行号。
- 复习支持反馈、可配置间隔、暂停、改期、编辑、历史备注和本地日期视图。

## 自动化结果

- 打包使用的虚拟环境执行 `python -m unittest discover -q`：96 项通过（46.250 秒）；包含用于模拟坏 PDF 的预期解析警告，以及一条已有 socket ResourceWarning，测试结果为 OK。
- 新增 `test_learning_flow.py`：预览选择、重复完成、重启、关闭自动复习、生成失败重试、伪造证据拒绝、手动卡片和旧数据迁移。
- 新增 `test_github_import.py`：固定 commit、README/docs/源码选择、全文检索与行号、重复导入、新版本差异、取消续传、单文件失败、敏感文件和 URL 安全。
- 真实公开仓库扫描与导入：`https://github.com/octocat/Hello-World/`，扫描得到固定 commit `7fd1a60b01f9`（完整 SHA 保存在隔离 SQLite），只导入用户选择的 `README`，未执行任何仓库内容。

## 限制

- GitHub API 未登录，受公开 API 限流影响；私有仓库、Token、LFS/二进制、超过限制的仓库和超过 1 MB 的文件暂不支持。
- 目前使用本地全文检索，向量检索仍是可替换接口。
- 学习建议的模型生成需要用户配置模型；夹具测试核对来源摘录，未把模型输出当作事实验证。
- 尚未在实体手机端开放 GitHub 导入、学习预览或复习接口；桌面端优先。

## 本轮真实 Windows 验收与交付

- WebView2 页面真实操作公开 Python 仓库 `https://github.com/pallets/itsdangerous/`，固定 commit `672971d66a2ef9f85151e53283113f33d642dabd`。
- 扫描 50 个文件，扫描后资料库为零条；用户选择全部可导入 docs（13 个）和 src 下 3 个 Python 文件，共 16 个，均成功保存。
- 搜索 `serializer` 得到命中；实际打开命中原文，显示固定 GitHub 来源、commit 和行号。研究与学习的资料权限均默认关闭。
- 重新创建服务打开同一隔离 SQLite，16 份资料及 complete 版本状态保留。真实验收记录：`build/github-webview-20261007-214300/results.json`；脚本：`build/github_webview_acceptance.py`。
- 首轮 UI 验收的命中等待过早（搜索结果刷新前点击旧列表），修正验收等待条件后通过。修复了真实代码中的脚本资源未放行、`Materials.refresh` 未导出两处问题。
- 新 EXE 已打包至 `dist-ui/InfraResearcher.exe`；`启动研究室.bat` 已优先指向它。隔离 EXE smoke test 产生 `webview-smoke-passed.txt`、`models-smoke-passed.txt`、`companion-smoke-passed.txt`、`companion-lifecycle-passed.txt`，目录为 `build/github-exe-smoke-20261007`。
- 网络实际验收仅用于公开只读下载；版本变化、限流、超时、取消、单文件失败、安全拒绝、学习生成与复习联动采用可控夹具，未触发真实限流，也未等待上游新 commit 或调用真实模型。未修改用户数据库与密钥。

## 修改清单与数据库迁移

- 统一读取：`github_source.py`、`core.py`；资料导入：`github_import.py`、`materials.py`、`desktop.py`；模型资料权限与联动：`chat.py`、`learning_flow.py`、`review.py`。
- 界面：`static/index.html`、`static/github-import.js`、`static/materials.js`、`static/materials.css`、`static/learning-flow.js`、`static/review.js`、`static/ui.js`、`static/companion.html`、`static/companion.js`。
- 测试：`test_github_import.py`、`test_learning_flow.py`、`test_desktop.py`、`build/github_webview_acceptance.py`；说明：`README.md`、本文档。
- 新增 `github_versions`（仓库固定版本元信息及缓存目录）、`github_files`（文件选择/状态/大小/哈希/文档关联）、`github_runs`（持久运行记录与取消状态）。现有 `documents` 增加 `source_json`、`content_hash`；`document_chunks` 增加 `start_line`、`end_line`、`chunk_hash`、`commit_sha`、`source_url`，复用原有 pages、tags、FTS 表。
- 学习联动新增 `learning_suggestions`、`learning_review_links`；复习表兼容增加标题、暂停、间隔和推进字段，复习事件增加备注。仅添加缺失字段和表，不替换旧表，不为旧学习任务批量创建复习。

## 文件类型与限制

- TXT、Markdown、RST、AsciiDoc；Python、JS/TS、Java、Go、Rust、C/C++、CUDA、Shell/PowerShell、Ruby、Swift、Kotlin、Scala、R、Vue/Svelte、HTML/CSS/XML/SQL 等文本；JSON/YAML/TOML/INI/CFG/CONF、依赖清单、Dockerfile、Makefile、CMake 等工程资料。
- UTF-8 优先，失败尝试 GB18030；包含二进制、无法解码、疑似凭据或空内容的文件记失败，其他文件继续。仓库 PDF、图片、音视频、LFS、构建产物、依赖缓存、符号链接、证书及密钥不导入。已有本地 PDF 导入保持可用。
- 单文件 1 MB；每批最多 100 文件、总计 15 MB；目录树最多 10,000 文件，API 截断时明确失败。网络超时沿用 45 秒；取消当前请求最多需等待该请求返回，之后停止，成功文件保留。
- 缓存固定 commit 的目录树和已成功保存文件；重复导入不再次下载已保存内容。暂不复用不同 commit 中相同 blob 的下载缓存。请求串行，进度每 1.2 秒仅轮询本机接口；限流不自动重试。
- 密钥检测是规则式防护，无法承诺识别所有自定义凭据格式。Token/私有仓库、向量检索、移动端资料操作及跨进程同时导入尚未实现。真实模型生成学习计划仍待用户配置后验收。
