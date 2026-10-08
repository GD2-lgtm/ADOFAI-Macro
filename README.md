# ADOFAI Macro

解析 ADOFAI 谱面文件，进行自动的按键输出

> 仅供学习与娱乐，在Together/TUF等环境中使用macro属于作弊行为，请遵守游戏与社区规则，对于因使用本项目造成的不良影响，开发组不负任何责任
>
> 尽管协议上没有要求，但如果有人想要用此Macro录制视频的话可以和我说一下(虽然可能不会有人录就是了.jpg)
>
> 这边是一点碎碎念，我希望有些人来找我是来交流学习的，不是连python都不会用的🙃

## 运行环境

| 项目     | 要求                                                     |
| -------- | -------------------------------------------------------- |
| 操作系统 | Windows 10 / 11（64 位）                                 |
| Python   | CPython **3.10 ~ 3.14**（Windows 版，推荐 3.12）         |
| 依赖库   | `PySide6`、`keyboard`、`colorama`、`pywin32`             |

> ⚠️ 只支持 Windows。全局键盘钩子、`SendInput` 注入、控制台接管都是直接调用 Win32 API 实现的。
>
> ⚠️ 请不要使用 Microsoft Store 版本的 Python，原因见下面「步骤 1」。

## 让它可以运作

**下面所有命令都在项目根目录（也就是 `main.py` 所在的那一层）执行。**

### 步骤 1：安装 Python

先看看有没有装过：

```powershell
python --version
```

- 输出 `Python 3.10.x` ~ `Python 3.14.x` → 直接跳到步骤 2
- 提示「不是内部或外部命令」，或者**一执行就弹出应用商店** → 需要安装，继续往下看

**方式 A：winget（推荐，Win10 1809+ 自带）**

```powershell
winget install -e --id Python.Python.3.12
```

**方式 B：官网安装包**

1. 打开 <https://www.python.org/downloads/windows/>
2. 下载 Python 3.12 的 **Windows installer (64-bit)**
3. 安装界面**务必勾选 `Add python.exe to PATH`**，然后一路 Next

装完请**关闭并重新打开终端**（让 PATH 生效），然后验证：

```powershell
python --version      # 期望：Python 3.12.x
where python          # 确认路径没有落在 WindowsApps 下面
where pythonw         # 确认 pythonw 也在（它没有控制台，加 --version 不会有任何输出）
```

> ⚠️ **别用 Microsoft Store 版的 Python**
>
> 如果 `where python` 给出的是
> `C:\Users\<用户名>\AppData\Local\Microsoft\WindowsApps\python.exe`，
> 那通常只是商店的**占位别名**：执行它不会运行代码，而是打开应用商店。
> 这种情况请按方式 A / B 装上真正的 Python；必要时到
> 「设置 → 应用 → 高级应用设置 → 应用执行别名」把 `python.exe`、`python3.exe` 两个别名关掉。

### 步骤 2：获取项目

- 下载 ZIP 解压，或者 `git clone`
- 解压后确认目录里同时存在 `main.py`、`config.json`、`app\`、`parser\`
- 建议放在**纯英文、无空格的路径**下（例如 `D:\AMacro`），可以省掉一堆编码和权限上的麻烦

### 步骤 3：安装依赖

```powershell
python -m pip install --upgrade pip
python -m pip install PySide6 keyboard colorama pywin32
```

下载慢就换国内镜像：

```powershell
python -m pip install PySide6 keyboard colorama pywin32 -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**装完必须验证**，下面这条命令打印出 `OK` 才算装好：

```powershell
python -c "import PySide6, keyboard, colorama, win32console; print('OK')"
```

> 四个库各管一块，缺任何一个程序都起不来：
> `PySide6` → 界面；`keyboard` → 全局按键钩子；`colorama` → 控制台彩色输出；
> `pywin32`（提供 `win32console`）→ 控制台窗口。
>
> 如果电脑里有多个 Python，请**始终用 `python -m pip install`** 装依赖，
> 这样才能保证装进「等一下要用来运行程序」的那个解释器里。

