# ADOFAI Macro

解析 ADOFAI 谱面文件，进行自动的按键输出

> 仅供学习与娱乐，在Together/TUF等环境中使用macro属于作弊行为，请遵守游戏与社区规则


## 运行环境

- Windows 10 / 11
- Python 3.10+
- 依赖库：

```bash
pip install PyQt5 keyboard colorama pywin32
```

## 使用方法

```bash
# 在项目根目录下运行
python main.py
```

1. **加载谱面**：菜单「文件 → 加载谱面」或直接把 `.adofai` 文件拖进窗口
2. **配置按键**：在「输出按键」区为左右手添加/修改/排序按键（可双击已绑定的按键直接修改）
   - 推荐绑定32键，以获得最佳手法模拟体验
   - (如果实在不会绑定的话，默认配置文件就行ouo)
3. **开始/停止**：按下触发键（默认 `Insert`）开始播放，再按一次停止
4. **偏移微调**：运行过程中可按 `←` / `→` 实时调整偏移（提前 / 延后，单位 ms）


## 目录结构

```
AMacro/
├── main.py               程序入口
├── config.json           用户配置(退出时自动保存)
├── LICENSE               MIT license
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
        ├── main_window.py    主窗口
        └── bind_window.py    按键绑定窗口
```

## 配置说明（config.json）

| 字段 | 说明 |
|---|---|
| `left_keys` / `right_keys` | 左右手输出按键列表（从上到下分别为从中间向左右发散，4个按键为一组） |
| `hotkey` | 全局触发键 |
| `press_duration` | 按键按下持续时间 |
| `technique.enabled` | 是否启用手法模拟 |
| `technique.single_kps` | 单指KPS |
| `technique.main_hand` | 主手（`right` / `left`） |
| `technique.follow_speed` | 手法模拟是否随倍速解析（`true` / `false`） |
| `verbose` | 是否开启实时按键详细输出 |

配置可通过菜单「文件 → 导入/导出配置」保存与导入

## 打包

您可以使用 Nuitka 打包为单文件 exe：

```bash
# 在项目根目录下运行
python -m nuitka --onefile --enable-plugin=pyqt5 main.py
```

## 声明

本项目使用了 AI 进行辅助制作：

- DeepSeek V4 Flash / Pro
- Kimi K3

## 注意

目前已知自动方块+中旋+长按场景下可能存在解析问题
4.0版本由于更换了UI框架，可能会存在一些未知bug
