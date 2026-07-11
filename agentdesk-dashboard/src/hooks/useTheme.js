import { useState, useEffect } from "react";

const CYBERPUNK  = "cyberpunk";
const CORPORATE  = "corporate";

export function useTheme() {
  const [theme, setTheme] = useState(
    () => localStorage.getItem("agentdesk-ui-theme") ?? CYBERPUNK
  );

  const isCyberpunk = theme === CYBERPUNK;

  useEffect(() => {
    const root = document.documentElement;
    if (isCyberpunk) {
      root.classList.remove(CORPORATE);
    } else {
      root.classList.add(CORPORATE);
    }
    localStorage.setItem("agentdesk-ui-theme", theme);
  }, [theme, isCyberpunk]);

  const toggle = () => setTheme(t => t === CYBERPUNK ? CORPORATE : CYBERPUNK);

  return { theme, toggle, isCyberpunk };
}
