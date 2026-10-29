# -*- coding: utf-8 -*-
"""排查 dsh-im 的出站推送机制: 分析机器人会话事件流, 找出'进群'的触发条件."""
import sys, os, json
from collections import Counter
sys.path.insert(0, r'D:\dsh-session-moniter\scripts')
from monitor import load_events, find_sessions

# 1) 事件类型直方图 + 与 im 相关的事件样例
targets = {
    'messi-bot': '4f46c814',
    'siu-bot': '86ed977c',
    'im-group': '80e5c535',
}
for label, prefix in targets.items():
    for group, sd, p in find_sessions():
        if sd.startswith('session-' + prefix) or sd.startswith(prefix):
            ev = load_events(p)
            types = Counter(e.get('type') for e in ev)
            print('== %s (%s) %d events ==' % (label, sd, len(ev)))
            for t, n in types.most_common(20):
                print('   %-28s %d' % (t, n))
            # 找 im 相关事件
            im_events = [e for e in ev if 'im' in str(e.get('type', '')).lower()
                         or 'im' in json.dumps(e.get('data', {}), ensure_ascii=False)[:400].lower()]
            print('   im-related:', len(im_events))
            for e in im_events[:4]:
                print('    *', e.get('type'), json.dumps(e.get('data', {}), ensure_ascii=False)[:220])
            print()
