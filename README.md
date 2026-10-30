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

---

# 开发者附录

## 版本规范（语义化版本）

- **补丁位**（0.5.x）：小修复、小补丁——bug 修复、文案调整、微调参数
- **次版本**（0.x.0）：新功能、行为变更（如新增命令、交互流程调整）
- **主版本**（x.0.0）：不兼容的破坏性变更（暂未使用）

每次版本变更同步更新 `package.json` 与本文件的版本记录，并提交推送到远程仓库。

## 版本记录

- **0.5.2** — README 重构为**用户使用指南**：功能总览表 / 安装 / 快速上手 /
  技能说明 / 设置页 / 配置 / 看板解读 / 数据与隐私；版本规范与版本记录等
  开发者信息移至文末附录
- **0.5.1** — 新增 **`help` 指令**（用户指南固定输出）：`monitor.py help`
  打印完整固定格式使用指南（功能清单/技能/设置页/配置优先级/常见问法→
  指令/依赖说明），`help <指令名>` 输出单指令的用法与示例（主题：
  status/board/tail/wait/notify/dump/help/config/install），未知主题列出
  可用主题；指南版本号读 package.json 单一来源。两份 SKILL.md 同步增加
  约定：用户问「这插件怎么用/有什么功能」时运行 help 并把 stdout **原样
  发送**（与 board 相同的固定输出约定）
- **0.5.0** — 设置页新增**依赖插件检测**：宿主半常驻路由
  `GET /session-monitor/status`（`ctx.get('dshIm')` 无侵入探测，不需要 inject
  声明，服务缺席返回 undefined 不抛错），返回版本号 + dshIm 三态信息
  （available / bots 数 / targets 数 / 部分列举错误）；客户端设置页顶部渲染
  「依赖插件检测」状态卡：**未安装**（引导到插件市场装 dsh-im）/ **已连接无
  目标**（引导到 设置→IM机器人 新建目标）/ **正常**（显示机器人与目标数），
  另有「宿主半为旧版本」降级态与「重新检测」按钮；标题旁显示插件版本号
- **0.4.3** — **根因修复设置页「宿主配置服务未连接」**：0.4.0 起宿主半调用的
  `ctx.connection.fetch.register` 是**不存在的 API**（`connection` 是客户端侧服务名），
  TypeError 被 try/catch 静默吞掉，路由从未注册过。正确机制（对照 dsh-im 源码）是
  `ctx.webServer.register({kind:'exact', path, handler(req,res)})`（宿主 `webServer`
  服务，原生 Node 处理器）。静态 inject 只声明 `webServer`（任何已启动 profile 必有，
  无 dsh-im 时设置页配置也可用）；`dshIm` 改为命令式 `ctx.inject(['dshIm'],...)` 挂载
  delivery/deliver 路由，服务出现即挂载、消失即卸载。已在隔离 profile
  （base + web-app + 假 dshIm 提供者）验证：config GET 200 / 非法 JSON 400 /
  delivery available:true / deliver 参数校验 400
- **0.4.2** — 修复宿主路由 404 与启动崩溃：根因是本 Cordis 的 `ctx` 代理
  **不声明 inject 就读不到服务**（`ctx.connection` 一直为 undefined，路由
  注册被静默吞掉）；改为 `inject: ['connection', 'dshIm']` 并同步注册；
  移除 0.4.1 引入的 setTimeout 重试（其在插件重载后对失活上下文调用
  `ctx.effect`，导致宿主 `INACTIVE_EFFECT` 崩溃，见 crash-2026-10-30 日志）
- **0.4.1** — 修复设置页「宿主配置服务未连接」：0.4.0 的声明式
  `inject: ['dshIm']` 会让宿主半在服务缺席时整体不激活（连带 config 路由
  消失）；改为请求时惰性访问 dshIm + 路由注册延迟重试（需重启 DSH 生效）
- **0.4.0** — 投递职责重构：目标配置完全交由 **dsh-im 管理**（设置页官方 UI），
  本插件只做检测/引导/调用；宿主半 `inject: dshIm` 暴露 delivery/deliver 桥
  （listBots/listTargets 自动发现 + ctx.dshIm.send 统一走 dsh-im 投递核心，
  兼容 HTTP/RPC 三条官方路径）；三态引导（未安装/无目标/正常）；机器人会话
  来源的提示规则；本地 delivery.targets 降级为回退路径（需重启 DSH 生效）
- **0.3.2** — 投递目标改为**命名目标架构**（渠道无关：微信/QQ/飞书/钉钉等可
  混配任意多个）；`--to` 按名路由、可多选；兼容旧版平铺配置键
- **0.3.1** — **主动投递集成**：`notify` 子命令与 `wait --notify`
  （监测会话回复后自动推送 IM）；对接 dsh-im Proactive Delivery HTTP 接口，
  Host 端口自动发现；`delivery_*` 配置项（bot/target/format/截断上限/端口）；
  实测飞书链路 `{"sent":true}`
- **0.3.0** — 设置页配置界面（client.js 注册 `settings.section` + 宿主
  `/session-monitor/config` 路由，实验性，需重装/重启 DSH 验证）；
  **增量读取**（帧扫描 + `decompressobj.eof` 完整性判定 + seq 去重，
  wait 高频轮询不再全量解压文件）；配置文件系统
  `~/.dsh/dsh-session-monitor.json`（轮询间隔/活跃阈值/僵尸阈值/看板条数）；
  自动化测试 `scripts/test_incremental.py`（含半帧截断场景）；插件图标
- **0.2.0** — 信使交互规范化：发送前固定反问「需要我在该任务结束后把结果
  反馈给您吗？」；回传固定格式（注明来源会话与等待时长）；全插件敬称审核
  （对用户称呼统一用「您」）；`wait` 命令（阻塞等待会话新回复）
- **0.1.0** — 初版：status / board(三段式看板) / tail / dump；
  插件包(bundle)结构 + 技能 junction 双形态安装

## 结构

- `package.json`        npm 包清单（name + `dsh.bundle.patch` + `dsh.client` 客户端声明）
- `cordis.patch.yml`    组合包补丁（把本插件插入 agent preset）
- `index.js`            Host 半：经 `ctx.webServer.register` 注册三条 HTTP 路由
                        （config 读写 / delivery 能力 / deliver 投递，见 0.4.3 说明）
- `client.js`           Client 半：设置页「DSH 会话监视器」分区（React 表单）
- `icon.svg`            插件图标
- `locale/zh|en.json`   插件管理器里显示的标题与描述
- `skills/dsh-session-monitor/SKILL.md`  插件包标准位置的技能入口（会话监视）
- `skills/dsh-session-relay/SKILL.md`    跨会话信使技能（GUI 发送 + wait 等待回复 + 转发）
- `SKILL.md`            根位置技能入口（形态A junction 使用，安装插件后可删）
- `scripts/monitor.py`  主脚本（status / board / tail / wait / notify / dump / help）
- `scripts/grep_sessions.py`  会话存档正则搜索工具（找回历史命令/URL/报错原文）
- `scripts/test_profile_import.mjs`  插件包解析导入诊断（以 profile 为锚点）
- `requirements.txt`    Python 依赖（zstandard）

## 测试

```
python scripts\monitor.py status
python scripts\monitor.py board --exclude <自身会话ID前缀>
python scripts\monitor.py tail 0a29d310 -n 10
python scripts\monitor.py dump 0a29d310 -o test-export.md
python scripts\test_incremental.py
```
