// Progressive disclosure: collapsed by default. A native <details>, so Enter or Space opens it from the keyboard and
// the content inside is the original section, unchanged. `term` keeps the internal name next to the plain one.
export function More({ title, term, hint, id, className = "", children }) {
  return (
    <details className={`more ${className}`.trim()} id={id}>
      <summary>
        <span className="more-title">{title}</span>
        {term && <span className="term">{term}</span>}
        {hint !== undefined && hint !== null && <span className="more-hint">{hint}</span>}
      </summary>
      <div className="more-body">{children}</div>
    </details>
  );
}
