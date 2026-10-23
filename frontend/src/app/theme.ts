export type Theme = "light" | "dark";
const storageKey = "videomind-theme";

export function preferredTheme(): Theme {
  try {
    const saved = localStorage.getItem(storageKey);
    if (saved === "light" || saved === "dark") return saved;
  } catch { /* Themes still work when browser storage is unavailable. */ }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
}

export function saveTheme(theme: Theme) {
  applyTheme(theme);
  try { localStorage.setItem(storageKey, theme); }
  catch { /* Keep the selection for this session even without storage. */ }
}
