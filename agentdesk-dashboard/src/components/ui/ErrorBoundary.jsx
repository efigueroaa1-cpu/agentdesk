import { Component } from "react";

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("[ErrorBoundary]", error?.message, info?.componentStack?.slice(0, 300));
  }

  render() {
    if (this.state.error) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div style={{
          padding: "1.5rem", borderRadius: 10, textAlign: "center",
          border: "1px solid rgba(255,45,85,.3)", background: "rgba(255,45,85,.05)",
          color: "#ff2d55", fontSize: ".8rem", display: "flex", flexDirection: "column", gap: 8,
        }}>
          <span style={{ fontWeight: 700 }}>Error al cargar componente</span>
          <span style={{ color: "var(--t-text-muted)", fontSize: ".72rem" }}>
            {this.state.error?.message ?? "Error desconocido"}
          </span>
          <button
            onClick={() => this.setState({ error: null })}
            style={{
              alignSelf: "center", padding: "5px 16px", borderRadius: 7,
              border: "1px solid rgba(255,45,85,.4)", background: "transparent",
              color: "#ff2d55", cursor: "pointer", fontSize: ".72rem", fontFamily: "inherit",
            }}
          >
            Reintentar
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
