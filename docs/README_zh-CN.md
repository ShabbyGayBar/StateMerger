# 维多利亚3省份合并工具&教程

![Python Version from PEP 621 TOML](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2FShabbyGayBar%2FStateMerger%2Frefs%2Fheads%2Fmaster%2Fpyproject.toml)
![GitHub Actions CI](https://img.shields.io/github/actions/workflow/status/ShabbyGayBar/StateMerger/ci.yml?label=CI)
![GitHub Actions Release](https://img.shields.io/github/actions/workflow/status/ShabbyGayBar/StateMerger/release.yml)
[![Codacy Badge](https://app.codacy.com/project/badge/Grade/ab10a6c25b77466d9b009f92c3b31fd9)](https://app.codacy.com/gh/ShabbyGayBar/StateMerger/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_grade)

作者的[省份合并 mod](https://github.com/ShabbyGayBar/StateMerging) 已经发布在 [Steam 创意工坊](https://steamcommunity.com/sharedfiles/filedetails/?id=3371693463)！

## 简介

本项目包含若干 Python 脚本，用于自动化合并维多利亚3中的省份。

脚本可以自动生成以下维多利亚3的 mod 文件：
- `/common/...`
- `/event/...`
- `/map_data/state_regions/...`

## 省份合并教程

### 0. 准备工作

- **二选一：**
  - 从[发布页面](https://github.com/ShabbyGayBar/StateMerger/releases)下载最新的 GUI 可执行文件。（推荐但仅 Windows）
  - **或：**
  - 安装 [Python 3.14 或更高版本](https://www.python.org/downloads/)。
  - 在命令行中运行
    `pip install "https://github.com/ShabbyGayBar/StateMerger/releases/download/v2.1.3/vic3_state_merger-2.1.3-py3-none-any.whl"`
    以通过 pip 安装本包。
- **二选一：**
  - **安装维多利亚3原版游戏（例如通过 Steam），** 如果你想从头制作 mod。
  - **或：**
  - **安装一个维多利亚3 mod（例如通过 Steam），** 如果你想在该 mod 上合并省份。

### 1. 编写省份合并规则

省份合并规则保存在 `merge_state.json` 文件中。您可以编辑此文件以自定义省份合并规则。

`merge_state.json` 文件结构类似下面这样：
```json
{
    "state_0": ["state_1", "state_2", "state_3"]
}
```

冒号左边的是省份 ID 的字符串，右边的是表示省份 ID 的字符串列表。列表中的所有省份将被合并到冒号左边的省份中。

例如，上面的 JSON 文件会将 `state_1`、`state_2` 和 `state_3` 合并到 `state_0` 中：

### 2. 运行脚本

#### 如果下载了 EXE（仅 Windows）

- 双击运行 `state-merger.exe`。
- 下图的 GUI 会冒出。

  ![State Merger GUI](images/gui.png)

- 填写：
  - *Merge file (merge_states.json)*：上一步编辑的文件。
  - *Game root folder*：维多利亚3安装目录或作为基础的 mod 根目录。
    **注意！** 游戏根目录应该是维多利亚3安装目录或 mod 目录**下**的 `game` 文件夹。也就是说，你应该**在该目录中**看到以下内容：

    ![game root contents](images/game_root.png)

  - *Mod output folder*：生成的 mod 文件保存位置。
  - *Small state limit*（可选）：省份数量小于等于该值的州将视为“小省份”，默认为 4。
  - *Ignore small states*（可选）：开启后合并时不会给小省份提供 buff。
- 点击“运行”开始合并。
- 脚本执行大概需要 5 分钟。
- 完成后，你应该在 Mod 输出文件夹中看到如下目录结构：

  ![mod contents](images/mod_contents.png)

- 你仍需要创建 `.metadata` 文件夹以使游戏识别你的 mod，也可以自行添加其他 mod 内容。更多信息请参考 [维多利亚3 Wiki](https://vic3.paradoxwikis.com/Modding)。

#### 如果使用命令行（CLI）

只需运行一行命令：

```
state-merger-cli <merge_file> <game_root> <mod_dir> [--data-dir <path>] [--small-state-limit <int>] [--ignore-small-states]
```

示例：

```
state-merger-cli merge_states.json "C:/Program Files (x86)/Steam/steamapps/common/Victoria 3/game" "C:/path/to/mod"
```

你也可以输入 `state-merger-cli --help` 查看所有可用选项。

### 选择处理阶段并组合 mod 数据（Python API 和 CLI）

支持的阶段为 `map_data`、`state`、`pops`、`buildings`、`trade`、
`map_objects`、`misc` 和 `localization`。例如，仅合并 mod 地图，
无需提供原版历史数据：

```sh
state-merger-cli merge_states.json /mods/resource-mod /build/output --stages map_data
```

使用 mod 覆盖原版地图，其余阶段使用原版，运行全部阶段：

```sh
state-merger-cli merge_states.json /games/Victoria3/game /build/output \
  --source map_data=/games/Victoria3/game --source map_data=/mods/resource-mod
```

每个阶段使用一个有序的**游戏目录结构根目录**列表，根目录内应包含 `common/`、
`map_data/` 等目录。后面的根目录覆盖相同相对路径的文件（包括空文件），前面根目录中
其他文件仍然有效。选出的文件按文件名顺序使用现有解析合并规则处理。
这不模拟启动器元数据、`replace_path` 或定义级 mod 加载，也不补全定义内缺失字段。
显式指定的来源列表会替换该阶段默认的 `[game_root]`；需要原版时应主动加入。
多次使用 `--source 阶段=根目录`，按优先级从低到高排列。未指定来源的阶段使用位置参数
中的游戏根目录。`misc` 仍使用现有的脚本目录范围。

`misc` 阶段自动读取这些目录中的已安装 DLC 脚本，包括城市类型脚本。每个来源根目录
先读取直接文件，再按文件夹名称顺序读取直属 `dlc/<pack>/` 文件夹；后面的 DLC 覆盖
同名文件。后面的来源根目录覆盖前面的根目录及其 DLC 文件，包括用空文件覆盖。
输出使用游戏内相对路径，不包含 DLC 文件夹前缀，并保留功能条件和图形定义。
扫描不解析启动器中的启用状态或所有权信息。其他阶段和缓存复制方法不会自动扫描
DLC 文件夹。若只需 mod 脚本，为 `misc` 仅指定该 mod 根目录；需要原版及其 DLC
脚本时，将游戏根目录放在来源列表首位。

```python
from vic3_state_merger import StateMerger

merger = StateMerger(
    game_root,
    output_dir,
    merge_plan,
    sources={"map_data": [game_root, resource_mod_root]},
)
merger.run(stages=["map_data"])
# merger.run() 运行全部阶段，其他阶段仍读取原版。
```

构造对象不读取数据或修改输出；`map_data`、`states`、`pops`、`buildings` 和 `trade`
属性按需加载。每次执行重新读取所需模型，因此手动修改这些属性不会改变后续执行。
`map_objects` 和 `localization` 可以在内部计算合并后的地图，但不会生成或清理地图输出。
历史数据与 `misc` 阶段不依赖地图。缺失的可选定位器、本地化文件会跳过。
英语和简体中文本地化读取所有选出 YML 文件中的地点名称条目：重复键优先使用较后的来源层，
同一层内使用文件名较后的值。缓存复制方法也使用解析后的文件来源。

**选中的阶段会清空各自输出目录内已有的普通文件。** 子目录保留，未选阶段保持不变。
仅地图模式因此只清理 `map_data/state_regions/`，保留已复制的历史、脚本、定位器和
本地化。必要的空白覆盖文件会抑制原始核心数据；被覆盖的陆地/海洋混合文件中的海洋节点
会保留。验证与输出内容准备完成后才开始清理。输入目录树与目标目录树不能重叠。

新的 `run()` 调用及使用任意新增配置选项的 CLI 调用，默认不注入合并补偿或附带静态资源。
使用 `integration_traits=True` 或 `--integration-traits` 启用补偿，并自动输出对应定义。
`ignore_small_states` 和 `small_state_limit` 影响补偿计算，不决定是否合并省份。
关闭补偿时保留已有特质。可单独使用 `assets=["usa_flag"]` 或 `--assets usa_flag`
选择资源：`state_traits`、`usa_flag`、`usa_state_counter`；`--assets none` 不选择资源。
显式资源只替换自身文件，不清理其他文件。不使用新增选项的原有 CLI、GUI 及
`merge_state_data()`、`merge_misc_data()`、`merge_loc_data()` 保留原有补偿和资源默认行为。

重复构建时可保留原有合并方案 JSON，另外创建执行配置 `build.json`：

```json
{
  "stages": ["map_data", "state", "pops", "buildings", "trade", "map_objects", "misc", "localization"],
  "sources": {"map_data": ["../game", "../resource-mod"]},
  "integration_traits": false,
  "assets": []
}
```

```sh
state-merger-cli merge_states.json /games/Victoria3/game /build/output --config build.json
```

配置中的来源路径相对于配置文件；命令行路径相对于当前工作目录。
命令行选项替换对应配置字段；来源选项只替换指定阶段的整个来源列表。
`--no-integration-traits` 可以覆盖配置中的 `true`。
Python `run_merge()` 以仅关键字参数接受 `stages`、`sources`、`integration_traits`、
`assets` 和 `config`。包同时导出 `STAGES` 和 `ASSETS` 常量。

部分输出用于其他 mod 的构建流程；其余内容需要自行组合或启用相应来源 mod。
工具不会自动调和复制的所有权历史与独立修改后的地理数据，不复制无关 mod 内容，
也不生成启动器元数据。当前地图模型仍不支持通用资源块、未知地图字段、`center_province`
和缺失字段修复。**RWR 的可发现资源仍需要适配器以避免数据丢失**；选择 mod 来源
并不消除这一限制。
不同文件中重复的定义仍按现有解析器的合并语义处理，可能被拒绝；需要定义级覆盖时，
应替换同名文件或预先整理输入数据。

### 开发检查

本项目需要 Python 3.14 或更高版本，并使用 [uv](https://docs.astral.sh/uv/)。
在代码仓库目录中执行以下命令，可以安装锁定的开发环境并运行持续集成中的检查：

```sh
uv sync --locked --group dev
uv run --locked pytest -m "not live"
uv run --locked ruff check .
uv run --locked ruff format --check .
uv build
```

测试会对核心合并模块强制要求至少 75% 的分支覆盖率。标记为 `live` 的测试需要
本地安装维多利亚3，因此不会在标准 CI 任务中运行。Pyright 在 CI 中只作为提示性检查。

可以使用以下命令运行可选的本地游戏冒烟测试：

```sh
VIC3_GAME_ROOT="/path/to/Victoria 3/game" uv run --locked pytest -m live --no-cov
```
  
### 3. 编辑 Spline Network

接下来是整个过程的最后一个**手动**部分。您需要编辑 spline network 以删除被合并省份的无效城市模型并重绘省份之间的新道路网络。

- 以调试模式打开维多利亚3游戏。
- 按 `~` 键打开控制台。
- 输入 `map_editor` 并按 `Enter` 键。
- 单击 `Spline Network` 选项卡或按 `9` 键。
- 选择 `Edit hub` 工具。
- 选择无效的城市模型（在顶部没有显示名称的）并按 `Delete` 键。
- 选择 `Add spline` 工具。
- 重新绘制剩余省份之间的道路连接。
- 详细信息请参考 [此 Steam 教程](https://steamcommunity.com/sharedfiles/filedetails/?id=3165669021)。

## 反馈

### Bug 反馈

如果您遇到任何问题，都请在 Issues 中提出。

## 声明

- 本 Python 脚本使用 [Pyradox](https://github.com/ajul/pyradox) 进行 Paradox 游戏文件解析。
- 维多利亚3游戏及其数据文件归 Paradox Interactive 所有。
- 本项目是非官方的 modding 工具，与 Paradox Interactive 无关。

# 开源许可

除 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) 中列明的第三方文件外，本仓库中的原创源代码、文档、数据和图稿均采用 [GNU 通用公共许可证第 3 版或后续版本](../LICENSE)，其中包括 `docs/images/icon.png` 和 `merge_states.json`。

GPL 不适用于 `src/vic3_state_merger/assets/flag_definitions_usa.py`，该文件改编自《维多利亚3》。生成文件中包含的 StateMerger 原创内置模板仍受 GPL 约束；但使用本工具处理用户提供的游戏数据，并不会自动使这些输入数据适用 GPL。有关材料来源、权利归属和适用条款，请参阅 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。
