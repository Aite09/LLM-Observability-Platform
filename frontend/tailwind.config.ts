import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        surface: "var(--surface)",
        raise: "var(--raise)",
        hairline: "var(--hairline)",
        rule: "var(--rule)",
        ink: "var(--ink)",
        "ink-2": "var(--ink-2)",
        faint: "var(--faint)",
        accent: "var(--accent)",
        "accent-soft": "var(--accent-soft)",
        sage: "var(--sage)",
        rust: "var(--rust)",
      },
      fontFamily: {
        display: ["Jersey 25", "IBM Plex Sans", "sans-serif"],
        ui: ["IBM Plex Sans", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
