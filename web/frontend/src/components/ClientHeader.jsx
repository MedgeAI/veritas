/**
 * 客户门户 Header
 *
 * 结构：
 * - Logo: V mark + "Veritas" + italic tagline
 * - 6 Tab 导航: 提交、进度、报告、问题、重核、验证
 * - Active tab 有底部 accent 色边框
 * - Sticky，1px bottom border ink-900/10
 */

const TABS = [
  { id: 'submit', label: '提交' },
  { id: 'progress', label: '进度' },
  { id: 'report', label: '报告' },
  { id: 'issue', label: '问题' },
  { id: 'reverification', label: '重核' },
  { id: 'verify', label: '验证' },
];

export default function ClientHeader({ activeTab, onTabChange }) {
  return (
    <header className="sticky top-0 z-50 bg-paper-50 border-b border-ink-900/10">
      <div className="max-w-[980px] mx-auto px-14 py-5 flex items-center justify-between">
        {/* Logo */}
        <div className="flex items-center gap-3.5">
          <div className="w-9 h-9 bg-ink-900 text-paper-50 flex items-center justify-center font-display italic text-[22px] rounded-[2px]" aria-hidden="true">
            V
          </div>
          <div>
            <div className="font-display text-[22px] tracking-wide">Veritas</div>
            <div className="text-[10px] text-ink-900/50 tracking-widest mt-0.5 italic">
              Independent verification for computational research
            </div>
          </div>
        </div>

        {/* Tab Navigation */}
        <nav className="flex gap-1" aria-label="主导航">
          {TABS.map((tab) => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => onTabChange(tab.id)}
                aria-current={isActive ? 'page' : undefined}
                className={`
                  bg-transparent cursor-pointer px-3 py-1.5 text-xs rounded-[2px]
                  transition-colors duration-150
                  focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50
                  ${isActive
                    ? 'text-ink-900 border-b-2 border-accent-500'
                    : 'text-ink-900/50 hover:text-ink-900/70'
                  }
                `}
              >
                {tab.label}
              </button>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
