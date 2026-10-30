/**
 * Host half of the dsh-session-monitor bundle.
 *
 * Routes (registered synchronously; the injected services are guaranteed
 * present when apply() runs, so no deferred registration is needed):
 *   GET  /session-monitor/config    - shared config file for the Settings UI
 *   GET  /session-monitor/delivery  - dsh-im proactive-delivery capability
 *   POST /session-monitor/deliver   - send via ctx.dshIm.send (shared core)
 *
 * Service access in this Cordis requires declarative `inject`: a plain
 * property read returns nothing (0.4.0/0.4.1 root cause), and deferring
 * effect registration to a timer crashed the host with INACTIVE_EFFECT
 * during plugin reload (0.4.1 regression, fixed in 0.4.2).
 *
 * Note: this half stays inactive while dsh-im is absent; skills and scripts
 * keep working regardless, and notify falls back to dsh-im's HTTP endpoint.
 */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { homedir } from 'node:os';

export const inject = ['connection', 'dshIm'];

const CONFIG_PATH = join(homedir(), '.dsh', 'dsh-session-monitor.json');

const DEFAULTS = {
  poll_interval_sec: 10,
  running_threshold_sec: 900,
  zombie_hours: 24,
  board_top: 5,
  board_max_running: 10,
};

const CLAMPS = {
  poll_interval_sec: [1, 3600],
  running_threshold_sec: [60, 86400],
  zombie_hours: [1, 720],
  board_top: [1, 50],
  board_max_running: [1, 100],
};

function readConfig() {
  try {
    const parsed = JSON.parse(readFileSync(CONFIG_PATH, 'utf8'));
    return { ...DEFAULTS, ...parsed };
  } catch {
    return { ...DEFAULTS };
  }
}

function sanitize(input) {
  const out = readConfig();
  for (const key of Object.keys(CLAMPS)) {
    if (input && input[key] !== undefined) {
      const n = Number(input[key]);
      if (Number.isFinite(n)) {
        const [min, max] = CLAMPS[key];
        out[key] = Math.min(max, Math.max(min, Math.round(n)));
      }
    }
  }
  return out;
}

function writeConfig(cfg) {
  mkdirSync(dirname(CONFIG_PATH), { recursive: true });
  writeFileSync(CONFIG_PATH, JSON.stringify(cfg, null, 2), 'utf8');
  return cfg;
}

async function readRequestBody(request) {
  const body = request && request.body;
  if (body == null) return {};
  if (typeof body === 'string') return JSON.parse(body || '{}');
  if (body instanceof ArrayBuffer) return JSON.parse(new TextDecoder().decode(body) || '{}');
  if (ArrayBuffer.isView(body)) return JSON.parse(new TextDecoder().decode(body) || '{}');
  if (typeof body.pipe === 'function' || typeof body.getReader === 'function') {
    return JSON.parse((await new Response(body).text()) || '{}');
  }
  return {};
}

function jsonReply(payload, status) {
  return new Response(JSON.stringify(payload), {
    status: status || 200,
    headers: { 'content-type': 'application/json' },
  });
}

export function apply(ctx) {
  const disposers = [];

  const keep = (fn) => {
    try {
      const dispose = fn();
      if (typeof dispose === 'function') disposers.push(dispose);
    } catch {
      // 单条路由注册失败不影响其余
    }
  };

  keep(() => ctx.connection.fetch.register({
    path: '/session-monitor/config',
    methods: ['GET', 'PUT'],
    requestBody: 'streaming',
    fetch: async (request) => {
      try {
        if (request.method === 'PUT') {
          const input = await readRequestBody(request);
          return jsonReply(writeConfig(sanitize(input)));
        }
        return jsonReply(readConfig());
      } catch (error) {
        return jsonReply({ error: String(error) }, 500);
      }
    },
  }));

  keep(() => ctx.connection.fetch.register({
    path: '/session-monitor/delivery',
    methods: ['GET'],
    requestBody: 'streaming',
    fetch: async () => {
      try {
        if (!ctx.dshIm || typeof ctx.dshIm.listBots !== 'function') {
          return jsonReply({ available: false, reason: 'dshIm 服务不可用' });
        }
        const bots = await ctx.dshIm.listBots();
        const targets = [];
        for (const bot of bots || []) {
          try {
            const list = await ctx.dshIm.listTargets(bot.botId);
            for (const t of list || []) {
              targets.push({
                botId: bot.botId,
                channel: bot.channel,
                targetId: t.targetId,
                name: t.name || null,
                kind: t.kind || null,
              });
            }
          } catch {
            // 单个机器人的目标列举失败不影响整体
          }
        }
        return jsonReply({ available: true, bots: bots || [], targets });
      } catch (error) {
        return jsonReply({ available: false, error: String(error) });
      }
    },
  }));

  keep(() => ctx.connection.fetch.register({
    path: '/session-monitor/deliver',
    methods: ['POST'],
    requestBody: 'streaming',
    fetch: async (request) => {
      try {
        if (!ctx.dshIm || typeof ctx.dshIm.send !== 'function') {
          return jsonReply({ sent: false, error: 'dshIm 服务不可用' }, 503);
        }
        const input = await readRequestBody(request);
        if (!input || !input.botId || !input.targetId || !input.text) {
          return jsonReply({ sent: false, error: 'botId/targetId/text required' }, 400);
        }
        const opts = input.format ? { format: input.format } : undefined;
        const result = await ctx.dshIm.send(input.botId, input.targetId, input.text, opts);
        return jsonReply({ sent: result && result.sent === true, result });
      } catch (error) {
        return jsonReply({ sent: false, error: String(error) }, 500);
      }
    },
  }));

  // 同步注册清理: 只在 apply 执行时调用(上下文必然活跃), 绝不延迟
  if (typeof ctx.effect === 'function') {
    ctx.effect(() => {
      for (const dispose of disposers) {
        try { dispose(); } catch { /* already disposed */ }
      }
      return () => {};
    }, 'session-monitor: host routes');
  }
}
