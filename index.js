/**
 * Host half of the dsh-session-monitor bundle.
 *
 * HTTP routes are registered on the Host WebServer service — the same
 * mechanism dsh-im uses (`ctx.webServer.register({ kind, path, handler })`):
 *   GET/PUT  /session-monitor/config    - shared config file for the Settings UI
 *   GET      /session-monitor/delivery  - dsh-im proactive-delivery capability
 *   POST     /session-monitor/deliver   - send via ctx.dshIm.send (shared core)
 *
 * 0.4.3 root cause: 0.4.0-0.4.2 called a non-existent `ctx.connection.fetch
 * .register` API; the TypeError was swallowed by a per-route try/catch, so no
 * route was ever registered and the settings page always showed
 * 「宿主配置服务未连接」. `connection` is a client-side service; the Host
 * exposes plain HTTP through `webServer` with raw Node (req, res) handlers.
 *
 * Activation: the static inject names only `webServer` (present in every
 * booted profile), so the config route works even while dsh-im is absent.
 * The dshIm-dependent routes are mounted via imperative ctx.inject(['dshIm'])
 * and exist exactly while dsh-im provides the service.
 */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { homedir } from 'node:os';

export const inject = ['webServer'];

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

const MAX_BODY_BYTES = 1024 * 1024;

let PLUGIN_VERSION = null;
try {
  PLUGIN_VERSION = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')).version || null;
} catch {
  PLUGIN_VERSION = null;
}

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

function httpError(status, message) {
  const error = new Error(message);
  error.status = status;
  return error;
}

function sendJson(res, status, payload, extraHeaders) {
  if (res.destroyed || res.writableEnded) return;
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    'cache-control': 'no-store',
    'content-type': 'application/json; charset=utf-8',
    'content-length': String(Buffer.byteLength(body)),
    ...extraHeaders,
  });
  res.end(body);
}

async function readJsonBody(req) {
  const declared = Number(req.headers['content-length']);
  if (Number.isFinite(declared) && declared > MAX_BODY_BYTES) throw httpError(413, 'payload too large');
  const chunks = [];
  let total = 0;
  for await (const chunk of req) {
    const buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    total += buf.length;
    if (total > MAX_BODY_BYTES) throw httpError(413, 'payload too large');
    chunks.push(buf);
  }
  const text = Buffer.concat(chunks, total).toString('utf8').trim();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    throw httpError(400, 'invalid JSON body');
  }
}

export function apply(ctx) {
  // 依赖检测路由: 常驻(只依赖 webServer), 用 ctx.get 无侵入探测 dshIm 是否已提供。
  // ctx.get 读服务不需要 inject 声明, 服务缺席时返回 undefined, 不抛错。
  ctx.effect(() => ctx.webServer.register({
    kind: 'exact',
    path: '/session-monitor/status',
    handler: async (req, res) => {
      try {
        if (req.method !== 'GET') {
          return sendJson(res, 405, { error: 'method not allowed' }, { allow: 'GET' });
        }
        let dshIm;
        try {
          dshIm = ctx.get('dshIm');
        } catch {
          dshIm = undefined;
        }
        if (!dshIm || typeof dshIm.listBots !== 'function') {
          return sendJson(res, 200, { version: PLUGIN_VERSION, dshIm: { available: false } });
        }
        const report = { version: PLUGIN_VERSION, dshIm: { available: true, bots: 0, targets: 0 } };
        try {
          const bots = (await dshIm.listBots()) || [];
          report.dshIm.bots = bots.length;
          for (const bot of bots) {
            try {
              const list = await dshIm.listTargets(bot.botId);
              report.dshIm.targets += (list || []).length;
            } catch {
              // 单个机器人的目标列举失败不影响整体统计
            }
          }
        } catch (error) {
          report.dshIm.error = String((error && error.message) || error);
        }
        return sendJson(res, 200, report);
      } catch (error) {
        return sendJson(res, error.status || 500, { error: String((error && error.message) || error) });
      }
    },
  }), 'session-monitor: /session-monitor/status');

  // 配置路由: 只依赖 webServer, 无 dsh-im 时设置页也能读写配置
  ctx.effect(() => ctx.webServer.register({
    kind: 'exact',
    path: '/session-monitor/config',
    handler: async (req, res) => {
      try {
        if (req.method === 'PUT') {
          const input = await readJsonBody(req);
          return sendJson(res, 200, writeConfig(sanitize(input)));
        }
        if (req.method !== 'GET') {
          return sendJson(res, 405, { error: 'method not allowed' }, { allow: 'GET, PUT' });
        }
        return sendJson(res, 200, readConfig());
      } catch (error) {
        return sendJson(res, error.status || 500, { error: String(error.message || error) });
      }
    },
  }), 'session-monitor: /session-monitor/config');

  // dshIm 相关路由: dsh-im 提供服务时才挂载, 服务消失时随注入作用域一起卸载
  ctx.inject(['dshIm'], (imCtx) => {
    const webServer = ctx.webServer;
    const dshIm = imCtx.dshIm;

    imCtx.effect(() => webServer.register({
      kind: 'exact',
      path: '/session-monitor/delivery',
      handler: async (req, res) => {
        try {
          if (req.method !== 'GET') {
            return sendJson(res, 405, { error: 'method not allowed' }, { allow: 'GET' });
          }
          const bots = await dshIm.listBots();
          const targets = [];
          for (const bot of bots || []) {
            try {
              const list = await dshIm.listTargets(bot.botId);
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
          return sendJson(res, 200, { available: true, bots: bots || [], targets });
        } catch (error) {
          return sendJson(res, 200, { available: false, error: String(error) });
        }
      },
    }), 'session-monitor: /session-monitor/delivery');

    imCtx.effect(() => webServer.register({
      kind: 'exact',
      path: '/session-monitor/deliver',
      handler: async (req, res) => {
        try {
          if (req.method !== 'POST') {
            return sendJson(res, 405, { error: 'method not allowed' }, { allow: 'POST' });
          }
          const input = await readJsonBody(req);
          if (!input || !input.botId || !input.targetId || !input.text) {
            return sendJson(res, 400, { sent: false, error: 'botId/targetId/text required' });
          }
          const opts = input.format ? { format: input.format } : undefined;
          const result = await dshIm.send(input.botId, input.targetId, input.text, opts);
          return sendJson(res, 200, { sent: result && result.sent === true, result });
        } catch (error) {
          return sendJson(res, error.status || 500, { sent: false, error: String(error.message || error) });
        }
      },
    }), 'session-monitor: /session-monitor/deliver');
  });
}
