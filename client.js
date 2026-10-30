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

    function fetchStatus() {
      return fetch('/session-monitor/status').then((r) => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      });
    }

    // 依赖插件检测卡: 三态引导(未安装 / 已连接无目标 / 正常), 另有路由缺席的降级态
    function DependencyCard({ status, loading, onRefresh }) {
      const boxStyle = {
        marginBottom: 18, padding: '10px 14px', borderRadius: 8,
        border: '1px solid rgba(128,128,128,0.35)', maxWidth: 560,
      };
      const hintStyle = { fontSize: 12, opacity: 0.65, marginTop: 6, lineHeight: 1.6 };
      const titleStyle = { fontWeight: 600 };
      const refreshStyle = { marginLeft: 10, fontSize: 12, padding: '2px 10px', cursor: 'pointer' };

      let title, hint, color;
      if (loading && !status) {
        title = '正在检测依赖插件…';
        hint = null;
        color = 'rgba(128,128,128,0.7)';
      } else if (!status) {
        title = '⚠ 依赖检测不可用';
        hint = '宿主半为 0.5.0 之前的版本或尚未随 DSH 重启加载。重启 DSH 后即可在此看到 dsh-im 的检测状态。';
        color = '#b8860b';
      } else if (!status.dshIm || !status.dshIm.available) {
        title = '⚠ 未检测到 dsh-im 服务';
        hint = 'IM 主动投递（notify / wait --notify）需要 dsh-im 插件；会话监视、看板与信使功能不受影响。' +
               '可在「设置 → 插件市场」搜索 dsh-im（@xmanrui/dsh-im）安装后重启 DSH。';
        color = '#b8860b';
      } else if (!status.dshIm.targets) {
        title = '⚠ dsh-im 已连接，但尚未配置投递目标';
        hint = '到「设置 → IM机器人」对应机器人的齿轮里新建目标（可先测试再保存），之后 notify / wait --notify 即可按目标投递。';
        color = '#b8860b';
      } else {
        title = '✓ dsh-im 已连接 · ' + status.dshIm.bots + ' 个机器人 / ' + status.dshIm.targets + ' 个投递目标';
        hint = status.dshIm.error ? ('部分目标列举失败: ' + status.dshIm.error) : 'IM 主动投递链路可用。';
        color = '#2e7d32';
      }

      return h('div', { style: Object.assign({}, boxStyle, { borderColor: color }) },
        h('div', { style: Object.assign({}, titleStyle, { color }) },
          '依赖插件检测',
          h('button', { style: refreshStyle, onClick: onRefresh }, '重新检测')),
        h('div', { style: { marginTop: 4 } }, title),
        hint && h('div', { style: hintStyle }, hint));
    }

    function Section() {
      const [cfg, setCfg] = React.useState(null);
      const [error, setError] = React.useState('');
      const [status, setStatus] = React.useState('');
      const [dep, setDep] = React.useState(null);
      const [depLoading, setDepLoading] = React.useState(true);

      React.useEffect(() => {
        fetchConfig().then(setCfg).catch(() => {
          setCfg(null);
          setError('宿主配置服务未连接');
        });
        refreshDeps();
      }, []);

      const refreshDeps = () => {
        setDepLoading(true);
        fetchStatus().then((data) => {
          setDep(data);
          setDepLoading(false);
        }).catch(() => {
          setDep(null);
          setDepLoading(false);
        });
      };

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
        h('h2', { style: { marginTop: 0 } }, 'DSH 会话监视器',
          dep && dep.version && h('span', { style: { fontSize: 12, opacity: 0.5, marginLeft: 8, fontWeight: 400 } },
            'v' + dep.version)),
        h(DependencyCard, { status: dep, loading: depLoading, onRefresh: refreshDeps }),
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
