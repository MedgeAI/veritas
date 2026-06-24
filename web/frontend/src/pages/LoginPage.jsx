import { useState } from 'react';
import { FiGrid, FiLock, FiUser } from 'react-icons/fi';
import { setAuthCredentials, getCurrentUser } from '../services/api.js';

function LoginPage({ onLogin }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError('请输入用户名和密码');
      return;
    }
    setLoading(true);
    setError('');
    try {
      setAuthCredentials(username.trim(), password);
      const user = await getCurrentUser();
      if (!user) {
        setError('认证失败，请检查用户名和密码');
        return;
      }
      onLogin(user);
    } catch (err) {
      setError(err.message || '登录失败');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-ink-50 to-ink-100 px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-ink-900 text-paper-50">
            <FiGrid className="text-2xl" aria-hidden="true" />
          </div>
          <h1 className="mt-4 font-display text-3xl font-bold tracking-tight text-ink-900">
            Veritas
          </h1>
          <p className="mt-2 text-sm text-ink-500">
            论文风控审查工作台
          </p>
        </div>

        <div className="dossier-panel rounded-2xl p-6">
          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label htmlFor="login-username" className="mb-1.5 block text-sm font-medium text-ink-700">
                用户名
              </label>
              <div className="relative">
                <FiUser className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-300" aria-hidden="true" />
                <input
                  id="login-username"
                  name="username"
                  type="text"
                  className="input-field pl-10"
                  placeholder="输入用户名…"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                  spellCheck={false}
                />
              </div>
            </div>

            <div>
              <label htmlFor="login-password" className="mb-1.5 block text-sm font-medium text-ink-700">
                密码
              </label>
              <div className="relative">
                <FiLock className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-300" aria-hidden="true" />
                <input
                  id="login-password"
                  name="password"
                  type="password"
                  className="input-field pl-10"
                  placeholder="输入密码…"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                />
              </div>
            </div>

            {error ? (
              <div className="rounded-xl border border-red-300/50 bg-red-50/70 px-4 py-3 text-sm text-red-700" role="alert" aria-live="polite">
                {error}
              </div>
            ) : null}

            <button type="submit" className="btn-primary w-full justify-center" disabled={loading}>
              {loading ? '登录中…' : '登录'}
            </button>
          </form>
        </div>

        <p className="mt-6 text-center text-xs text-ink-400">
          呈现结构化证据与待办事项，不代替学术判断。
        </p>
      </div>
    </div>
  );
}

export default LoginPage;
