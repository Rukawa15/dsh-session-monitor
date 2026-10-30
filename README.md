# dsh-session-moniter (开发目录)

DSH 会话监视器插件的开发目录。当前版本 **0.5.0**（隔离环境已验证，桌面端待重启验证）。

## 版本规范（语义化版本）

- **补丁位**（0.4.x）：小修复、小补丁——bug 修复、文案调整、微调参数
- **次版本**（0.x.0）：新功能、行为变更（如新增命令、交互流程调整）
- **主版本**（x.0.0）：不兼容的破坏性变更（暂未使用）

每次版本变更同步更新 `package.json` 与本文件的版本记录，并提交推送到远程仓库。

## 版本记录

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

## 安装形态

- 开发位置（本目录）: `D:\dsh-session-moniter`
- 形态A 技能目录: `C:\Users\admin\.agents\skills\dsh-session-monitor` -> junction 指向本目录
- 形态B 插件包: 本目录已具备标准 bundle 结构，可在 DSH「插件管理」中
  通过本地路径 `D:\dsh-session-moniter` 安装（需 pnpm）
- 注意：两种形态同时启用时技能会重复出现；UI 安装成功后建议删除 junction

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
- `scripts/monitor.py`  主脚本（status / board / tail / wait / dump）
- `requirements.txt`    Python 依赖（zstandard）

## 数据源

`~/.dsh/sessions/<工作区分组>/<会话ID>/session.v4.jsonl.zstd`
多帧 zstd 流，每帧之后追加 JSONL 事件（session 头 / user/message / assistant/* /
tool/call / tool/result / step|turn start-end / model/selection 等，time 为 epoch 毫秒）。

## 测试

```
python scripts\monitor.py status
python scripts\monitor.py board --exclude <自身会话ID前缀>
python scripts\monitor.py tail 0a29d310 -n 10
python scripts\monitor.py dump 0a29d310 -o test-export.md
```
