#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dsh-session-monitor -- 读取本机所有 DeepSeek Harness (DSH) 会话的状态与内容。

用法:
  python monitor.py status [--cwd D:\\path] [--json]     所有会话状态总览
  python monitor.py board [--top 5] [--exclude ID]      固定格式任务看板(进行中+已完成TopN)
  python monitor.py wait <会话ID前缀> [--timeout 300]   阻塞等待该会话产生新回复并打印
  python monitor.py notify --text "..." [--bot --target]  经 dsh-im 主动投递发消息到 IM
  python monitor.py tail <会话ID前缀> [-n 20]            某会话最近 N 条事件
  python monitor.py dump <会话ID前缀> [-o out.md]        导出完整对话为 Markdown
  python monitor.py help [指令名]                        固定格式使用指南(用户问"怎么用"时原样输出)

只读操作，不会修改任何会话文件。
"""
import argparse
import datetime
import io
import json
import os
import sys
import time

# Windows 控制台默认 GBK, 强制 UTF-8 输出, 无法编码的字符用替代符, 避免崩溃与乱码
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

SESSIONS_DIR = os.path.join(os.path.expanduser('~'), '.dsh', 'sessions')
MAX_OUTPUT = 400_000_000
ZSTD_MAGIC = b'\x28\xb5\x2f\xfd'

# 可调参数: 默认值 <- ~/.dsh/dsh-session-monitor.json <- 命令行参数(部分)
CONFIG_PATH = os.path.join(os.path.expanduser('~'), '.dsh', 'dsh-session-monitor.json')
CONFIG_DEFAULTS = {
    'poll_interval_sec': 10,      # wait 命令轮询间隔(秒)
    'running_threshold_sec': 900, # 无更新超过该秒数 -> 疑似中断
    'zombie_hours': 24,           # 无更新超过该小时数且未结束 -> 不显示在看板
    'board_top': 5,               # 已完成任务榜单条数
    'board_max_running': 10,      # 进行中/疑似中断最多显示条数
    # 主动投递(dsh-im Proactive Delivery): 渠道无关(微信/QQ/飞书/钉钉/...), 命名目标可配任意多个
    'delivery': {},
    # delivery 结构:
    #   {"default": "feishu",                       缺省目标名
    #    "targets": {"feishu": {"botId": "...", "targetId": "..."},
    #                "wechat": {"botId": "...", "targetId": "...", "format": "markdown"}},
    #    "format": "plain", "max_chars": 1800, "host_port": null}
}


def load_config():
    cfg = dict(CONFIG_DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def _iter_frames(data, dctx):
    """按魔数扫描并逐帧独立解压(每帧一个 decompressobj)。

    用 decompressobj.eof 判定帧完整性: 残缺尾帧(eof=False)会返回部分输出,
    必须丢弃, 等待后续字节补全后再整帧重解。已验证: 逐帧解压总行数 ==
    跨帧流式解压总行数(23 个会话一致)。
    """
    pos = 0
    while True:
        i = data.find(ZSTD_MAGIC, pos)
        if i < 0:
            return
        try:
            dobj = dctx.decompressobj()
            out = dobj.decompress(data[i:])
            if out and getattr(dobj, 'eof', True):
                yield out
        except Exception:
            pass
        pos = i + len(ZSTD_MAGIC)


def load_events(path):
    """解压 session.v4.jsonl.zstd（多帧 zstd 流），返回事件 dict 列表。"""
    try:
        import zstandard
    except ImportError:
        print('缺少依赖: 请先运行  pip install zstandard', file=sys.stderr)
        sys.exit(2)
    dctx = zstandard.ZstdDecompressor()
    raw = open(path, 'rb').read()
    events = []
    buf = b''
    for out in _iter_frames(raw, dctx):
        data = buf + out
        *complete, buf = data.split(b'\n')
        for line in complete:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                pass
    if buf.strip():
        try:
            events.append(json.loads(buf.decode('utf-8', 'replace').strip()))
        except Exception:
            pass
    return events


class SessionTail:
    """增量跟踪一个会话文件: 初次全量加载, 之后只解压新增字节。

    内部维护 self.tail(最后一个成功帧起点到文件末尾的字节)与事件去重(seq 单调递增)。
    用于 wait 命令的高频轮询, 避免每次完整解压整个文件。
    """

    def __init__(self, path):
        import zstandard
        self.path = path
        self.dctx = zstandard.ZstdDecompressor()
        self.file_pos = 0        # 已从文件读出的字节位置
        self.tail = b''          # 待续字节(含最后一个成功帧, 重新扫描时按 seq 去重)
        self.buf = b''           # 跨帧不完整行
        self.events = []
        self.max_seq = 0
        self._append_bytes(open(path, 'rb').read())
        self.file_pos = os.path.getsize(path)

    def _append_bytes(self, data):
        merged = self.tail + data
        pos = 0
        last_ok = None
        while True:
            i = merged.find(ZSTD_MAGIC, pos)
            if i < 0:
                break
            try:
                dobj = self.dctx.decompressobj()
                out = dobj.decompress(merged[i:])
                complete = bool(out) and getattr(dobj, 'eof', True)
            except Exception:
                out, complete = None, False
            if complete:
                last_ok = i  # 该帧完整; 尾部回退点为本帧起点(字节级帧长未知)
                chunk = self.buf + out
                *complete_lines, self.buf = chunk.split(b'\n')
                for line in complete_lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    seq = ev.get('seq', 0)
                    if seq and seq <= self.max_seq:
                        continue  # 尾部回退导致的重复帧, 按 seq 去重
                    if seq:
                        self.max_seq = seq
                    self.events.append(ev)
                pos = i + len(ZSTD_MAGIC)
            else:
                # 残缺尾帧(部分输出必须丢弃, 防止污染行缓冲)或伪魔数: 继续扫描
                pos = i + len(ZSTD_MAGIC)
        # 本批有完整帧: 尾部从其起点开始(下轮重扫该帧, seq 去重兜底);
        # 本批无完整帧: 保留全部合并字节, 等待帧被后续字节补全。
        self.tail = merged[last_ok:] if last_ok is not None else merged

    def poll(self):
        """读取新增文件字节, 返回本次新追加的事件列表。文件变小视为重写, 全量重载。"""
        size = os.path.getsize(self.path)
        if size < self.file_pos - len(self.tail) - 65536:
            # 文件被截断/重写: 重置
            self.__init__(self.path)
            return []
        if size == self.file_pos and not self.tail:
            return []
        with open(self.path, 'rb') as f:
            f.seek(self.file_pos)
            new = f.read()
        if not new:
            return []
        before = len(self.events)
        self._append_bytes(new)
        self.file_pos = size
        return self.events[before:]


def fmt_time(ms):
    try:
        return datetime.datetime.fromtimestamp(ms / 1000).strftime('%m-%d %H:%M:%S')
    except Exception:
        return '?'


def fmt_age(sec):
    if sec < 60:
        return f'{sec:.0f}秒前'
    if sec < 3600:
        return f'{sec / 60:.1f}分钟前'
    if sec < 86400:
        return f'{sec / 3600:.1f}小时前'
    return f'{sec / 86400:.1f}天前'


def content_text(content):
    """从消息 content 结构中提取可读文本。"""
    if isinstance(content, str):
        return content
    parts = []
    if isinstance(content, list):
        for c in content:
            if not isinstance(c, dict):
                continue
            t = c.get('type')
            if t == 'text':
                parts.append(c.get('text', ''))
            elif t == 'tool-call':
                parts.append('[调用工具 %s 参数=%s]' % (c.get('name'), str(c.get('arguments'))[:120]))
    return ' '.join(p.strip() for p in parts if p and p.strip())


# 真实用户输入的 source.kind 白名单(其余 time-context/runtime-context/skill-catalog/
# user-approval/model-selection/goal/... 均为 harness 系统注入, 不作为任务标题/动作)
REAL_USER_KINDS = ('user', 'plugin:dsh-im', 'schedule')


def is_real_user_msg(d):
    return (d.get('source') or {}).get('kind') in REAL_USER_KINDS


def extract_title(ev):
    """取第一条真实用户消息作为任务标题（按 source.kind 白名单过滤系统注入）。"""
    for e in ev:
        if e.get('type') != 'user/message':
            continue
        d = e.get('data', {}) or {}
        if not is_real_user_msg(d):
            continue
        txt = content_text(d.get('content')).strip()
        if not txt:
            continue
        return ' '.join(txt.split())[:50]
    return '(无用户输入)'


def short_id(sid):
    return sid.replace('session-', '')[:8]


def find_sessions():
    """遍历所有会话: yield (group_dir, session_dir, file_path)。"""
    if not os.path.isdir(SESSIONS_DIR):
        print('未找到会话目录: %s' % SESSIONS_DIR, file=sys.stderr)
        sys.exit(2)
    for group in sorted(os.listdir(SESSIONS_DIR)):
        gdir = os.path.join(SESSIONS_DIR, group)
        if not os.path.isdir(gdir):
            continue
        for sd in sorted(os.listdir(gdir)):
            p = os.path.join(gdir, sd, 'session.v4.jsonl.zstd')
            if os.path.isfile(p):
                yield group, sd, p


def session_summary(group, sdir, path, cfg=None):
    cfg = cfg or load_config()
    ev = load_events(path)
    st = os.stat(path)
    now = time.time()
    age = now - st.st_mtime
    header = next((e for e in ev if e.get('type') == 'session'), {})
    cwd = header.get('cwd', '')
    model = None
    last_turn_end = None
    turn = step = None
    last_user_idx = -1
    for i, e in enumerate(ev):
        t = e.get('type')
        if t == 'model/selection':
            model = e.get('data', {}).get('model')
        elif t == 'turn/end':
            last_turn_end = e
        elif t == 'user/message':
            last_user_idx = i
        elif t == 'step/start':
            d = e.get('data', {})
            turn, step = d.get('turn'), d.get('step')

    last_type = ev[-1].get('type', '') if ev else ''
    unfinished = bool(ev) and last_type != 'turn/end' and last_user_idx >= 0
    if unfinished and age < cfg['running_threshold_sec']:
        state = 'RUNNING'
    elif unfinished:
        state = 'STALLED'
    else:
        state = 'IDLE'
    aborted = bool(last_turn_end and (last_turn_end.get('data', {}).get('reason') or {}).get('kind') == 'aborted')

    desc, desc_time = '', None
    for e in reversed(ev):
        t = e.get('type')
        d = e.get('data', {}) or {}
        if t == 'assistant/message':
            txt = content_text((d.get('message') or {}).get('content'))
            if txt:
                desc, desc_time = 'AI: ' + txt[:160], e.get('time')
                break
        elif t == 'tool/call':
            desc, desc_time = '工具 %s %s' % (d.get('name'), str(d.get('arguments'))[:100]), e.get('time')
            break
        elif t == 'user/message':
            if not is_real_user_msg(d):
                continue
            txt = content_text(d.get('content'))
            if txt:
                desc, desc_time = '用户: ' + txt[:160], e.get('time')
                break
    return {
        'group': group, 'id': sdir, 'cwd': cwd, 'events': len(ev),
        'title': extract_title(ev),
        'created': header.get('createdAt'), 'mtime': st.st_mtime, 'age_sec': age,
        'model': model, 'state': state, 'turn': turn, 'step': step,
        'last_desc': desc, 'last_time': desc_time, 'aborted': aborted,
    }


def brief(e):
    t = e.get('type', '?')
    d = e.get('data', {}) or {}
    if t == 'user/message':
        return '用户: ' + content_text(d.get('content'))[:120]
    if t == 'assistant/message':
        return 'AI: ' + content_text((d.get('message') or {}).get('content'))[:120]
    if t == 'assistant/attempt':
        return 'AI 开始生成'
    if t == 'tool/call':
        return '工具调用 %s %s' % (d.get('name'), str(d.get('arguments'))[:100])
    if t == 'tool/result':
        msg = d.get('message', {}) or {}
        txt = content_text(msg.get('content'))[:100]
        return ('工具结果[错误]: ' if msg.get('isError') else '工具结果: ') + txt
    if t == 'step/start':
        return '步骤开始 turn %s step %s' % (d.get('turn'), d.get('step'))
    if t == 'step/end':
        return '步骤结束 turn %s step %s' % (d.get('turn'), d.get('step'))
    if t == 'turn/end':
        return '轮次结束(%s)' % ((d.get('reason') or {}).get('kind'))
    if t == 'model/selection':
        return '模型切换 %s/%s' % (d.get('provider'), d.get('model'))
    return t


def match_sid(prefix, cwd_filter=None):
    hits = []
    for group, sd, p in find_sessions():
        if sd.startswith(prefix) or prefix in sd:
            hits.append((group, sd, p))
    if not hits:
        print('未找到匹配 %r 的会话' % prefix, file=sys.stderr)
        sys.exit(1)
    if len(hits) > 1:
        print('匹配到多个会话, 请用更长前缀:')
        for g, s, _ in hits:
            print('  %s  (组 %s)' % (s, g))
        sys.exit(1)
    return hits[0]


def cmd_status(args):
    rows = []
    for group, sd, p in find_sessions():
        s = session_summary(group, sd, p)
        if args.cwd:
            key = args.cwd.lower().replace('/', '\\')
            if key not in s['cwd'].lower().replace('/', '\\') and key not in group.lower():
                continue
        rows.append(s)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        print('没有匹配的会话')
        return
    rows.sort(key=lambda r: r['mtime'], reverse=True)
    groups = {}
    for r in rows:
        groups.setdefault(r['group'], []).append(r)
    for g in sorted(groups, key=lambda k: groups[k][0]['mtime'], reverse=True):
        r0 = groups[g][0]
        print('== 工作区 %s  (组 %s) ==' % (r0['cwd'] or '?', g))
        for r in groups[g]:
            flag = '[RUNNING]' if r['state'] == 'RUNNING' else ('[STALLED]' if r['state'] == 'STALLED' else ('[IDLE    ]' if not r['aborted'] else '[ABORTED ]'))
            pos = ('turn %s step %s' % (r['turn'], r['step'])) if r['turn'] is not None else ''
            print('%s %s  %s  模型=%s  %d条事件  最后写入 %s(%s)' % (
                flag, r['id'][:20], pos, r['model'] or '?', r['events'],
                fmt_time(r['mtime'] * 1000), fmt_age(r['age_sec'])))
            if r['last_desc']:
                lt = fmt_time(r['last_time']) if r['last_time'] else ''
                print('     最新活动 %s: %s' % (lt, r['last_desc'][:160]))
        print()


def cmd_board(args):
    cfg = load_config()
    zombie_sec = float(cfg['zombie_hours']) * 3600
    top = args.top if args.top is not None else int(cfg['board_top'])
    max_running = args.max_running if args.max_running is not None else int(cfg['board_max_running'])
    rows = []
    for group, sd, p in find_sessions():
        s = session_summary(group, sd, p, cfg)
        if args.cwd:
            key = args.cwd.lower().replace('/', '\\')
            if key not in s['cwd'].lower().replace('/', '\\') and key not in group.lower():
                continue
        rows.append(s)
    ex = args.exclude or []
    rows = [r for r in rows if not any(r['id'].startswith(e) or e in r['id'] for e in ex)]
    active = sorted([r for r in rows if r['state'] == 'RUNNING'],
                    key=lambda r: r['mtime'], reverse=True)
    stalled = sorted([r for r in rows if r['state'] == 'STALLED' and r['age_sec'] < zombie_sec],
                     key=lambda r: r['mtime'], reverse=True)
    done = sorted([r for r in rows if r['state'] == 'IDLE'],
                  key=lambda r: r['mtime'], reverse=True)
    if args.json:
        print(json.dumps({
            'generated': datetime.datetime.now().isoformat(timespec='seconds'),
            'active': active[:max_running],
            'stalled': stalled[:max_running],
            'done': done[:top],
        }, ensure_ascii=False, indent=2))
        return
    stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print('【DSH 任务看板】%s · %d 个工作区 / %d 个会话' % (
        stamp, len(set(r['group'] for r in rows)), len(rows)))
    print()

    def print_entry(i, r):
        print('%d. %s · %s' % (i, r['cwd'] or r['group'], short_id(r['id'])))
        print('   任务：%s' % r['title'])
        if r['turn'] is not None:
            print('   进度：第%s轮 第%s步 · 更新 %s（%s）' % (
                r['turn'], r['step'],
                datetime.datetime.fromtimestamp(r['mtime']).strftime('%m-%d %H:%M:%S'),
                fmt_age(r['age_sec'])))
        else:
            print('   更新：%s（%s）' % (
                datetime.datetime.fromtimestamp(r['mtime']).strftime('%m-%d %H:%M:%S'),
                fmt_age(r['age_sec'])))
        if r['last_desc']:
            print('   动作：%s' % ' '.join(r['last_desc'].split())[:40])

    print('▶ 活跃中（%d）' % len(active))
    if not active:
        print('（当前没有正在运行的任务）')
    for i, r in enumerate(active[:max_running], 1):
        print_entry(i, r)
    if len(active) > max_running:
        print('   …另有 %d 个活跃会话未列出' % (len(active) - max_running))
    print()
    print('⏸ 疑似中断（%d）' % len(stalled))
    if not stalled:
        print('（无疑似中断的会话）')
    for i, r in enumerate(stalled[:max_running], 1):
        print_entry(i, r)
    if len(stalled) > max_running:
        print('   …另有 %d 个疑似中断的会话未列出' % (len(stalled) - max_running))
    print()
    print('✔ 已完成任务 Top%d（按更新时间由新到旧）' % top)
    if not done:
        print('（暂无已完成的会话）')
    for i, r in enumerate(done[:top], 1):
        ab = ' · 已中止' if r['aborted'] else ''
        print('%d. %s · %s · %s%s' % (
            i, r['cwd'] or r['group'], short_id(r['id']),
            datetime.datetime.fromtimestamp(r['mtime']).strftime('%m-%d %H:%M'), ab))
        print('   任务：%s' % r['title'])
        if r['last_desc']:
            print('   收尾：%s' % ' '.join(r['last_desc'].split())[:40])


def cmd_tail(args):
    group, sd, p = match_sid(args.sid, args.cwd)
    ev = load_events(p)
    print('== %s  (组 %s, 共 %d 条) 最近 %d 条 ==' % (sd, group, len(ev), args.n))
    for e in ev[-args.n:]:
        ts = fmt_time(e.get('time', 0)) if e.get('time') else ''
        print('[%s] #%s %s' % (ts, e.get('seq', '?'), brief(e)))


def discover_host_port(port_hint=None):
    """找到 DSH Host 的本机监听端口(netstat+tasklist), 可用 delivery.host_port 固定."""
    if port_hint:
        return int(port_hint)
    import subprocess
    try:
        ns = subprocess.run(['netstat', '-ano', '-p', 'tcp'],
                            capture_output=True, text=True, timeout=10).stdout
        tl = subprocess.run(['tasklist', '/fo', 'csv', '/nh'],
                            capture_output=True, text=True, timeout=10).stdout
        pids = {}
        for line in tl.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2:
                pids[parts[1]] = parts[0].lower()
        for line in ns.splitlines():
            ll = line.split()
            if len(ll) >= 5 and ll[3] == 'LISTENING':
                lp = ll[1]
                if 'deepseek harness' in pids.get(ll[4], '') and ':' in lp:
                    return int(lp.rsplit(':', 1)[1])
    except Exception:
        pass
    return None


def resolve_delivery(cfg):
    """归一化投递配置。渠道无关: 每个命名目标一组 {botId, targetId, format?}。

    兼容旧版平铺键 delivery_bot_id/delivery_target_id(自动合成名为 default 的目标)。
    """
    d = cfg.get('delivery') or {}
    profiles = dict(d.get('targets') or {})
    default = d.get('default')
    if not profiles:
        bot, tgt = cfg.get('delivery_bot_id'), cfg.get('delivery_target_id')
        if bot and tgt:
            profiles = {'default': {'botId': bot, 'targetId': tgt}}
            default = 'default'
    if not default and profiles:
        default = sorted(profiles.keys())[0]
    return {
        'profiles': profiles,
        'default': default,
        'max_chars': int(d.get('max_chars') or 1800),
        'host_port': d.get('host_port'),
        'format': d.get('format') or 'plain',
    }


def _bridge_info(port):
    """读取宿主桥的投递能力信息; 路由不存在(旧版宿主半)返回 None。"""
    import urllib.request
    try:
        with urllib.request.urlopen(
                'http://127.0.0.1:%d/session-monitor/delivery' % port, timeout=10) as r:
            return json.loads(r.read().decode('utf-8', 'replace'))
    except Exception:
        return None


def _bridge_send(port, bot_id, target_id, text, fmt):
    """经宿主桥(ctx.dshIm.send)投递一条, 返回 (ok, 详情)。"""
    import urllib.request
    payload = json.dumps({'botId': bot_id, 'targetId': target_id, 'text': text,
                          'format': fmt or 'plain'}).encode('utf-8')
    req = urllib.request.Request(
        'http://127.0.0.1:%d/session-monitor/deliver' % port, data=payload,
        headers={'Content-Type': 'application/json; charset=utf-8'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode('utf-8', 'replace')
            ok = r.status == 200 and '"sent":true' in body.replace(' ', '')
            return ok, 'HTTP %s %s' % (r.status, body)
    except Exception as e:
        code = getattr(e, 'code', None)
        detail = ''
        if code is not None:
            try:
                detail = e.read().decode('utf-8', 'replace')
            except Exception:
                pass
        return False, 'HTTP %s %s %s' % (code or '-', e, detail)


def deliver(text, cfg, fmt=None, to=None):
    """把消息主动投递到一个或多个 IM 目标(微信/QQ/飞书等, 渠道无关)。

    目标配置统一由 dsh-im 管理(设置 → IM机器人 → 新建目标, 官方 UI 支持测试)。
    本插件优先走宿主桥自动发现已保存目标:
      dsh-im 未安装 -> 引导安装; 已装无目标 -> 引导到设置页; 正常 -> 按名路由。
    宿主桥不可用(旧版宿主半)时回退本地 delivery.targets 配置。
    """
    d = cfg.get('delivery') or {}
    maxc = int(d.get('max_chars') or 1800)
    if len(text) > maxc:
        text = text[:maxc] + '…(已截断)'
    port = discover_host_port(d.get('host_port'))
    if port:
        info = _bridge_info(port)
        if isinstance(info, dict) and info.get('available'):
            targets = info.get('targets') or []
            if not targets:
                return False, ['dsh-im 尚未配置任何投递目标: 请到 DSH 设置 → IM机器人 → '
                               '对应机器人齿轮 → 新建目标(测试并保存)后重试']
            wants = list(to) if to else None
            if not wants:
                if len(targets) == 1:
                    sel = targets
                else:
                    return False, ['共有 %d 个投递目标, 请用 --to 指定: %s' % (
                        len(targets), ', '.join('%s(%s)' % (
                            t.get('targetId'), t.get('name') or t.get('channel') or '?')
                            for t in targets))]
            else:
                sel, missing = [], []
                for w in wants:
                    hits = [t for t in targets
                            if w == t.get('targetId') or w == (t.get('name') or '')]
                    if hits:
                        sel.extend(hits)
                    else:
                        missing.append(w)
                if missing:
                    return False, ['未知目标 %s; 可用: %s' % (
                        ','.join(missing),
                        ', '.join(str(t.get('targetId')) for t in targets))]
            results, ok_all = [], True
            for t in sel:
                ok, detail = _bridge_send(port, t.get('botId'), t.get('targetId'),
                                          text, fmt or t.get('format'))
                results.append('%s: %s' % (t.get('targetId'), detail))
                if not ok:
                    ok_all = False
            return ok_all, results
    # 回退: 本地命名目标(宿主桥不可用时的兼容路径, 直接打 dsh-im HTTP 投递端点)
    spec = resolve_delivery(cfg)
    names = list(to) if to else ([spec['default']] if spec['default'] else [])
    if not names:
        return False, ['未配置任何投递目标: 在 DSH 设置 → IM机器人 里配置(推荐), '
                       '或在 ~/.dsh/dsh-session-monitor.json 的 delivery.targets 里添加']
    results, ok_all = [], True
    for name in names:
        prof = spec['profiles'].get(name)
        if not prof or not prof.get('botId') or not prof.get('targetId'):
            results.append('%s: 未知或不完整目标(已配置: %s)' % (
                name, ', '.join(sorted(spec['profiles'])) or '无'))
            ok_all = False
            continue
        if not port:
            results.append('%s: 未找到 DSH Host 端口(可配置 delivery.host_port)' % name)
            ok_all = False
            continue
        import urllib.request
        payload = json.dumps({
            'botId': prof['botId'], 'targetId': prof['targetId'], 'text': text,
            'format': fmt or prof.get('format') or spec['format'],
        }).encode('utf-8')
        req = urllib.request.Request(
            'http://127.0.0.1:%d/api/dsh-im/delivery/messages' % port,
            data=payload, headers={'Content-Type': 'application/json; charset=utf-8'})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode('utf-8', 'replace')
                results.append('%s: HTTP %s %s' % (name, resp.status, body))
                if resp.status != 200:
                    ok_all = False
        except Exception as e:
            code = getattr(e, 'code', None)
            detail = ''
            if code is not None:
                try:
                    detail = e.read().decode('utf-8', 'replace')
                except Exception:
                    pass
            results.append('%s: HTTP %s %s %s' % (name, code or '-', e, detail))
            ok_all = False
    return ok_all, results


def cmd_notify(args):
    """经 dsh-im 主动投递发送一条消息, 按命名目标路由(微信/QQ/飞书等)。"""
    cfg = load_config()
    to = list(args.to or [])
    if args.bot and args.target:
        # 临时目标: 与命名目标并存, 便于一次性投递
        spec = {'default': '__adhoc',
                'profiles': {'__adhoc': {'botId': args.bot, 'targetId': args.target,
                                         'format': args.format}},
                'max_chars': 1800, 'host_port': None, 'format': 'plain'}
        names = to or ['__adhoc']
        ok_all, lines = True, []
        text = args.text
        if len(text) > spec['max_chars']:
            text = text[:spec['max_chars']] + '…(已截断)'
        port = discover_host_port()
        for name in names:
            prof = spec['profiles'].get(name)
            if not prof or not port:
                ok_all = False
                lines.append('%s: 无法投递(参数不完整或未找到 Host 端口)' % name)
                continue
            import urllib.request
            payload = json.dumps({'botId': prof['botId'], 'targetId': prof['targetId'],
                                  'text': text, 'format': args.format or 'plain'}).encode('utf-8')
            req = urllib.request.Request(
                'http://127.0.0.1:%d/api/dsh-im/delivery/messages' % port,
                data=payload, headers={'Content-Type': 'application/json; charset=utf-8'})
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    lines.append('%s: HTTP %s %s' % (name, resp.status,
                                                     resp.read().decode('utf-8', 'replace')))
            except Exception as e:
                ok_all = False
                lines.append('%s: %s' % (name, e))
        print(('已投递: ' if ok_all else '投递失败(部分): ') + '; '.join(lines))
        if not ok_all:
            sys.exit(1)
        return
    ok, results = deliver(args.text, cfg, args.format, to or None)
    print(('已投递: ' if ok else '投递失败(部分): ') + '; '.join(results))
    if not ok:
        sys.exit(1)


def cmd_wait(args):
    """阻塞等待目标会话出现新的轮次结束, 打印期间产生的 AI 文本回复。

    增量实现: 初次全量加载后用 SessionTail 只解压新增字节,
    高频轮询不再重复解压整个文件。
    """
    group, sd, p = match_sid(args.sid)
    cfg = load_config()
    poll = int(args.poll) if args.poll else int(cfg['poll_interval_sec'])
    tail = SessionTail(p)
    base_seq = tail.max_seq
    print('== 等待 %s 的新回复 (最多 %s 秒, 基线 seq=%s, 每 %s 秒增量轮询) ==' % (
        short_id(sd), args.timeout, base_seq, poll))
    deadline = time.time() + args.timeout
    last_beat = time.time()
    while True:
        time.sleep(max(1, poll))
        new = tail.poll()
        ends = [e for e in new if e.get('type') == 'turn/end' and e.get('seq', 0) > base_seq]
        if not ends:
            # 兜底: 轮次结束事件可能在上次全量与本次增量边界之外
            ends = [e for e in tail.events
                    if e.get('type') == 'turn/end' and e.get('seq', 0) > base_seq]
        if ends:
            end = ends[0]
            end_seq = end.get('seq', 0)
            texts = []
            for e in tail.events:
                if base_seq < e.get('seq', 0) <= end_seq and e.get('type') == 'assistant/message':
                    d = e.get('data', {}) or {}
                    txt = content_text((d.get('message') or {}).get('content'))
                    if txt and not txt.startswith('[调用工具'):
                        texts.append(txt)
            turn_no = (end.get('data') or {}).get('turn')
            reason = ((end.get('data') or {}).get('reason') or {}).get('kind') or ''
            if args.json:
                print(json.dumps({'session': sd, 'turn': turn_no, 'end_reason': reason,
                                  'messages': texts}, ensure_ascii=False, indent=2))
            else:
                print('== 新回复已到达 (turn %s%s) ==' % (
                    turn_no, ', 被中止' if reason == 'aborted' else ''))
                for t in texts:
                    print(t)
                    print('---')
                if not texts:
                    print('（该轮没有文本回复）')
            if args.notify:
                head = '【任务完成】%s turn %s' % (short_id(sd), turn_no)
                body = '\n---\n'.join(texts) or '（该轮没有文本回复）'
                ok, results = deliver(head + '\n' + body, cfg,
                                      to=list(args.to or []) or None)
                print(('已主动投递到 IM: ' if ok else '主动投递失败(部分): ')
                      + '; '.join(results))
            return
        if time.time() >= deadline:
            print('超时: %s 秒内该会话没有新的轮次结束' % args.timeout)
            sys.exit(1)
        if time.time() - last_beat >= 60:
            print('[%s] 仍在等待…' % datetime.datetime.now().strftime('%H:%M:%S'))
            last_beat = time.time()


def cmd_dump(args):
    group, sd, p = match_sid(args.sid, args.cwd)
    ev = load_events(p)
    lines = ['# 会话 %s 导出' % sd, '']
    for e in ev:
        t = e.get('type')
        d = e.get('data', {}) or {}
        ts = fmt_time(e.get('time', 0)) if e.get('time') else ''
        if t == 'user/message':
            lines += ['## 用户 (%s)' % ts, '', content_text(d.get('content')), '']
        elif t == 'assistant/message':
            txt = content_text((d.get('message') or {}).get('content'))
            if txt:
                lines += ['## 助手 (%s)' % ts, '', txt, '']
        elif t == 'tool/call':
            lines += ['> 工具 %s %s' % (d.get('name'), str(d.get('arguments'))[:200]), '']
    md = '\n'.join(lines)
    out = args.out or ('session-%s.md' % sd[:16])
    with open(out, 'w', encoding='utf-8') as f:
        f.write(md)
    print('已导出 %d 条消息到 %s (%d 字符)' % (len(ev), os.path.abspath(out), len(md)))


def _plugin_version():
    """读包根 package.json 的版本号(单一来源), 失败返回占位。"""
    try:
        pkg = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'package.json')
        with open(pkg, encoding='utf-8') as f:
            return json.load(f).get('version') or '(未知版本)'
    except Exception:
        return '(未知版本)'


def _guide_full():
    ver = _plugin_version()
    return """【dsh-session-monitor 使用指南】v%s

