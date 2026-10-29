window.__ModuleLoader__.load({
  id: '@local/dsh-session-monitor',
  factory(require) {
    const React = require('react');
    const h = React.createElement;

    // 配置项定义: [key, 标签, 说明, 最小值]
    const FIELD_DEFS = [
      ['poll_interval_sec', '后台轮询间隔（秒）', 'wait 命令每次检查会话文件的间隔', 1],
      ['running_threshold_sec', '活跃判定阈值（秒）', '无更新超过该时长仍未结束的任务标记为「疑似中断」', 60],
      ['zombie_hours', '僵尸隐藏阈值（小时）', '无更新超过该时长且未结束的会话不再出现在看板', 1],
      ['board_top', '已完成榜单条数', '任务看板「已完成」一节显示的条数', 1],
      ['board_max_running', '进行中最多显示条数', '任务看板「活跃中/疑似中断」的条数上限', 1],
    ];
    const CONFIG_HINT = '~/.dsh/dsh-session-monitor.json';

    function fetchConfig() {
      return fetch('/session-monitor/config').then((r) => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      });
    }

    function Section() {
      const [cfg, setCfg] = React.useState(null);
      const [error, setError] = React.useState('');
      const [status, setStatus] = React.useState('');

      React.useEffect(() => {
        fetchConfig().then(setCfg).catch(() => {
          setCfg(null);
          setError('宿主配置服务未连接');
        });
      }, []);

      if (error) {
        return h('div', { style: { padding: 16, opacity: 0.8 } },
          h('div', null, 'DSH 会话监视器：', error),
          h('div', { style: { fontSize: 12, marginTop: 8 } },
            '可手动编辑配置文件：' + CONFIG_HINT),
          h('button', {
            style: { marginTop: 12 },
            onClick: () => { setError(''); setStatus(''); fetchConfig().then(setCfg).catch(() => setError('宿主配置服务未连接')); },
          }, '重试'));
      }
      if (!cfg) return h('div', { style: { padding: 16, opacity: 0.6 } }, '加载中…');

      const save = async () => {
        setStatus('保存中…');
        try {
          const body = {};
          for (const [key] of FIELD_DEFS) body[key] = Number(cfg[key]);
          const r = await fetch('/session-monitor/config', {
            method: 'PUT',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify(body),
          });
          if (!r.ok) throw new Error('HTTP ' + r.status);
          setCfg(await r.json());
          setStatus('已保存 ✓');
        } catch (e) {
          setStatus('保存失败: ' + (e && e.message ? e.message : e));
        }
      };

      const labelStyle = { display: 'block', marginBottom: 14, maxWidth: 520 };
      const inputStyle = { display: 'block', marginTop: 4, width: 180, padding: '4px 8px' };
      const hintStyle = { marginLeft: 8, opacity: 0.55, fontSize: 12 };

      return h('div', { style: { padding: 16, maxWidth: 720 } },
        h('h2', { style: { marginTop: 0 } }, 'DSH 会话监视器'),
        h('p', { style: { opacity: 0.7 } },
          '调整任务看板与后台轮询的行为参数。修改对之后运行的 monitor.py 命令生效。'),
        FIELD_DEFS.map(([key, label, hint, min]) => h('label', { key, style: labelStyle },
          h('span', null, label, h('span', { style: hintStyle }, hint)),
          h('input', {
            type: 'number', min, value: cfg[key],
            onChange: (e) => setCfg(Object.assign({}, cfg, { [key]: e.target.value })),
            style: inputStyle,
          }))),
        h('div', null,
          h('button', { onClick: save }, '保存'),
          status && h('span', { style: { marginLeft: 12 } }, status)),
        h('p', { style: { fontSize: 12, opacity: 0.55, marginTop: 20 } },
          '配置文件位置: ' + CONFIG_HINT + ' · 技能: dsh-session-monitor / dsh-session-relay'));
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        try {
          ctx.slots.inject('settings.section', () => ctx.slots.register({
            name: 'settings.section',
            id: 'dsh-session-monitor',
            order: 90,
            label: () => 'DSH 会话监视器',
          }, Section));
        } catch (error) {
          // 设置插槽不可用时保持静默: 技能与脚本功能不受影响
        }
      },
    };
  },
});
