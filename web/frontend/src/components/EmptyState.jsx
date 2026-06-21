function EmptyState({ title, message, children }) {
  return (
    <section className="dossier-panel rounded-[2rem] p-8 text-center">
      {title ? (
        <p className="font-display text-2xl font-semibold">{title}</p>
      ) : null}
      {message ? (
        <p className={title ? "mt-3 text-sm leading-6 text-ink-500" : "text-sm text-ink-500"}>{message}</p>
      ) : null}
      {children}
    </section>
  );
}

export default EmptyState;