一、这是什么
实时监视本机所有 DeepSeek Harness (DSH) 会话的只读工具：谁在跑、跑什么、
进展如何；配合 dsh-im 插件还能把结果推送到微信/QQ/飞书等 IM。
全部操作只读，不会修改或干扰任何会话。

二、指令一览（python scripts/monitor.py <指令>；help <指令> 看单指令详情）
  status   全部会话状态总览（RUNNING/STALLED/IDLE/ABORTED）
  board    固定格式任务看板：▶ 活跃中 / ⏸ 疑似中断 / ✔ 已完成TopN
  tail     某会话最近 N 条事件（tail <短ID> -n 20）
  wait     阻塞等待某会话新回复（wait <短ID> --timeout 600）
  notify   经 IM 主动推送消息（notify --text "..." --to 目标）
  dump     导出某会话完整对话为 Markdown（dump <短ID> -o 文件.md）
  help     本指南；help <指令名> 查看该指令的用法与示例

三、两个技能（AI 助手自动调用，无需手敲命令）
  dsh-session-monitor  问「其他会话在干什么/进度如何」时自动使用
  dsh-session-relay    说「去XX会话发句话/问一下并带回回复」时使用

四、设置页
  设置 → 「DSH 会话监视器」：调整轮询间隔/判定阈值/看板条数；
  顶部「依赖插件检测」实时显示 dsh-im 状态（未安装/无目标/正常）。