<details>
<summary>可选：用虚拟环境隔离（不想污染全局环境的推荐）</summary>

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install PySide6 keyboard colorama pywin32
```

之后每次运行前先激活 `.\.venv\Scripts\Activate.ps1`；
或者不激活，直接 `.\.venv\Scripts\pythonw.exe main.py`。

</details>

### 步骤 4：启动程序

```powershell
# 在项目根目录下
pythonw main.py
```

用 `python` 也一样可以：

```powershell
python main.py
```

> `pythonw` 与 `python` 的区别只在于「启动瞬间有没有现成的控制台可以附着」：
> 程序自己会调用 `AllocConsole()` 开一个控制台窗口并把日志重定向过去，
> 所以两种方式都能跑，日志也都看得到。
>
> 在 VS Code / PyCharm 里直接运行 `main.py` 时，输出会走编辑器自带的终端，不会另开窗口。
>
> 用 IDLE 打开 `main.py` 按 F5 也可以，因为 IDLE 本身就是走 `pythonw`。

**启动成功的标志**：主窗口出现。
至于控制台，用 `pythonw` 启动时程序会自己新开一个；用 `python` 在已有终端里启动时，日志就直接打在当前终端。
控制台平时是空的，只有在操作、报错或开启详细输出时才会滚日志。

### 步骤 5：开始使用

1. **加载谱面**：菜单「文件 → 加载谱面」或直接把 `.adofai` 文件拖进窗口
2. **配置按键**：在「输出按键」区为左右手添加/修改/排序按键（可双击已绑定的按键直接修改）
   - 推荐绑定32键，以获得最佳手法模拟体验
   - (如果实在不会绑定的话，默认配置文件就行ouo)
3. **开始/停止**：按下触发键（默认 `Insert`）开始播放，再按一次停止
4. **偏移微调**：运行过程中可按 `←` / `→` (默认)实时调整偏移（提前 / 延后，精度1ms）
5. **节奏提示**：在「其他设置」的「节奏提示」分组中勾选「启用节奏提示」开启
6. **下落式**：在「其他设置」的「下落式」分组中勾选「启用下落式窗口」开启
7. **随机偏移**:
   - 正常偏移：适用于规则角度（如 90°、180°）以及双押/三连音。程序会自动识别多押并强制使用此偏移，保证同时按下的稳定性。
   - 不规则偏移：适用于不规则角度（如 45°、58° 等弯曲路段），模拟真人操作时的误差。
8. **界面语言**：菜单「语言 → 简体中文 / English」随时切换，立即生效并自动保存到配置

### 步骤 6：确认按键真的输出到游戏

Macro 是把按键注入到**当前焦点窗口**上的，所以：

1. 先把 Macro 启动好，再切到 ADOFAI，并让游戏保持在前台（**不要**让 Macro 窗口或控制台窗口抢着焦点）
2. 在游戏里按触发键（默认 `Insert`）开始，再按一次停止；能否用 `Esc` 停止取决于配置里的「Macro 结束方式」
3. 想先确认有没有真的在发按键：打开记事本，按一下 `Insert`，应该能看到一串字符被「打」进记事本
   （前提是「其他设置 → 按键输出」里的 `禁用 Macro 按键输出` 没有被勾上）
4. 如果游戏是**以管理员身份运行**的，Macro 也必须以管理员身份运行，否则发出的按键会被 Windows 的 UIPI 丢掉，
   表现就是「日志一切正常，但游戏毫无反应」

## 常见问题

**Q1. `python` 不是内部或外部命令，或者一执行就跳出应用商店**

没装真正的 Python，见「步骤 1」。装完记得**重开终端**。

**Q2. `ModuleNotFoundError: No module named 'PySide6'`（`keyboard` / `colorama` 同理）**

依赖没装，或者装到别的 Python 里去了。重新执行
`python -m pip install PySide6 keyboard colorama pywin32`，
并用 `python -c "import sys; print(sys.executable)"` 确认这就是你打算用来运行程序的那个解释器。

**Q3. `ModuleNotFoundError: No module named 'win32console'`**

pywin32 缺失或装得不完整：

```powershell
python -m pip install --force-reinstall pywin32
```

还不行就跑一次 pywin32 的安装后脚本（把 `<Python安装目录>` 换成你的解释器所在目录）：

```powershell
python "<Python安装目录>\Scripts\pywin32_postinstall.py" -install
```

**Q4. 用 `pythonw` 或双击启动后一闪就没，什么提示都没有**

改用 `python main.py` 在**已经有控制台的终端**里运行，traceback 才会留在屏幕上。
最常见的原因就是依赖没装齐 —— `pythonw` 下导入 `PySide6` 失败是「静音」的。

**Q5. 按 `Insert` 游戏里没反应**

- 游戏窗口必须是前台焦点（Macro 往焦点窗口注入按键）
- 游戏若以管理员运行，Macro 也要以管理员运行
- 检查「其他设置 → 按键输出」里 `禁用 Macro 按键输出` 是否被勾上
- 检查「按键配置」里左右手的按键列表是不是空的
- 先按「步骤 6」第 3 条在记事本里验证一遍按键输出

**Q6. `config.json` 解析失败 / 设置乱掉了**

直接删掉 `config.json` 再启动，程序会回退到内置默认配置，并在退出或改动设置时重新写出一份完整的 `config.json`。

**Q7. 触发键或方向键跟别的软件冲突**

触发键、`←` / `→` 偏移键、`Esc` 结束键都是**全局**钩子，在任何窗口下都会响应；
而且在 `suppress_bound_keys`（默认 `true`）打开时还会被**全局屏蔽** ——
Macro 开着的时候，`Insert` 不会传给你正在用的其他软件。
不想要这个行为，就到「其他设置 → 按键输出」把「屏蔽已绑定按键输入」取消勾选；
单纯是冲突的话，也可以到「按键配置」里换一个触发键。

**Q8. 杀毒软件报警，或全局钩子被拦截**

本项目用 `keyboard` 和 `SetWindowsHookEx` 安装全局键盘钩子来自动按键，
行为上会被部分安全软件误判成键盘记录器。请自行判断是否加入信任列表。

**Q9. 某个键一直处于「按下」状态**

正常结束播放时程序会统一释放所有按键，但**强杀进程**（任务管理器结束任务）会跳过这一步。
请用触发键 / `Esc` 正常停止；已经卡住的话，手动多按几下那个键即可恢复。

**Q10. 谱面文件从哪来**

任何 `.adofai` 文件都能加载（菜单「文件 → 加载谱面」，或直接把文件拖进窗口）。
官方编辑器保存的关卡、社区网站下载的关卡都可以用；
Steam 创意工坊关卡一般可以在
`...\steamapps\workshop\content\977950\<关卡ID>\` 里找到（977950 是 ADOFAI 的 AppID）。

## 界面语言

程序内置简体中文 / English 两套界面文案，通过菜单栏的「语言」菜单切换，**无需重启**：

- 切换后所有已打开的窗口（主窗口、按键配置、其他设置、节奏提示、下落式）会同步刷新
- 窗口会按新语言重新排版并自动调整到合适大小；语言相关的下拉框选项（切分、轨道数、主手、结束方式、手法风格）只改变显示文字，写入 `config.json` 的始终是与语言无关的固定值
- 语言记录在 `config.json` 的 `language` 字段（`zh` / `en`），导入/导出配置时一并生效
- 未翻译或缺失的条目会回退到简体中文，不会出现空白

## 界面布局

界面按「主窗口做最常改的事，其余收进子窗口」的方式组织，并使用统一的对齐网格：

- **主窗口**：加载谱面、播放控制、手法模拟
- **按键配置**：输出按键（左右手并排列表）、触发键
- **其他设置**：按键输出、Macro 结束方式、节奏提示、下落式

细节上做了这些优化：

- 播放控制改用网格布局，同一列的数字输入框与标签严格对齐，宽度统一
- 手法模拟把开关放在一行、参数放在一行，窄窗口下也不会被撑宽
- 节奏提示 / 下落式把「开关 + 流速/切分」与「特效 + 按钮」分成两行，其他设置窗口从约 930px 宽收窄到约 450～520px
- 所有窗口改为**可放大**（保留最小尺寸），窗口按内容自适应；切换语言时只会变大，不会挤压已调整过的窗口

## 目录结构

```
AMacro/
 ├── main.py               程序入口
 ├── config.json           用户配置
 ├── README.md             项目说明
 ├── .gitignore            Git 忽略规则
 ├── parser/               谱面解析
 │   ├── reader.py         .adofai 文件解码
 │   └── angle.py          角度/节拍/按键时间计算
 └── app/                  应用逻辑
     ├── config.py         配置读写
     ├── console.py        控制台
     ├── constants.py      常量
     ├── i18n.py           界面语言（简体中文 / English）与文案表
     ├── keys.py           键名解析与 SendInput 注入
     ├── hotkey.py         方向键钩子
     ├── multipress.py     多押识别与标注
     ├── playback.py       按键播放引擎
     ├── playback_process.py 播放引擎子进程封装
     ├── technique.py      手法模拟
     ├── timeline.py       按键时间轴生成 (含随机偏移逻辑)
     └── ui/
         ├── main_window.py         主窗口
         ├── sizing.py              窗口按内容自适应大小
         ├── focus_filter.py        点击空白处清除输入框焦点
         ├── key_config_window.py   按键配置窗口
         ├── other_settings_window.py 其他设置窗口
         ├── rhythm_hint_window.py  节奏提示窗口
         ├── falling_notes_window.py 下落式窗口
         └── bind_window.py         按键绑定窗口
