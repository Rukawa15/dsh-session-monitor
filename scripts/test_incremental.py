# -*- coding: utf-8 -*-
"""monitor.py 增量读取与配置系统的正确性验证(只读)."""
import sys, os, time, io
sys.path.insert(0, r'D:\dsh-session-moniter\scripts')
import zstandard
from monitor import load_events, SessionTail, find_sessions, load_config, CONFIG_DEFAULTS

# 1) 逐帧 load_events 与流式解压一致性(用旧方法做对照)
def load_events_stream(path):
    raw = open(path, 'rb').read()
    dctx = zstandard.ZstdDecompressor()
    reader = dctx.stream_reader(io.BytesIO(raw), read_across_frames=True)
    events = []
    for line in reader.read().decode('utf-8', 'replace').splitlines():
        line = line.strip()
        if line:
            try:
                events.append(__import__('json').loads(line))
            except Exception:
                pass
    return events

checked = 0
for group, sd, p in find_sessions():
    a, b = load_events(p), load_events_stream(p)
    sa = [e.get('seq') for e in a]
    sb = [e.get('seq') for e in b]
    assert sa == sb, '%s: seq 不一致 %d vs %d' % (sd, len(sa), len(sb))
    checked += 1
print('1) 逐帧 vs 流式 事件序列一致: %d 个会话全部通过' % checked)

# 2) SessionTail 增量: 初始事件 == 全量; 模拟追加后 poll 捕获新事件
group, sd, p = next(find_sessions())
tail = SessionTail(p)
full = load_events(p)
assert [e.get('seq') for e in tail.events] == [e.get('seq') for e in full], 'SessionTail 初始与全量不一致'
print('2) SessionTail 初始加载 == 全量 (%d 事件) 通过' % len(full))

# 3) poll 空转: 无新增时返回空列表
assert tail.poll() == []
print('3) SessionTail.poll() 空转返回空列表 通过')

# 4) 增量捕获真实新增(拿当前正在活跃的本会话文件, 循环几次直到它有新写入或超时)
me = os.path.expanduser(r'~\.dsh\sessions\--D-LQ-v2--\session-db460253-16be-44d2-983e-86cacf25a8bc\session.v4.jsonl.zstd')
t2 = SessionTail(me)
deadline = time.time() + 45
got = None
while time.time() < deadline:
    new = t2.poll()
    if new:
        got = new
        break
    time.sleep(2)
if got:
    seqs = [e.get('seq') for e in got]
    allseq = [e.get('seq') for e in t2.events]
    assert allseq == sorted(allseq, key=lambda x: x or 0), '事件 seq 非递增'
    assert len(t2.events) == len(set(allseq)), '事件出现重复'
    print('4) 实时增量捕获通过: 新增 %d 个事件, 首个 seq=%s, 无重复' % (len(got), seqs[0]))
else:
    print('4) 45 秒内本会话无新写入(跳过实时验证, 其余断言已通过)')

# 5) 配置系统
cfg = load_config()
assert cfg == dict(CONFIG_DEFAULTS), '无配置文件时应返回默认值: %r' % cfg
print('5) 配置默认值通过: %r' % cfg)

# 6) 合成文件: 增量追加 / 半帧截断 / 半帧补全 (模拟 DSH 写入中途被轮询)
import json as _json
import tempfile
cctx = zstandard.ZstdCompressor()
tmp = os.path.join(tempfile.gettempdir(), 'dsm_test.jsonl.zstd')
with open(tmp, 'wb') as f:
    f.write(cctx.compress(b'{"type":"a","seq":1}\n'))
    f.write(cctx.compress(b'{"type":"b","seq":2}\n{"type":"c","seq":3}\n'))
t = SessionTail(tmp)
assert [e['seq'] for e in t.events] == [1, 2, 3], t.events
with open(tmp, 'ab') as f:
    f.write(cctx.compress(b'{"type":"d","seq":4}\n'))
new = t.poll()
assert [e['seq'] for e in new] == [4], new
frame = cctx.compress(b'{"type":"e","seq":5}\n')
with open(tmp, 'ab') as f:                      # 只写半帧(模拟写到一半)
    f.write(frame[:len(frame) // 2])
assert t.poll() == [], '半帧不应产生事件'
with open(tmp, 'ab') as f:                      # 补全另一半
    f.write(frame[len(frame) // 2:])
new = t.poll()
assert [e['seq'] for e in new] == [5], new
assert len(t.events) == 5 and not t.poll()
os.remove(tmp)
print('6) 合成增量/半帧截断/半帧补全 全部通过')