五、配置优先级：命令行参数 > ~/.dsh/dsh-session-monitor.json > 默认值
  （设置页与配置文件是同一份数据；修改对之后运行的命令立即生效）

六、常见问法 → 对应指令
  「现在在跑什么任务」        → board
  「XX任务进度怎么样」        → tail <短ID>
  「等XX做完把结果发我」      → wait <短ID> --notify
  「把这条消息推到飞书」      → notify --text "..." --to feishu
  「导出XX会话完整对话」      → dump <短ID> -o 导出.md
  「这插件怎么用/有什么功能」  → help（本指南）

七、依赖
  核心功能仅需 Python3 + zstandard；IM 推送需另装 dsh-im 插件（可选），
  缺失时相关命令会给出安装/配置引导，其余功能不受影响。""" % ver


HELP_TOPICS = {
    'status': """status — 全部会话状态总览（只读）
用法: python monitor.py status [--cwd D:\\路径] [--json]
说明: 列出本机所有 DSH 会话的运行状态（RUNNING/STALLED/IDLE/ABORTED）、
      轮次/步骤、工作区与最新动作；--cwd 只看某个工作区。
示例: python monitor.py status --cwd D:\\LQ\\v2""",
    'board': """board — 固定格式任务看板（只读, IM 查询首选）
