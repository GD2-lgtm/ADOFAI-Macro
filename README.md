# ADOFAI Macro

解析 ADOFAI 谱面文件，进行自动的按键输出

> 仅供学习与娱乐，在Together/TUF等环境中使用macro属于作弊行为，请遵守游戏与社区规则，对于因使用本项目造成的不良影响，开发组不负任何责任
>
> 尽管协议上没有要求，但如果有人想要用此Macro录制视频的话可以和我说一下(虽然可能不会有人录就是了.jpg)
>
> 这边是一点碎碎念，我希望有些人来找我是来交流学习的，不是连python都不会用的🙃

## 运行环境

- Windows 10 / 11
- Python 3.10+
- 依赖库：PySide6 keyboard colorama pywin32

```bash
pip install PySide6 keyboard colorama pywin32
```

## 使用方法

你可以使用IDLE，VsCode等编辑器打开main.py或使用以下命令运行

```bash
# 在项目根目录下运行
pythonw main.py
```

> 在VsCode等编辑器下，默认走的是python.exe，此时程序会将在对应编辑器的控制台进行输出，不会创建控制台窗口
>
> 对于IDLE无影响，因为IDLE走的是pythonw.exe
>
> 至于命令行更没影响了，python和pythonw其实都行()

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
    ├── keys.py           键名解析与 SendInput 注入
    ├── hotkey.py         方向键钩子
    ├── playback.py       按键播放引擎
    ├── technique.py      手法模拟
    ├── timeline.py       按键时间轴生成
    └── ui/
        ├── main_window.py         主窗口
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

配置可通过菜单「文件 → 导入/导出配置」保存与导入

## 其他

一些过于重要的功能会闭源
