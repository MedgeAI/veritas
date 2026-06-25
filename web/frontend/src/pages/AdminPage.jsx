import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { FaEdit, FaKey, FaPlus, FaTrash, FaUsers } from 'react-icons/fa';
import { listUsers, createUser, updateUser, deleteUser, changePassword } from '../services/api.js';

const USER_DATE_FORMATTER = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

// ---------------------------------------------------------------------------
// Focus trap hook
// ---------------------------------------------------------------------------

function useFocusTrap(dialogRef, isActive) {
  useEffect(() => {
    if (!isActive || !dialogRef.current) return;

    function getFocusable() {
      return Array.from(
        dialogRef.current.querySelectorAll(
          'input:not([disabled]), button:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
      );
    }

    function handleKeyDown(event) {
      if (event.key === 'Escape') {
        event.preventDefault();
        dialogRef.current?.dispatchEvent(new CustomEvent('modal-close'));
        return;
      }
      if (event.key !== 'Tab') return;

      const focusable = getFocusable();
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener('keydown', handleKeyDown);

    // Auto-focus first input
    const focusable = getFocusable();
    if (focusable.length > 0) focusable[0].focus();

    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [dialogRef, isActive]);
}

// ---------------------------------------------------------------------------
// Unsaved changes guard hook
// ---------------------------------------------------------------------------

function useDirtyGuard(isDirty) {
  const confirmClose = useCallback(
    (closeFn) => {
      if (isDirty && !window.confirm('有未保存的更改，确定要关闭吗？')) return;
      closeFn();
    },
    [isDirty]
  );
  return confirmClose;
}

// ---------------------------------------------------------------------------
// Modal wrapper
// ---------------------------------------------------------------------------

function Modal({ onClose, title, children }) {
  const titleId = useId();
  const dialogRef = useRef(null);
  const [triggerButton] = useState(() => document.activeElement);

  useFocusTrap(dialogRef, true);

  // Restore focus to trigger button on close
  useEffect(() => {
    return () => {
      if (triggerButton && triggerButton.focus) triggerButton.focus();
    };
  }, [triggerButton]);

  // Listen for custom modal-close event from focus trap
  useEffect(() => {
    const el = dialogRef.current;
    if (!el) return;
    function handler() {
      onClose();
    }
    el.addEventListener('modal-close', handler);
    return () => el.removeEventListener('modal-close', handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/40"
        aria-label="关闭弹窗"
        onClick={onClose}
        tabIndex={-1}
      />
      <div
        ref={dialogRef}
        className="relative w-full max-w-md rounded-2xl bg-white p-6 shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 id={titleId} className="font-display text-lg font-semibold text-ink-900">{title}</h3>
          <button type="button" className="btn-ghost !px-2 !py-1 text-sm" onClick={onClose}>
            关闭
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create user form
// ---------------------------------------------------------------------------

function CreateUserModal({ onClose, onCreated }) {
  const usernameId = useId();
  const passwordId = useId();
  const emailId = useId();
  const rolesId = useId();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [email, setEmail] = useState('');
  const [roles, setRoles] = useState('user');
  const [error, setError] = useState('');
  const [fieldError, setFieldError] = useState({ username: '', password: '' });
  const [loading, setLoading] = useState(false);
  const usernameRef = useRef(null);
  const passwordRef = useRef(null);

  const isDirty = username !== '' || password !== '' || email !== '' || roles !== 'user';
  const confirmClose = useDirtyGuard(isDirty);

  async function handleSubmit(e) {
    e.preventDefault();
    const newFieldError = { username: '', password: '' };
    let firstEmpty = null;
    if (!username.trim()) {
      newFieldError.username = '请输入用户名';
      firstEmpty = firstEmpty || 'username';
    }
    if (!password) {
      newFieldError.password = '请输入密码';
      firstEmpty = firstEmpty || 'password';
    }
    if (firstEmpty) {
      setFieldError(newFieldError);
      if (firstEmpty === 'username') usernameRef.current?.focus();
      else passwordRef.current?.focus();
      return;
    }
    setFieldError({ username: '', password: '' });
    setLoading(true);
    setError('');
    try {
      await createUser(username.trim(), password, email.trim() || undefined, roles.split(',').map((r) => r.trim()).filter(Boolean));
      onCreated();
      onClose();
    } catch (err) {
      setError(err.message || '创建失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal title="创建用户" onClose={() => confirmClose(onClose)}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor={usernameId} className="mb-1 block text-sm font-medium text-ink-700">用户名 *</label>
          <input ref={usernameRef} id={usernameId} name="username" className="input-field" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" spellCheck={false} />
          {fieldError.username && <p className="mt-1 text-xs text-red-600">{fieldError.username}</p>}
        </div>
        <div>
          <label htmlFor={passwordId} className="mb-1 block text-sm font-medium text-ink-700">密码 *</label>
          <input ref={passwordRef} id={passwordId} name="password" className="input-field" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
          {fieldError.password && <p className="mt-1 text-xs text-red-600">{fieldError.password}</p>}
        </div>
        <div>
          <label htmlFor={emailId} className="mb-1 block text-sm font-medium text-ink-700">邮箱</label>
          <input id={emailId} name="email" className="input-field" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" spellCheck={false} />
        </div>
        <div>
          <label htmlFor={rolesId} className="mb-1 block text-sm font-medium text-ink-700">角色（逗号分隔）</label>
          <input id={rolesId} name="roles" className="input-field" value={roles} onChange={(e) => setRoles(e.target.value)} autoComplete="off" spellCheck={false} placeholder="user, admin…" />
        </div>
        {error ? <div className="rounded-xl border border-red-300/50 bg-red-50/70 px-3 py-2 text-sm text-red-700" role="alert" aria-live="polite">{error}</div> : null}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={() => confirmClose(onClose)}>取消</button>
          <button type="submit" className="btn-primary" disabled={loading}>{loading ? '创建中…' : '创建'}</button>
        </div>
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Edit user form
// ---------------------------------------------------------------------------

function EditUserModal({ user, onClose, onUpdated }) {
  const emailId = useId();
  const rolesId = useId();
  const initialEmail = user.email || '';
  const initialRoles = (user.roles || []).join(', ');
  const [email, setEmail] = useState(initialEmail);
  const [roles, setRoles] = useState(initialRoles);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const isDirty = email !== initialEmail || roles !== initialRoles;
  const confirmClose = useDirtyGuard(isDirty);

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      await updateUser(user.username, email.trim() || undefined, roles.split(',').map((r) => r.trim()).filter(Boolean));
      onUpdated();
      onClose();
    } catch (err) {
      setError(err.message || '更新失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal title={`编辑用户: ${user.username}`} onClose={() => confirmClose(onClose)}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor={emailId} className="mb-1 block text-sm font-medium text-ink-700">邮箱</label>
          <input id={emailId} name="email" className="input-field" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" spellCheck={false} />
        </div>
        <div>
          <label htmlFor={rolesId} className="mb-1 block text-sm font-medium text-ink-700">角色（逗号分隔）</label>
          <input id={rolesId} name="roles" className="input-field" value={roles} onChange={(e) => setRoles(e.target.value)} autoComplete="off" spellCheck={false} />
        </div>
        {error ? <div className="rounded-xl border border-red-300/50 bg-red-50/70 px-3 py-2 text-sm text-red-700" role="alert" aria-live="polite">{error}</div> : null}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={() => confirmClose(onClose)}>取消</button>
          <button type="submit" className="btn-primary" disabled={loading}>{loading ? '保存中…' : '保存'}</button>
        </div>
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Change password form
// ---------------------------------------------------------------------------

function ChangePasswordModal({ user, onClose }) {
  const passwordId = useId();
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [fieldError, setFieldError] = useState('');
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);
  const passwordRef = useRef(null);

  const isDirty = password !== '';
  const confirmClose = useDirtyGuard(isDirty);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!password) {
      setFieldError('请输入新密码');
      passwordRef.current?.focus();
      return;
    }
    setFieldError('');
    setLoading(true);
    setError('');
    try {
      await changePassword(user.username, password);
      setSuccess(true);
      setPassword('');
    } catch (err) {
      setError(err.message || '修改失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal title={`修改密码: ${user.username}`} onClose={() => confirmClose(onClose)}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor={passwordId} className="mb-1 block text-sm font-medium text-ink-700">新密码</label>
          <input ref={passwordRef} id={passwordId} name="new_password" className="input-field" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
          {fieldError && <p className="mt-1 text-xs text-red-600">{fieldError}</p>}
        </div>
        {error ? <div className="rounded-xl border border-red-300/50 bg-red-50/70 px-3 py-2 text-sm text-red-700" role="alert" aria-live="polite">{error}</div> : null}
        {success ? <div className="rounded-xl border border-green-300/50 bg-green-50/70 px-3 py-2 text-sm text-green-700" role="status" aria-live="polite">密码已修改</div> : null}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={() => confirmClose(onClose)}>关闭</button>
          <button type="submit" className="btn-primary" disabled={loading}>{loading ? '修改中…' : '修改密码'}</button>
        </div>
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Delete confirmation
// ---------------------------------------------------------------------------

function DeleteConfirmModal({ user, onClose, onDeleted }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function handleDelete() {
    setLoading(true);
    setError('');
    try {
      await deleteUser(user.username);
      onDeleted();
      onClose();
    } catch (err) {
      setError(err.message || '删除失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal title="确认删除" onClose={onClose}>
      <p className="mb-4 text-sm text-ink-500">
        确定要删除用户 <strong className="text-ink-900">{user.username}</strong> 吗？此操作不可撤销。
      </p>
      {error ? <div className="mb-4 rounded-xl border border-red-300/50 bg-red-50/70 px-3 py-2 text-sm text-red-700" role="alert" aria-live="polite">{error}</div> : null}
      <div className="flex justify-end gap-2">
        <button type="button" className="btn-ghost" onClick={onClose}>取消</button>
        <button type="button" className="btn-danger" onClick={handleDelete} disabled={loading}>
          {loading ? '删除中…' : '删除'}
        </button>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Main AdminPage
// ---------------------------------------------------------------------------

function AdminPage() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [modal, setModal] = useState(null); // { type: 'create' | 'edit' | 'password' | 'delete', user? }

  const fetchUsers = useCallback(async () => {
    try {
      const data = await listUsers();
      setUsers(data.users || data || []);
      setError('');
    } catch (err) {
      setError(err.message || '加载用户列表失败，请刷新页面重试');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <p className="text-sm text-ink-500">加载用户列表…</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-purple-500/10 text-purple-600">
            <FaUsers className="text-lg" aria-hidden="true" />
          </div>
          <div>
            <h2 className="font-display text-xl font-semibold text-ink-900">用户管理</h2>
            <p className="text-sm text-ink-500">{users.length} 个用户</p>
          </div>
        </div>
        <button type="button" className="btn-primary" onClick={() => setModal({ type: 'create' })}>
          <FaPlus aria-hidden="true" />
          创建用户
        </button>
      </div>

      {/* Error */}
      {error ? (
        <div className="rounded-xl border border-red-300/50 bg-red-50/70 px-4 py-3 text-sm text-red-700" role="alert" aria-live="polite">{error}</div>
      ) : null}

      {/* User table */}
      <div className="dossier-panel overflow-hidden rounded-2xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-ink-900/10 bg-ink-50/50">
              <tr>
                <th className="px-4 py-3 font-medium text-ink-500">用户名</th>
                <th className="px-4 py-3 font-medium text-ink-500">邮箱</th>
                <th className="px-4 py-3 font-medium text-ink-500">角色</th>
                <th className="px-4 py-3 font-medium text-ink-500">创建时间</th>
                <th className="px-4 py-3 text-right font-medium text-ink-500">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-900/8">
              {users.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-ink-500">暂无用户</td>
                </tr>
              ) : (
                users.map((user) => (
                  <tr key={user.username} className="hover:bg-white/45">
                    <td className="px-4 py-3 font-medium text-ink-900">{user.username}</td>
                    <td className="px-4 py-3 text-ink-500">{user.email || '-'}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {(user.roles || []).filter(Boolean).map((role) => (
                          <span key={role} className="rounded-full bg-ink-900/8 px-2.5 py-0.5 text-xs font-medium text-ink-500">
                            {role}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-ink-500">
                      {user.created_at ? USER_DATE_FORMATTER.format(new Date(user.created_at)) : '-'}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-ink-500 transition hover:bg-ink-900/5 hover:text-ink-700"
                          onClick={() => setModal({ type: 'edit', user })}
                        >
                          <FaEdit aria-hidden="true" />
                          编辑
                        </button>
                        <button
                          type="button"
                          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-ink-500 transition hover:bg-ink-900/5 hover:text-ink-700"
                          onClick={() => setModal({ type: 'password', user })}
                        >
                          <FaKey aria-hidden="true" />
                          密码
                        </button>
                        <button
                          type="button"
                          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-red-500 transition hover:bg-red-50 hover:text-red-700"
                          onClick={() => setModal({ type: 'delete', user })}
                        >
                          <FaTrash aria-hidden="true" />
                          删除
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Modals */}
      {modal?.type === 'create' ? (
        <CreateUserModal onClose={() => setModal(null)} onCreated={fetchUsers} />
      ) : null}
      {modal?.type === 'edit' ? (
        <EditUserModal user={modal.user} onClose={() => setModal(null)} onUpdated={fetchUsers} />
      ) : null}
      {modal?.type === 'password' ? (
        <ChangePasswordModal user={modal.user} onClose={() => setModal(null)} />
      ) : null}
      {modal?.type === 'delete' ? (
        <DeleteConfirmModal user={modal.user} onClose={() => setModal(null)} onDeleted={fetchUsers} />
      ) : null}
    </div>
  );
}

export default AdminPage;
