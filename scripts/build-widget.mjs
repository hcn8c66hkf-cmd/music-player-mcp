import { build } from "tsup";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");

await build({
  entry: [resolve(root, "widget-src/music-player-widget.ts")],
  outDir: resolve(root, "dist/widget"),
  format: ["iife"],
  globalName: "MusicPlayerWidget",
  platform: "browser",
  target: "es2020",
  bundle: true,
  minify: true,
  sourcemap: false,
  clean: true,
  dts: false,
  splitting: false,
  outExtension: () => ({ js: ".global.js" }),
});

console.log("Music widget built.");