```

## 配置说明（config.json）


| 字段                                           | 说明                                                           |
| ---------------------------------------------- | -------------------------------------------------------------- |
| `left_keys` / `right_keys`                     | 左右手输出按键列表（4个按键为一组）                            |
| `keys`                                         | 兼容字段：`left_keys + right_keys`，一般无需手动修改           |
| `hotkey`                                       | 全局触发键                                                     |
| `press_duration`                               | 按键按下持续时间                                               |
| `technique.enabled`                            | 是否启用手法模拟                                               |
| `technique.style`                              | 手法风格名称（当前仅`内轮`）                                   |
| `technique.single_kps`                         | 单指KPS                                                        |
| `technique.main_hand`                          | 主手（`right` / `left`）                                       |
| `technique.follow_speed`                       | 手法模拟是否随倍速解析                                         |
| `verbose`                                      | 是否开启实时按键详细输出                                       |
| `offset_left_key` / `offset_right_key`         | 实时偏移调节键（默认`left` / `right`）                         |
| `realtime_offset_enabled`                      | 是否允许运行中实时调整偏移（默认`true`）                       |
| `macro_end_mode`                               | Macro 结束方式：`trigger` / `esc` / `both`                     |
| `disable_key_output`                           | 是否禁用 Macro 按键输出（默认`false`）                         |
| `suppress_bound_keys`                          | 是否屏蔽已绑定按键输入（默认`true`，输出按键除外）             |
| `rhythm_hint_enabled`                          | 是否开启节奏提示窗口                                           |
| `rhythm_hint_speed`                            | 节奏提示音符流速                                               |
| `rhythm_hint_division`                         | 节奏提示切分线密度（`4` / `8` / `16` / `32` 分）               |
| `rhythm_hint_hit_effect`                       | 是否显示判定特效（音符到达判定点时放大的白色圆环，默认`true`） |
| `rhythm_hint_multi_fix`                        | 节奏提示是否启用多押提示（默认`true`）                         |
| `falling_notes_enabled`                        | 是否开启下落式窗口                                             |
| `falling_notes_speed`                          | 下落式音符流速                                                 |
| `falling_notes_division`                       | 下落式横向节拍线密度（`4` / `8` / `16` / `32` 分）             |
| `falling_notes_lanes`                          | 下落式轨道数（`4` = 4K、`8` = 8K[支持到16键]）                 |
| `falling_notes_multi_fix`                      | 下落式是否启用多押提示（默认`true`）                           |
| `falling_notes_hit_effect`                     | 下落式是否显示判定特效（默认`false`）                          |
| `rhythm_hint_width`                            | 节奏提示窗口宽度（默认`900`；高度固定为 150，宽度可拖动调整）  |
| `falling_notes_width` / `falling_notes_height` | 下落式窗口分辨率（默认`380` / `820`，宽高都可拖动调整）        |
| `regular_offset_ms`                            | 正常偏移量 (ms)：规则角度及多押/三连音的随机偏移范围，默认`5.0` |
| `irregular_offset_ms`                          | 不规则偏移量 (ms)：不规则角度的随机偏移范围，默认`10.0`       |
| `font_name` / `font_size`                      | 界面字体名称与字号（默认`Microsoft YaHei` / `9`）              |
| `language`                                     | 界面语言：`zh`(简体中文) / `en`(English)，默认`zh`            |

配置可通过菜单「文件 → 导入/导出配置」保存与导入

## 其他

一些过于重要的功能会闭源
