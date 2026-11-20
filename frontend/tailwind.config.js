import formsPlugin from "@tailwindcss/forms";

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#f3f2ff",
          100: "#e9e7ff",
          500: "#7065e8",
          600: "#5b4fd6",
          700: "#4b40bd",
        },
      },
      boxShadow: {
        panel: "0 1px 3px rgba(20, 24, 40, 0.05), 0 8px 24px rgba(20, 24, 40, 0.025)",
      },
    },
  },
  plugins: [formsPlugin],
};
