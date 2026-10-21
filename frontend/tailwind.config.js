/**
 * DriftWear design tokens: a tailoring palette.
 *   Surfaces   canvas (warm stone), surface (muslin), raised (white), seam (hairlines)
 *   Type       fg (charcoal), muted, faint
 *   Brand      navy (suiting ink) for chrome and primary actions, plum (lining) as the single accent
 *   States     stable / warning / drift / adapted, each with an -ink (text) and -soft (fill) step.
 *              Reserved for detector and model states only. Validated for colour-vision deficiency
 *              (adjacent ΔE ≥ 10) and always paired with an icon and a label.
 *   Reference  stone, for baselines and reference windows in charts.
 */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#EFEDE9",
        surface: "#FBFAF8",
        raised: "#FFFFFF",
        seam: { DEFAULT: "#DEDAD2", strong: "#C9C3B8" },
        fg: "#24262B",
        muted: "#5F5C56",
        faint: "#7E7A73",
        stone: "#A39E94",
        navy: { DEFAULT: "#172036", 800: "#1F2A45", 700: "#2A3756", 600: "#3A4868", 300: "#9AA2B4", 200: "#C7CCD8", 100: "#E4E7EE", 50: "#F1F2F6" },
        plum: { DEFAULT: "#7A3366", 700: "#642953", 300: "#D9A6C8", 100: "#F2E4EE", 50: "#F8F1F6" },
        stable: { DEFAULT: "#1A8F6E", ink: "#146B52", soft: "#E3F1EC" },
        warning: { DEFAULT: "#C88A12", ink: "#85590A", soft: "#F8EDD5" },
        drift: { DEFAULT: "#B8261F", ink: "#A32019", soft: "#F7E3E1" },
        adapted: { DEFAULT: "#2A4FC2", ink: "#2443A8", soft: "#E4E9F8" },
      },
      fontFamily: {
        sans: ['"Archivo"', "system-ui", "-apple-system", '"Segoe UI"', "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", '"Liberation Mono"', "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
        xs: ["0.75rem", { lineHeight: "1.05rem" }],
        sm: ["0.8125rem", { lineHeight: "1.25rem" }],
        base: ["0.875rem", { lineHeight: "1.4rem" }],
        md: ["1rem", { lineHeight: "1.5rem" }],
        lg: ["1.25rem", { lineHeight: "1.65rem" }],
        xl: ["1.5625rem", { lineHeight: "1.9rem" }],
        "2xl": ["2rem", { lineHeight: "2.25rem" }],
        "3xl": ["2.5rem", { lineHeight: "2.7rem" }],
        "4xl": ["3.5rem", { lineHeight: "3.5rem" }],
      },
      maxWidth: { content: "1320px", prose: "68ch" },
      boxShadow: {
        pop: "0 1px 2px rgba(23,32,54,.06), 0 8px 24px -6px rgba(23,32,54,.18)",
        dialog: "0 24px 64px -12px rgba(23,32,54,.35)",
      },
      keyframes: {
        "toast-in": { from: { opacity: "0", transform: "translateY(8px)" }, to: { opacity: "1", transform: "none" } },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "slide-in": { from: { transform: "translateX(16px)", opacity: "0" }, to: { transform: "none", opacity: "1" } },
      },
      animation: {
        "toast-in": "toast-in 180ms ease-out",
        "fade-in": "fade-in 150ms ease-out",
        "slide-in": "slide-in 180ms ease-out",
      },
    },
  },
  plugins: [],
};
