/**
 * 客户门户 Footer
 *
 * 两行内容：
 * - 品牌名
 * - Italic tagline
 * - 居中，muted 文字
 */

export default function ClientFooter() {
  return (
    <footer className="max-w-[980px] mx-auto px-14 py-10 pb-15 border-t border-ink-900/10 text-center text-[11px] text-ink-900/50 tracking-wide">
      <div>Veritas · Independent verification for computational research</div>
      <div className="font-display italic mt-1.5">
        We don't judge how good your research is. We only certify that what you said is true.
      </div>
    </footer>
  );
}