用法: python monitor.py board [--top N] [--max-running N] [--cwd 路径]
                              [--exclude 短ID] [--json]
说明: 三段式看板：▶ 活跃中（最多 N 条）/ ⏸ 疑似中断 / ✔ 已完成 TopN，
      均按更新时间由新到旧；输出格式固定，可直接原样转发给用户。
示例: python monitor.py board --top 10
      python monitor.py board --exclude 0a29d310""",
    'tail': """tail — 查看某会话最近事件（只读）
用法: python monitor.py tail <会话ID前缀> [-n 条数] [--cwd 路径]
说明: 打印该会话最近 N 条事件（用户消息/AI消息/工具调用等），适合深入
      某个任务看当前进展。短ID 只需前 8 位左右。
示例: python monitor.py tail 0a29d310 -n 20""",
    'wait': """wait — 阻塞等待某会话的新回复（信使核心, 只读）
用法: python monitor.py wait <会话ID前缀> [--timeout 秒] [--poll 秒]
                            [--notify] [--to 目标] [--json]
说明: 阻塞直到该会话当前轮次结束并打印 AI 回复文本；--notify 时把回复
      经 dsh-im 自动投递到 IM（--to 指定目标，缺省用配置默认）。
示例: python monitor.py wait 0a29d310 --timeout 600 --notify""",
    'notify': """notify — 经 IM 主动推送一条消息（需要 dsh-im）
