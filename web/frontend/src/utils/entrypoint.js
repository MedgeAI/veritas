/**
 * 入口分流判断
 *
 * 根据 hostname 和 pathname 判断当前应该进入哪个入口：
 * - client: 客户服务页 (veritas.science)
 * - ops: 运营后台 (ops.veritas.science 或 /ops)
 * - verify: 公开验证 (verify.veritas.science 或 /verify)
 *
 * 优先级：hostname > pathname
 */

export function detectEntry() {
  const { hostname, pathname } = window.location;

  // hostname 优先判断
  if (hostname.startsWith('ops.')) {
    return 'ops';
  }
  if (hostname.startsWith('verify.')) {
    return 'verify';
  }

  // pathname 兜底（本地开发）
  if (pathname.startsWith('/ops')) {
    return 'ops';
  }
  if (pathname.startsWith('/verify')) {
    return 'verify';
  }

  // 默认进入客户服务页
  return 'client';
}
