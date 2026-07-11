export function SkipLink() {
  return (
    <a
      href="#main-content"
      style={{
        position: "absolute", top: -40, left: 0, zIndex: 99999,
        padding: "8px 16px", background: "var(--t-accent)", color: "#000",
        fontWeight: 600, fontSize: ".85rem", borderRadius: "0 0 8px 0",
        transition: "top .2s",
        "&:focus": { top: 0 },
      }}
      onFocus={e => { e.currentTarget.style.top = "0"; }}
      onBlur={e => { e.currentTarget.style.top = "-40px"; }}
    >
      Saltar al contenido principal
    </a>
  );
}

export function LiveRegion({ message }) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="true"
      style={{ position: "absolute", left: -9999, width: 1, height: 1, overflow: "hidden" }}
    >
      {message}
    </div>
  );
}