用法: python monitor.py notify --text "消息" [--to 目标 ...]
                              [--bot ID --target ID] [--format plain|markdown]
说明: 把文本推送到 IM（微信/QQ/飞书等，渠道无关）；目标由 dsh-im 统一
      管理（设置 → IM机器人），--bot/--target 可免配置一次性投递。
示例: python monitor.py notify --text "构建完成" --to feishu""",
    'dump': """dump — 导出某会话完整对话为 Markdown（只读）
用法: python monitor.py dump <会话ID前缀> [-o 输出.md] [--cwd 路径]
说明: 把该会话从头到尾的用户/AI 消息导出为 Markdown 文件，便于存档、
      分享或离线阅读；缺省输出到当前目录 session-<短ID>.md。
示例: python monitor.py dump 0a29d310 -o 会话导出.md""",
    'help': """help — 固定格式使用指南
用法: python monitor.py help [指令名]
说明: 不带参数输出完整使用指南（功能清单/技能/设置页/配置/常见问法）；
      带指令名输出该指令的用法、说明与示例。输出格式完全固定——
      用户问「这插件怎么用/有什么功能」时，把 stdout 原样发送即可。
示例: python monitor.py help board""",
    'config': """config — 配置的三个入口（优先级: 命令行参数 > 配置文件 > 默认值）
  1) 设置页：设置 → 「DSH 会话监视器」（图形界面，含依赖插件检测）
  2) 配置文件：~/.dsh/dsh-session-monitor.json（设置页与它是同一份数据，
     手改后对之后运行的命令立即生效）
  3) 命令行参数：如 board --top 10、wait --poll 5（只对当次命令生效）
