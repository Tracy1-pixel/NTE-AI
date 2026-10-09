# 异环助手 · 店长特供 1.3

Windows 10/11 x64 桌面应用，安装后通过桌面“异环助手”打开中文 GUI。使用 EXE 安装包时无需单独安装 Python；也支持下载源码并通过 PowerShell 运行。新版内置玩家提供的七图界面模板和操作位置。

## 安装与开始

### 方法一：EXE 安装包

[直接下载 Windows EXE 安装包](https://github.com/Tracy1-pixel/NTE-AI/releases/download/v1.3.0/NTE-AI-Setup-1.3.0.exe)，或打开 [Releases 下载页面](https://github.com/Tracy1-pixel/NTE-AI/releases/latest)，在 Assets 中选择 `NTE-AI-Setup-1.3.0.exe`。双击安装后，通过桌面 **“异环助手”快捷方式** 打开中文界面，点击“开始运行”或“停止”。无需下载源代码、解压 ZIP 或安装 Python。已有旧版可直接安装升级，应用配置目录为 `%LOCALAPPDATA%\NTE-AI`。

### 方法二：EXE 下载不了或无法使用时，下载源码并用 PowerShell 运行

1. 从 [Python 官网](https://www.python.org/downloads/windows/) 安装 **Python 3.12（64 位）**，安装时保留 Python Launcher（`py` 启动器）选项。
2. [下载源码 ZIP](https://github.com/Tracy1-pixel/NTE-AI/archive/refs/heads/main.zip)，或在仓库点击 **Code → Download ZIP**。将 ZIP 完整解压，进入能看到 `app.py`、`requirements.txt` 和 `assets` 的文件夹。如果已经下载了这样的源码文件夹，可以直接使用。
3. 在该文件夹空白处右键选择 **“在终端中打开”**，确认使用 PowerShell。Windows 10 可按住 **Shift** 再右键，选择 **“在此处打开 PowerShell 窗口”**。
4. 先检查 Python 版本：

```powershell
py -3.12 --version
```

显示 `Python 3.12.x` 后，在同一窗口依次执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

首次安装依赖需要联网；看到依赖安装完成后，再执行最后一行打开中文界面。此方式直接使用虚拟环境中的 Python，无需执行 `Activate.ps1`，也无需修改 PowerShell 执行策略。

如果提示找不到 `py` 或没有 Python 3.12，请回到第 1 步安装相应版本和 Launcher，重新打开 PowerShell 后再试。如果提示找不到 `requirements.txt` 或 `app.py`，请回到第 2 步中的源码文件夹再打开终端。

以后启动时，在同一源码文件夹打开 PowerShell，只需执行：

```powershell
.\.venv\Scripts\python.exe app.py
```

**可选：为源码版创建桌面快捷方式。** 首次成功运行并关闭助手后，在同一源码文件夹的 PowerShell 中执行下面整段代码：

```powershell
$nteSourceRoot = (Get-Location).Path
$nteShortcutShell = New-Object -ComObject WScript.Shell
$nteDesktopPath = [Environment]::GetFolderPath('Desktop')
$nteSourceShortcut = $nteShortcutShell.CreateShortcut((Join-Path $nteDesktopPath '异环助手（源码）.lnk'))
$nteSourceShortcut.TargetPath = Join-Path $nteSourceRoot '.venv\Scripts\pythonw.exe'
$nteSourceShortcut.Arguments = '"' + (Join-Path $nteSourceRoot 'app.py') + '"'
$nteSourceShortcut.WorkingDirectory = $nteSourceRoot
$nteSourceShortcut.Save()
```

之后双击桌面 **“异环助手（源码）”** 即可打开界面。这个快捷方式依赖当前源码目录，请保留该目录及其中的 `.venv` 文件夹。

### 游戏准备与开始运行

游戏须先在游戏设置中切换为**普通窗口模式**。新版将游戏**内容区固定为 1920×1080**，标题栏和边框另算；开始运行时自动调整所选窗口尺寸和位置。助手使用独立的深色控制台界面，显示窗口尺寸、运行阶段、营业额和完成 / 失败次数。

游戏窗口须在主屏幕完整可见。窗口位置可以改变，识别截图与点击坐标始终跟随游戏内容区，不包括桌面、标题栏和边框。桌面需有足够空间容纳 1920×1080 内容区及边框，例如 2560×1440；1920×1080 桌面通常放不下同尺寸的带边框窗口，此时会提示空间不足并拒绝启动。

1. 打开店长特供的**图一初始界面**。
2. 打开助手，点击“刷新”，在“绑定游戏窗口”下拉框选中《异环》。标题能唯一识别时会自动选中。游戏打开后再刷新；多个同名窗口须手动选择。
3. 在助手主页设置点击和识别间隔，点击“开始运行”，助手会自动最小化，5 秒内切回图一。助手会将所选游戏内容区调整为 1920×1080，尝试将游戏置于前台，再确认图一。随后将游戏光标移到左侧关卡栏，向下滚动到底，找到并点击“钢琴家”；确认右侧已选中关卡后，将光标移到右下角点击“开始营业”，继续倒计时和锤子连点。游戏若自行恢复其他尺寸，会暂停操作并提示尺寸错误。
4. “检查画面”只读，不会改变尺寸或点击；先将游戏设置为 1920×1080，再检查。初始界面应显示 `home`，都市体力数值应与游戏一致。
5. **点击“停止”或按 F8 手动停止。** 助手运行时会最小化，可通过任务栏恢复界面点击停止；切到助手会暂停游戏操作。任务终止后，助手会自动恢复 GUI，显示结束原因和运行记录。运行中关闭 GUI 会提示先停止。鼠标移到角落、Esc、轮数和总时长不再是停止条件。

游戏切到后台、最小化、移出主屏幕或内容区尺寸改变时暂停操作；恢复正确尺寸并切回游戏后继续。F8 可停止当前运行。

GUI 中“七图流程说明”展示完整流程，不再需要手动录入不足提示、Esc 或进出步骤。1.0 的轮数、总分钟数和旧坐标配置在新版流程中不生效。

## 游戏左下角状态栏

运行时，在游戏内容区左下角显示半透明状态栏，持续更新**实际窗口尺寸、当前阶段、营业额、完成轮数和连续失败次数**。出现尺寸错误或未知画面时显示暂停原因；恢复正确界面后继续。切换到其他窗口、最小化游戏或结束运行时隐藏状态栏。

状态栏采用普通 Windows 浮窗，鼠标点击穿透且不抢游戏焦点。截图识别时排除状态栏；旧版 Windows 或排除失败时，在截图期间临时隐藏，以免遮挡左侧选关的 OCR。状态栏随游戏窗口位置和尺寸变化，预期尺寸为 1920×1080。

## 自动流程

| 图片 | 识别与操作 |
| --- | --- |
| 图一 | 连续确认店长特供标题与开始营业按钮，才允许开始；将光标移到左侧关卡栏，向下滚动到底 |
| 图二 | OCR 找到 `3-10 钢！琴！家！`，移动光标点击关卡并确认右侧已选中，再将光标移到右下角点击开始营业 |
| 图三 | 倒计时期间即可开始连续点击左侧锤子 |
| 图四 | 保持锤子连点，定期读取右上角营业额 |
| 图六 | 连续确认营业额达到 1900 后停止连点，点击左上角退出图标 |
| 图七 | 连续确认成功结算，读取领取下方消耗，非零且可读时领取；回到图一继续 |
| 图五 | 连续确认失败，点击“重新挑战”；直接等待倒计时并连点，不返回图一选关 |

每次成功领取并返回图一，连续失败计数归零。连续失败三次终止当前运行。

领取下方的消耗**不是固定 48**。每次结算都会重新 OCR 读取当前数字，任何可读的非零消耗都允许领取并继续循环；例如 `48 → 24 → 7 → 0`，前三次领取，最后确认 0 时停止，且不点击领取。界面预览中的 48 只是截图样例。

都市体力完整分数中的左侧值连续确认为 0，或者领取按钮下方的消耗连续确认为 0，都自动停止。OCR 读不到为未知，**不会当作 0**。这些是自动结束条件；手动停止使用停止按钮或 F8。

初始画面不匹配时显示“界面错误”并拒绝开始。运行过程中出现未知画面或页面切换迟迟未完成时，暂停点击并在日志显示错误，继续等待正确界面或 F8；不会因普通加载超时直接退出。挑战自身倒计时结束出现图五时走失败重试流程。

营业额达标依据左侧数字 ≥1900；星星是界面反馈，不代替营业额判断。工具使用截图、OCR 和普通鼠标输入，不读取游戏内存。

## 开发与构建

Windows Python 3.12：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

命令行 `python automation.py check` 检查界面，`python automation.py run` 启动同一新版流程。

构建还需 Inno Setup 6：

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-build.txt
python -m unittest discover -s tests -v
.\packaging\build.ps1
```

GitHub Actions 使用 Windows 构建，打包 OCR 模型与截图模板，测试安装后的 GUI、真实截图数字识别、Windows 窗口内容区调整、停止按钮、状态栏位置 / 点击穿透 / 焦点以及桌面快捷方式。验证通过后自动将 EXE 发布至 GitHub Releases；已有版本保持不变，更新安装包时须提升版本号。安装程序未签名，安装向导为英语，应用为中文。

## 验证范围

窗口测试覆盖边框尺寸换算、窗口移动后的坐标、前台与最小化检查、尺寸错误、桌面空间不足和窗口选择。状态机测试覆盖初始界面拒绝、选关启动、领取循环、体力/消耗零值、直接重试、三次失败、领取后重置失败计数、未知界面暂停及 F8。状态栏测试还覆盖截图排除的回退、截图失败后的恢复、窗口移动定位和未知 / 零营业额的显示。截图识别已用玩家提供的图一、三、四、五、六、七核对。

这些验证不能替代真实游戏运行。截图来自玩家设备，其他语言、不同 UI 缩放、弹窗遮挡或游戏不接收模拟输入可能导致识别或点击失败。首次运行请观察完整流程，必要时按 F8。
