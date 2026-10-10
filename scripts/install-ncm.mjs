import { existsSync, rmSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

const repoUrl = "https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced.git";
const commit = "2db6684453297ee86dec0492842f2320b08182d9";
const target = resolve("vendor", "ncm-api");

if (process.env.SKIP_BUNDLED_NCM === "1") {
  console.log("Skipping bundled NCM source installation");
  process.exit(0);
}

if (existsSync(resolve(target, "app.js"))) {
  console.log("Bundled NCM source already installed");
  process.exit(0);
}

const run = (command, args, options = {}) => {
  const result = spawnSync(command, args, { stdio: "inherit", ...options });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed with exit code ${result.status}`);
  }
};

rmSync(target, { recursive: true, force: true });
run("git", ["init", target]);
run("git", ["-C", target, "remote", "add", "origin", repoUrl]);
run("git", ["-C", target, "fetch", "--depth", "1", "origin", commit]);
run("git", ["-C", target, "checkout", "--detach", "FETCH_HEAD"]);
run("npm", ["install", "--omit=dev", "--ignore-scripts"], { cwd: target });

console.log(`Bundled NCM source installed at ${target}`);
