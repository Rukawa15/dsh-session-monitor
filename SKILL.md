---
name: dsh-session-monitor
description: 查看与监控本机所有 DeepSeek Harness (DSH) 会话的实时状态、正在运行的任务与完整历史内容。当用户想查看其他会话或全部会话在干什么、任务进度、是否还在运行，或导出某个会话的完整对话记录时使用本技能。
---

# DSH 会话监视器 (dsh-session-monitor)

只读读取 `~/.dsh/sessions/` 下所有 DSH 会话文件（多帧 zstd 压缩的 JSONL 事件流）。
DSH 按事件实时落盘（step/工具调用/结果都是即时写入），因此本技能能以秒级新鲜度反映其他会话的当前状态。

## 运行方式

需要 Python 3 与 zstandard 库（缺失时先执行 `pip install zstandard`）。
本技能脚本位于技能目录下 `scripts/monitor.py`（开发目录 `D:\dsh-session-moniter`）。

```
python <技能目录>/scripts/monitor.py status                  # 全部会话状态总览
python <技能目录>/scripts/monitor.py board [--top 5]        # 固定格式任务看板(IM 查询用)
python <技能目录>/scripts/monitor.py status --cwd D:\LQ\v2   # 只看某个工作区的会话
python <技能目录>/scripts/monitor.py tail <会话ID前缀> -n 20 # 某会话最近 20 条事件
python <技能目录>/scripts/monitor.py wait <会话ID前缀> --timeout 600  # 阻塞等待该会话新回复(信使用)
python <技能目录>/scripts/monitor.py wait <会话ID前缀> --notify [--to 名称]  # 回复自动投递到 IM
python <技能目录>/scripts/monitor.py notify --text "..." [--to 名称 ...]      # 主动发消息(可多渠道)
python <技能目录>/scripts/monitor.py dump <会话ID前缀> -o 导出.md  # 导出完整对话
```

status / board 的 `--json` 可输出机器可读格式，便于进一步加工。

## 可配置参数

阈值与条数可在 `~/.dsh/dsh-session-monitor.json` 调整（0.3.0+ 也可在
DSH 设置页 → 「DSH 会话监视器」分区图形化调整）：

- `poll_interval_sec`：wait 命令轮询间隔（默认 10）
- `running_threshold_sec`：活跃→疑似中断阈值秒数（默认 900）
- `zombie_hours`：僵尸隐藏阈值小时数（默认 24）
- `board_top` / `board_max_running`：看板条数（默认 5 / 10）
- `delivery`：主动投递配置，**渠道无关**（微信/QQ/飞书等通用）：命名目标表
  `targets`（每项 `{botId, targetId, format?}`，设置 → IM机器人里复制）、
  `default` 缺省目标名、`format`/`max_chars`（默认 plain/1800）、`host_port`
  （留空自动发现）；兼容旧版平铺键 delivery_bot_id/delivery_target_id

命令行显式参数优先于配置文件；无配置文件时使用默认值。

## 主动投递的前置检测与引导

目标配置统一由 dsh-im 管理（设置 → IM机器人，官方 UI 支持测试）；
本插件只做检测、引导与调用：

- dsh-im 未安装 → 引导用户到插件市场安装（搜索 dsh-im / @xmanrui/dsh-im）
- 已安装但无投递目标 → 引导到 设置 → IM机器人 → 齿轮 → 新建目标；
  **消息来自机器人时**若未配置，顺带提示一次，已配置则不提
- dsh-im 投递核心被 HTTP POST / 宿主 ctx.dshIm.send / Connection RPC 三条
  路径共用；本插件走宿主桥，天然兼容，旧宿主自动回退 HTTP 端点

## 输出解读

- `[RUNNING]`：该会话正在运行（文件 15 分钟内有写入且最后一轮未结束）
- `[STALLED]`：有未完成的轮次但已超过 15 分钟无写入（可能中断/挂起）
- `[IDLE]`：空闲，最后一轮已正常结束
- `[ABORTED]`：最后一轮被用户手动中止
- `turn N step M`：最近记录到的轮次/步骤号
- `最新活动`：最后一条有信息量的事件（用户消息 / AI 消息 / 工具调用）

## 任务看板与 IM 查询（board 命令，固定输出格式）

`board` 输出由脚本完全固定，三段式：**▶ 活跃中**（轮次未结束且 15 分钟内有写入，
最多 10 条）、**⏸ 疑似中断**（轮次未结束但超 15 分钟无写入，可能是中断残留或
超长工具执行；超 24 小时的僵尸会话不显示）、**✔ 已完成任务 Top N**（默认 5，
`--top` 可调），均按最后更新时间由新到旧；每条包含 工作区 / 短ID / 任务标题
（该会话第一条真实用户消息，系统注入已按 source.kind 白名单过滤）/ 进度 / 最近动作，
截断长度固定。用户问「现在在跑什么」时看「活跃中」一段即可。

当用户通过 IM（dsh-im 等通讯软件接入的会话）询问「现在在跑什么任务」「任务进度」
「最近完成了什么」时：

1. 运行 `board`；若知道当前会话自身的 ID，加 `--exclude <自身ID前缀>`，
   避免把正在回答的机器人会话自己列为「进行中」
2. 将脚本 stdout **原样发送**给用户：不要改写、不要总结、不要增删格式——
   这是保证每个用户每次看到的界面完全一致的约定
3. 用户想深入某个任务时，再用 `tail <短ID>` 查看该会话最近事件

## 注意事项

- 全部操作只读，不会修改、不会干预任何会话。
- 会话文件按"事件"粒度实时写入，因此能看到正在运行会话的工具调用序列与步骤推进，
  但 AI 正在流式生成的文本要等该条消息完成才会出现。
- 读取其他用户/其他机器的会话不适用：只读本机当前用户 ~/.dsh 下的数据。