可调项: poll_interval_sec / running_threshold_sec / zombie_hours /
     board_top / board_max_running / delivery（IM 投递回退配置）""",
    'install': """install — 安装形态（本机已完成安装）
  · 插件包（当前启用）: 经 DSH「插件管理」以本地路径 D:\\dsh-session-moniter
    安装，pnpm link 指向开发目录，改代码后重启 DSH 生效
  · 技能目录（形态A）: C:\\Users\\admin\\.agents\\skills\\dsh-session-monitor
    （junction 指向开发目录；两种形态同时启用会重复出现技能）
  · 依赖: Python3 + zstandard（核心功能）；dsh-im（可选，仅 IM 推送需要）""",
}


def cmd_help(args):
    topic = (args.topic or '').strip().lower()
    if not topic:
        print(_guide_full())
        return
    block = HELP_TOPICS.get(topic)
    if block is None:
        print('未知主题: %s' % topic)
        print('可用主题: %s' % ', '.join(sorted(HELP_TOPICS)))
        return
    print(block)


def main():
    ap = argparse.ArgumentParser(description='DSH 会话监视器(只读)')
    sub = ap.add_subparsers(dest='cmd')
    ps = sub.add_parser('status', help='所有会话状态总览')
    ps.add_argument('--cwd', help='按工作区路径过滤')
    ps.add_argument('--json', action='store_true')
    pb = sub.add_parser('board', help='固定格式任务看板: 进行中 + 已完成TopN')
    pb.add_argument('--top', type=int, default=None,
                    help='已完成榜单条数(默认读配置文件)')
    pb.add_argument('--max-running', type=int, default=None,
                    help='进行中最多显示条数(默认读配置文件)')
    pb.add_argument('--cwd', help='按工作区路径过滤')
    pb.add_argument('--exclude', action='append', help='排除会话ID前缀(可多次)')
    pb.add_argument('--json', action='store_true')
    pt = sub.add_parser('tail', help='查看某会话最近事件')
    pt.add_argument('sid', help='会话 ID 前缀')
    pt.add_argument('-n', type=int, default=15)
    pt.add_argument('--cwd')
    pw = sub.add_parser('wait', help='阻塞等待某会话产生新回复')
    pw.add_argument('sid', help='会话 ID 前缀')
    pw.add_argument('--timeout', type=int, default=300)
    pw.add_argument('--poll', type=float, default=None,
                    help='轮询间隔秒数(默认读配置文件 poll_interval_sec)')
    pw.add_argument('--notify', action='store_true',
                    help='捕获回复后经 dsh-im 主动投递发送到 IM')
    pw.add_argument('--to', action='append',
                    help='投递目标名(可多次, 缺省用配置默认目标; 渠道无关)')
    pw.add_argument('--json', action='store_true')
    pn = sub.add_parser('notify', help='经 dsh-im 主动投递发送一条消息')
    pn.add_argument('--text', required=True, help='消息文本')
    pn.add_argument('--to', action='append',
                    help='命名投递目标(可多次, 如 feishu/wechat; 缺省用配置默认)')
    pn.add_argument('--bot', help='临时 botId(与 --target 搭配, 免配置一次性投递)')
    pn.add_argument('--target', help='临时 targetId(与 --bot 搭配)')
    pn.add_argument('--format', choices=['plain', 'markdown'],
                    help='文本格式(默认读目标/全局配置)')
    pd = sub.add_parser('dump', help='导出完整对话为 Markdown')
    pd.add_argument('sid', help='会话 ID 前缀')
    pd.add_argument('-o', '--out')
    pd.add_argument('--cwd')
    ph = sub.add_parser('help', help='固定格式使用指南(help [指令名] 查看详情)')
    ph.add_argument('topic', nargs='?', default=None,
                    help='指令名或主题(status/board/tail/wait/notify/dump/help/config/install)')
    args = ap.parse_args()
    if not args.cmd:
        args = ap.parse_args(['status'])
    {'status': cmd_status, 'board': cmd_board, 'tail': cmd_tail,
     'wait': cmd_wait, 'notify': cmd_notify, 'dump': cmd_dump,
     'help': cmd_help}[args.cmd](args)


if __name__ == '__main__':
    main()
