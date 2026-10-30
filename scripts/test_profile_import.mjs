// 诊断: 以 desktop profile 为解析锚点, 模拟宿主 Loader 导入本插件包
// 用法: node scripts/test_profile_import.mjs
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const PROFILE_PKG = 'C:/Users/admin/.dsh/profiles/desktop/package.json';
const SPEC = '@local/dsh-session-monitor';

try {
  const require = createRequire(pathToFileURL(PROFILE_PKG));
  const resolved = require.resolve(SPEC);
  console.log('resolve OK ->', resolved);
  const mod = await import(pathToFileURL(resolved));
  console.log('import OK, exports:', Object.keys(mod).join(', '));
  console.log('inject:', JSON.stringify(mod.inject));
  console.log('apply:', typeof mod.apply, '| name:', mod.name ?? '(none)');
} catch (err) {
  console.error('FAILED:', err?.code ?? '', err?.message);
  if (err?.cause) console.error('cause:', err.cause?.message ?? err.cause);
  process.exit(1);
}
