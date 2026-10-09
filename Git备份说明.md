# Git 备份与恢复

远程仓库：https://github.com/LyraSelene/GitHubExploer

本仓库保存 InfraResearcher 的 Python 源码、前端、原画运行素材、Android 源工程、研究指令、自动化测试及验收文档。2026-10-09 首次备份对应当前已打包的水中动作版本；此后提出的动作幅度优化尚未实现。

本机使用 `启动研究室.bat` 优先打开 `dist-ui/InfraResearcher.exe`。外层 `D:\codex尝试\启动目录核对.bat` 启动的是独立 Markdown 目录核对工具，不属于本项目。

## 获取与运行

```powershell
git clone https://github.com/LyraSelene/GitHubExploer.git
cd GitHubExploer
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe desktop.py
```

Windows 桌面运行需要已安装 Microsoft Edge WebView2。个人 API Key 在应用内配置，继续由 Windows DPAPI 保存，不随 Git 迁移。

## 测试与重新打包

```powershell
.\.venv\Scripts\python.exe -m unittest discover -q
node build/test_water_actions.cjs
node build/check_scene_lifecycle.cjs
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath dist-ui InfraResearcher.spec
```

重新打包后使用 `启动研究室.bat`。Node 检查需要本机 Node.js；几何和资产处理脚本另需 Pillow、NumPy、OpenCV。部分历史 WebView 对比脚本依赖本机 `build` 下的基线样本与测量输出，Git 中不包含这些生成数据，不宣称全新克隆后这些对比脚本可直接运行。

## 后续提交

```powershell
git status --short
git add .
git diff --cached --stat
git commit -m "描述本次修改"
git push origin main
```

提交前检查暂存文件。`.gitignore` 排除运行数据库、密钥、虚拟环境、EXE/APK、构建缓存和历次截图；`static` 内运行所需图片和视频随源码保存。

本地 Git bundle 保存于外层 `git-backups` 目录，可在远程不可用时恢复：

```powershell
git clone "本地备份文件.bundle" InfraResearcher-restored
```

Git 备份不包含个人报告、聊天、学习进度和模型配置。这些运行数据位于 `%LOCALAPPDATA%\AIInfraResearcher`，没有在本次公开上传中读取或复制。历史验收文档中的本地截图链接属于当时测试记录，部分预览文件不随本仓库上传。
