# DSH 会话监视器 (dsh-session-monitor)

实时掌握本机所有 DeepSeek Harness (DSH) 会话动态的**只读**工具——谁在跑、
跑什么、进展如何；配合 dsh-im 插件还能把结果推送到微信/QQ/飞书等 IM。

> 当前版本 **0.5.2** · 任何时刻运行 `python scripts/monitor.py help` 可获取
> 完整的固定格式使用指南（`help <指令名>` 看单指令详情）。全部操作只读，
> 不会修改或干扰任何会话。

## 功能总览

| 功能 | 指令 | 说明 |
|---|---|---|
| 会话状态总览 | `status` | 全部会话的 RUNNING/STALLED/IDLE/ABORTED、轮次/步骤、最新动作 |
| 任务看板 | `board` | 固定格式三段式：▶ 活跃中 / ⏸ 疑似中断 / ✔ 已完成 TopN（IM 查询首选） |
| 深入某任务 | `tail <短ID>` | 某会话最近 N 条事件（用户消息/AI 消息/工具调用） |
| 等待回复 | `wait <短ID>` | 阻塞等到该会话本轮结束并打印 AI 回复；`--notify` 自动推送到 IM |
| 主动推送 | `notify --text "..."` | 经 dsh-im 把消息发到微信/QQ/飞书等（`--to` 选目标） |
| 导出对话 | `dump <短ID> -o 文件.md` | 某会话完整对话导出为 Markdown |
| 使用指南 | `help [指令名]` | 本指南的命令行版，输出格式完全固定 |

所有指令支持 `--cwd 路径` 只看某个工作区；`status`/`board`/`wait` 支持
`--json` 机器可读输出。会话短 ID 取会话 ID 前 8 位左右即可。

## 安装

**依赖**：核心功能仅需 Python 3 与 `zstandard`（缺失时 `pip install zstandard`）；
IM 推送需另装 [dsh-im](https://github.com/xmanrui/dsh-im) 插件（可选，缺失时
相关命令会给出安装/配置引导，其余功能不受影响）。

两种安装形态（本机均已就绪）：

- **插件包（当前启用）**：在 DSH「插件管理」中通过本地路径
  `D:\dsh-session-moniter` 安装（pnpm link 直链开发目录，改代码后重启 DSH 生效）。
  设置页、依赖检测等完整功能均来自这一形态。
- **技能目录（形态A）**：`C:\Users\admin\.agents\skills\dsh-session-monitor`
  （junction 指向开发目录）。仅技能入口，适合不装插件包时让 AI 助手调用脚本。
- ⚠️ 两种形态同时启用时技能会重复出现；插件包安装成功后建议删除 junction。

## 快速上手

```powershell
# 现在在跑什么任务？
python scripts\monitor.py board

# 某个任务进展如何？（短ID看板里有）
python scripts\monitor.py tail 0a29d310 -n 20

# 等某会话出结果，出来后推送到飞书
python scripts\monitor.py wait 0a29d310 --timeout 600 --notify

# 主动发一条消息到 IM
python scripts\monitor.py notify --text "构建完成" --to feishu

# 导出某会话完整对话
python scripts\monitor.py dump 0a29d310 -o 会话导出.md

# 完整使用指南（固定格式，可直接转发给任何提问的用户）
python scripts\monitor.py help
```

## 两个技能（AI 助手自动调用，无需手敲命令）

- **dsh-session-monitor**：当您问「其他会话在干什么 / 任务进度如何 /
  现在在跑什么」时，AI 助手自动调用 board/tail/status 并把 board 的固定
  输出**原样**回复给您。
- **dsh-session-relay**（跨会话信使）：当您说「去XX会话发句话 / 帮我问一下
  并带回回复 / 让XX任务继续」时使用——AI 经 GUI 代为发送，`wait` 阻塞等待
  对方回复，再以固定格式转发给您。

当您（尤其经 IM 接入时）问「这个插件怎么用 / 有什么功能」时，AI 助手会
运行 `help` 并把指南**原样发送**——与看板相同的固定输出约定。

## 设置页

DSH **设置 → 「DSH 会话监视器」**：

- 调整轮询间隔 / 活跃判定阈值 / 僵尸隐藏阈值 / 看板条数；
- 顶部「依赖插件检测」状态卡实时显示 dsh-im 连接情况（未安装 → 引导到
  插件市场；已连接无目标 → 引导到 设置→IM机器人 新建目标；正常 → 显示
  机器人与目标数量），支持一键「重新检测」。

## 配置（优先级：命令行参数 > 配置文件 > 默认值）

三种入口，设置页与配置文件是**同一份数据**：

1. 设置页图形界面（最省心）
2. 直接编辑 `~/.dsh/dsh-session-monitor.json`（手改后对之后运行的命令立即生效）
3. 命令行参数临时覆盖（如 `board --top 10`、`wait --poll 5`，只对当次生效）

可调项：`poll_interval_sec`（默认 10）、`running_threshold_sec`（900）、
`zombie_hours`（24）、`board_top`（5）、`board_max_running`（10）、
`delivery`（IM 投递回退配置；正式目标由 dsh-im 统一管理）。

## 状态与看板解读

- `[RUNNING]` 正在运行（15 分钟内有写入且本轮未结束）
- `[STALLED]` 疑似中断（本轮未结束但超 15 分钟无写入）
- `[IDLE]` 空闲（本轮已正常结束）· `[ABORTED]` 最后一次轮次被手动中止
- 看板「活跃中/疑似中断」各最多显示 `board_max_running` 条，超过 24 小时
  无更新的僵尸会话不再显示；「已完成」按更新时间取前 `board_top` 条

## 数据与隐私

数据源为本机当前用户的 `~/.dsh/sessions/<工作区分组>/<会话ID>/session.v4.jsonl.zstd`
（多帧 zstd 压缩的 JSONL 事件流，DSH 按事件实时落盘，因此能以秒级新鲜度
反映各会话状态）。只读本机当前用户数据；不修改、不上传、不干预任何会话。
