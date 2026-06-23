import { useCallback, useEffect, useState } from 'react';
import { FaEdit, FaKey, FaPlus, FaTrash, FaUsers } from 'react-icons/fa';
import { FiRefreshCw } from 'react-icons/fi';
import { listUsers, createUser, updateUser, deleteUser, changePassword } from '../services/api.js';

// ---------------------------------------------------------------------------
// Modal wrapper
// ---------------------------------------------------------------------------

function Modal({ title, onClose, children }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="font-display text-lg font-semibold text-ink-900">{title}</h3>
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
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [email, setEmail] = useState('');
  const [roles, setRoles] = useState('user');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError('用户名和密码不能为空');
      return;
    }
    setLoading(true);
    setError('');
    try {
      await createUser(username.trim(), password, email.trim() || undefined, roles.split(',').map((r) => r.trim()).filter(Boolean));
      onCreated();
      onClose();
    } catch (err) {
      setError(err.message || '创建失败');
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal title="创建用户" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="mb-1 block text-sm font-medium text-ink-700">用户名 *</label>
          <input className="input-field" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-ink-700">密码 *</label>
          <input className="input-field" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-ink-700">邮箱</label>
          <input className="input-field" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-ink-700">角色（逗号分隔）</label>
          <input className="input-field" value={roles} onChange={(e) => setRoles(e.target.value)} placeholder="user, admin" />
        </div>
        {error ? <div className="rounded-xl border border-red-300/50 bg-red-50/70 px-3 py-2 text-sm text-red-700" role="alert" aria-live="polite">{error}</div> : null}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>取消</button>
          <button type="submit" className="btn-primary" disabled={loading}>{loading ? '创建中...' : '创建'}</button>
        </div>
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Edit user form
// ---------------------------------------------------------------------------

function EditUserModal({ user, onClose, onUpdated }) {
  const [email, setEmail] = useState(user.email || '');
  const [roles, setRoles] = useState((user.roles || []).join(', '));
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      await updateUser(user.username, email.trim() || undefined, roles.split(',').map((r) => r.trim()).filter(Boolean));
      onUpdated();
      onClose();
    } catch (err) {
      setError(err.message || '更新失败');
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal title={`编辑用户: ${user.username}`} onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="mb-1 block text-sm font-medium text-ink-700">邮箱</label>
          <input className="input-field" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-ink-700">角色（逗号分隔）</label>
          <input className="input-field" value={roles} onChange={(e) => setRoles(e.target.value)} />
        </div>
        {error ? <div className="rounded-xl border border-red-300/50 bg-red-50/70 px-3 py-2 text-sm text-red-700" role="alert" aria-live="polite">{error}</div> : null}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>取消</button>
          <button type="submit" className="btn-primary" disabled={loading}>{loading ? '保存中...' : '保存'}</button>
        </div>
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Change password form
// ---------------------------------------------------------------------------

function ChangePasswordModal({ user, onClose }) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!password) {
      setError('密码不能为空');
      return;
    }
    setLoading(true);
    setError('');
    try {
      await changePassword(user.username, password);
      setSuccess(true);
      setPassword('');
    } catch (err) {
      setError(err.message || '修改失败');
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal title={`修改密码: ${user.username}`} onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="mb-1 block text-sm font-medium text-ink-700">新密码</label>
          <input className="input-field" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus />
        </div>
        {error ? <div className="rounded-xl border border-red-300/50 bg-red-50/70 px-3 py-2 text-sm text-red-700" role="alert" aria-live="polite">{error}</div> : null}
        {success ? <div className="rounded-xl border border-green-300/50 bg-green-50/70 px-3 py-2 text-sm text-green-700">密码已修改</div> : null}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>关闭</button>
          <button type="submit" className="btn-primary" disabled={loading}>{loading ? '修改中...' : '修改密码'}</button>
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
      setError(err.message || '删除失败');
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal title="确认删除" onClose={onClose}>
      <p className="mb-4 text-sm text-ink-600">
        确定要删除用户 <strong className="text-ink-900">{user.username}</strong> 吗？此操作不可撤销。
      </p>
      {error ? <div className="mb-4 rounded-xl border border-red-300/50 bg-red-50/70 px-3 py-2 text-sm text-red-700" role="alert" aria-live="polite">{error}</div> : null}
      <div className="flex justify-end gap-2">
        <button type="button" className="btn-ghost" onClick={onClose}>取消</button>
        <button type="button" className="btn-danger" onClick={handleDelete} disabled={loading}>
          {loading ? '删除中...' : '删除'}
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
      setError(err.message || '加载用户列表失败');
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
        <p className="text-sm text-ink-400">加载用户列表...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-purple-500/10 text-purple-600">
            <FaUsers className="text-lg" />
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
        <div className="rounded-xl border border-red-300/50 bg-red-50/70 px-4 py-3 text-sm text-red-700">{error}</div>
      ) : null}

      {/* User table */}
      <div className="dossier-panel overflow-hidden rounded-2xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-ink-900/10 bg-ink-50/50">
              <tr>
                <th className="px-4 py-3 font-medium text-ink-600">用户名</th>
                <th className="px-4 py-3 font-medium text-ink-600">邮箱</th>
                <th className="px-4 py-3 font-medium text-ink-600">角色</th>
                <th className="px-4 py-3 font-medium text-ink-600">创建时间</th>
                <th className="px-4 py-3 text-right font-medium text-ink-600">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-900/8">
              {users.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-ink-400">暂无用户</td>
                </tr>
              ) : (
                users.map((user) => (
                  <tr key={user.username} className="hover:bg-white/45">
                    <td className="px-4 py-3 font-medium text-ink-900">{user.username}</td>
                    <td className="px-4 py-3 text-ink-600">{user.email || '-'}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {(user.roles || []).filter(Boolean).map((role) => (
                          <span key={role} className="rounded-full bg-ink-900/8 px-2.5 py-0.5 text-xs font-medium text-ink-600">
                            {role}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-ink-400">
                      {user.created_at ? new Date(user.created_at).toLocaleDateString() : '-'}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-ink-500 transition hover:bg-ink-900/5 hover:text-ink-700"
                          onClick={() => setModal({ type: 'edit', user })}
                        >
                          <FaEdit />
                          编辑
                        </button>
                        <button
                          type="button"
                          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-ink-500 transition hover:bg-ink-900/5 hover:text-ink-700"
                          onClick={() => setModal({ type: 'password', user })}
                        >
                          <FaKey />
                          密码
                        </button>
                        <button
                          type="button"
                          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-red-500 transition hover:bg-red-50 hover:text-red-700"
                          onClick={() => setModal({ type: 'delete', user })}
                        >
                          <FaTrash />
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
