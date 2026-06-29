/**
 * GradeStrip — A/B/C/D horizontal grade bar.
 *
 * Reference: prototype ReportPage gradeStrip section.
 * Active cell: ink-900 bg, paper-50 text.
 * Inactive: paper-200 bg, ink-500 text.
 */

const GRADE_LABELS = {
  A: '完全通过',
  B: '有条件通过',
  C: '待修订',
  D: '未通过',
};

const GRADES = ['A', 'B', 'C', 'D'];

export default function GradeStrip({ grade, dimensions }) {
  return (
    <div>
      <div className="grid grid-cols-4 overflow-hidden rounded-sm border border-ink-900/10 bg-white">
        {GRADES.map((g, i) => {
          const isActive = g === grade;
          return (
            <div
              key={g}
              className={`relative px-5 py-8 text-center ${
                i < GRADES.length - 1 ? 'border-r border-ink-900/10' : ''
              } ${isActive ? 'bg-ink-900' : 'bg-paper-200'}`}
            >
              <div
                className={`font-display text-[56px] font-normal leading-none ${
                  isActive ? 'text-paper-50' : 'text-ink-900'
                }`}
              >
                {g}
              </div>
              <div
                className={`mt-2 text-[11px] tracking-widest ${
                  isActive ? 'text-paper-300' : 'text-ink-500'
                }`}
              >
                {GRADE_LABELS[g]}
              </div>
              {isActive && (
                <div className="absolute bottom-0 left-1/2 h-0.5 w-[30px] -translate-x-1/2 bg-paper-50" />
              )}
            </div>
          );
        })}
      </div>

      {dimensions && dimensions.length > 0 && (
        <div className="mt-10 grid grid-cols-4 border-t border-b border-ink-900/10">
          {dimensions.map((d, i) => (
            <div
              key={d.name}
              className={`px-5 py-5 ${i < dimensions.length - 1 ? 'border-r border-ink-900/10' : ''}`}
            >
              <div className="text-xs font-medium text-ink-900">{d.label}</div>
              <div className="mt-0.5 font-display text-[11px] text-ink-500 italic">
                {d.name}
              </div>
              <div
                className={`mt-3.5 font-display text-[22px] font-normal ${
                  d.status === 'pass'
                    ? 'text-ink-900'
                    : d.status === 'fail'
                      ? 'text-risk-500'
                      : 'text-accent-500'
                }`}
              >
                {d.verdict}
              </div>
              {d.detail && (
                <div className="mt-1.5 text-[11px] leading-[1.5] text-ink-700">
                  {d.detail}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
