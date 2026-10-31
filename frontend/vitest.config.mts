import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react() as never], // plugin-react and vitest bundle different vite typings; runtime is identical
  resolve: { alias: { "@": fileURLToPath(new URL("./", import.meta.url)) } },
  test: {
    environment: "jsdom",
    setupFiles: ["./test-support/setup.ts"],
    include: ["**/*.test.{ts,tsx}"],
    exclude: ["node_modules/**", ".next/**"],
    css: false,
    // jsdom + the full CEO Hub tree makes the first render in a file cost 1-2 s alone; with every core busy it passed the 5 s limit (ceoDecide, ceoAttach, ceoInput, ceoSendFailure; also on 8ab58ea). Half the cores keeps the default limit meaningful.
    maxWorkers: "50%",
  },
});
