import type { Config } from "tailwindcss";

/**
 * Proteus Factory Home — JARVIS + TRON theme reference.
 *
 * This is a future frontend configuration artifact. The current repository does
 * not use Tailwind, so this file must be copied into a separately approved
 * Tailwind frontend rather than added to the existing FastAPI runtime.
 */
const factoryTheme: Config = {
  content: [
    "./src/**/*.{html,js,ts,jsx,tsx}",
    "./app/**/*.{html,js,ts,jsx,tsx}",
    "./components/**/*.{html,js,ts,jsx,tsx}",
  ],
  darkMode: ["class", '[data-theme="factory"]'],
  theme: {
    extend: {
      colors: {
        factory: {
          canvas: {
            950: "#04090C",
            900: "#061014",
            850: "#08151A",
          },
          surface: {
            900: "#0A171C",
            850: "#0E2026",
            800: "#132B32",
            raised: "#10242B",
          },
          line: {
            quiet: "#1C3942",
            DEFAULT: "#2E5661",
            bright: "#4E8390",
            focus: "#70FFF8",
          },
          ink: {
            100: "#F0FFFE",
            200: "#D6F4F1",
            300: "#B5D8D5",
            400: "#8DB5B2",
            500: "#668D8B",
            600: "#456967",
          },
          cyan: {
            100: "#D7FFFC",
            200: "#A9FFF9",
            300: "#70FFF8",
            400: "#4CEDE7",
            500: "#29D4D0",
            600: "#159F9E",
            700: "#0F7374",
          },
          violet: {
            200: "#D6CCFF",
            300: "#C1B2FF",
            400: "#AB95FF",
            500: "#8D71E8",
            600: "#6C52BC",
          },
          amber: {
            200: "#FFE3A6",
            300: "#FFD27A",
            400: "#FFBE4E",
            500: "#E99B22",
            600: "#B96C10",
          },
          red: {
            200: "#FFD1D5",
            300: "#FFA5AC",
            400: "#FF7E87",
            500: "#E75561",
            600: "#B93645",
          },
          green: {
            200: "#CEFFE0",
            300: "#A5F5C2",
            400: "#78DB9D",
            500: "#43AF70",
            600: "#237E4D",
          },
        },
        state: {
          running: "#4CEDE7",
          planning: "#AB95FF",
          waiting: "#FFBE4E",
          paused: "#8DB5B2",
          recovering: "#70FFF8",
          completed: "#78DB9D",
          failed: "#FF7E87",
          stale: "#B5D8D5",
        },
      },
      fontFamily: {
        sans: [
          "Inter Variable",
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "sans-serif",
        ],
        display: [
          "Space Grotesk",
          "Inter Variable",
          "ui-sans-serif",
          "system-ui",
          "sans-serif",
        ],
        mono: [
          "IBM Plex Mono",
          "SFMono-Regular",
          "Consolas",
          "Liberation Mono",
          "monospace",
        ],
      },
      letterSpacing: {
        telemetry: "0.13em",
        display: "0.045em",
        command: "0.08em",
      },
      borderRadius: {
        factory: "0px",
        "factory-sm": "2px",
      },
      spacing: {
        18: "4.5rem",
        22: "5.5rem",
        26: "6.5rem",
      },
      boxShadow: {
        "cyan-hairline": "0 0 0 1px rgb(112 255 248 / 0.48)",
        "cyan-focus": "0 0 0 2px rgb(112 255 248 / 0.92), 0 0 18px rgb(76 237 231 / 0.22)",
        "cyan-trace": "0 0 14px rgb(76 237 231 / 0.28), inset 0 0 0 1px rgb(112 255 248 / 0.42)",
        "amber-signal": "0 0 14px rgb(255 190 78 / 0.18)",
        "red-signal": "0 0 14px rgb(255 126 135 / 0.18)",
        "surface-lift": "0 18px 50px rgb(0 0 0 / 0.30)",
      },
      backgroundImage: {
        "factory-grid": "linear-gradient(rgb(46 86 97 / 0.16) 1px, transparent 1px), linear-gradient(90deg, rgb(46 86 97 / 0.16) 1px, transparent 1px)",
        "factory-grid-fine": "linear-gradient(rgb(112 255 248 / 0.075) 1px, transparent 1px), linear-gradient(90deg, rgb(112 255 248 / 0.075) 1px, transparent 1px)",
        "factory-radial": "radial-gradient(circle at 50% -12%, rgb(41 212 208 / 0.17), transparent 52%)",
        "trace-top": "linear-gradient(90deg, transparent, rgb(112 255 248 / 0.95), transparent)",
        "surface-sheen": "linear-gradient(135deg, rgb(19 43 50 / 0.92), rgb(10 23 28 / 0.98))",
        "stale-hatch": "repeating-linear-gradient(135deg, transparent 0 7px, rgb(181 216 213 / 0.10) 7px 9px)",
        "waiting-hatch": "repeating-linear-gradient(135deg, transparent 0 7px, rgb(255 190 78 / 0.12) 7px 9px)",
      },
      backgroundSize: {
        grid: "48px 48px",
        "grid-fine": "12px 12px",
      },
      keyframes: {
        "trace-once": {
          "0%": { transform: "scaleX(0)", transformOrigin: "left", opacity: "0" },
          "18%": { opacity: "1" },
          "100%": { transform: "scaleX(1)", transformOrigin: "left", opacity: "0.92" },
        },
        "receipt-signal": {
          "0%": { transform: "translateX(-10%)", opacity: "0" },
          "22%": { opacity: "1" },
          "100%": { transform: "translateX(100%)", opacity: "0" },
        },
        "panel-reveal": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "snapshot-sweep": {
          "0%": { transform: "translateX(-115%)", opacity: "0" },
          "20%": { opacity: "0.68" },
          "100%": { transform: "translateX(115%)", opacity: "0" },
        },
        "gate-arrival": {
          "0%": { transform: "scaleX(0.2)", opacity: "0.2" },
          "100%": { transform: "scaleX(1)", opacity: "1" },
        },
        "connection-bloom": {
          "0%": { boxShadow: "0 0 0 0 rgb(76 237 231 / 0)" },
          "45%": { boxShadow: "0 0 20px 3px rgb(76 237 231 / 0.24)" },
          "100%": { boxShadow: "0 0 0 0 rgb(76 237 231 / 0)" },
        },
        "progress-traverse": {
          "0%": { transform: "translateX(-65%)" },
          "100%": { transform: "translateX(165%)" },
        },
      },
      animation: {
        "trace-once": "trace-once 160ms cubic-bezier(0.2, 0.8, 0.2, 1) both",
        "receipt-signal": "receipt-signal 190ms cubic-bezier(0.2, 0.8, 0.2, 1) both",
        "panel-reveal": "panel-reveal 180ms cubic-bezier(0.2, 0.8, 0.2, 1) both",
        "snapshot-sweep": "snapshot-sweep 210ms ease-out both",
        "gate-arrival": "gate-arrival 180ms cubic-bezier(0.2, 0.8, 0.2, 1) both",
        "connection-bloom": "connection-bloom 140ms ease-out both",
        "progress-traverse": "progress-traverse 900ms linear infinite",
      },
      transitionTimingFunction: {
        command: "cubic-bezier(0.2, 0.8, 0.2, 1)",
      },
      transitionDuration: {
        command: "160ms",
        response: "220ms",
      },
      zIndex: {
        grid: "-1",
        halo: "0",
        content: "1",
        focus: "10",
      },
    },
  },
  plugins: [],
};

export default factoryTheme;
