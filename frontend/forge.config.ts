import type { ForgeConfig } from "@electron-forge/shared-types";
import { MakerSquirrel } from "@electron-forge/maker-squirrel";
import { MakerZIP } from "@electron-forge/maker-zip";
import { MakerDeb } from "@electron-forge/maker-deb";
import { MakerRpm } from "@electron-forge/maker-rpm";
import { VitePlugin } from "@electron-forge/plugin-vite";
import { execFileSync } from "child_process";
import path from "path";
import fs from "fs";

const stagedBackendRoot = path.resolve(__dirname, ".packaged-backend");
const stagedBackendDir = path.join(stagedBackendRoot, "backend");
const stagedPythonDir = path.join(stagedBackendRoot, "python");

function shouldStagePackagedResources() {
  const lifecycleEvent = process.env.npm_lifecycle_event;
  if (lifecycleEvent === "package" || lifecycleEvent === "make") {
    return true;
  }

  return process.argv.includes("package") || process.argv.includes("make");
}

function shouldSkipPath(relativePath: string, skipPatterns: string[]) {
  return skipPatterns.some((pattern) =>
    relativePath === pattern || relativePath.startsWith(`${pattern}/`)
  );
}

function copyDirectory(
  sourceDir: string,
  targetDir: string,
  skipPatterns: string[],
  options: { dereference?: boolean } = {},
) {
  fs.cpSync(sourceDir, targetDir, {
    recursive: true,
    dereference: options.dereference ?? true,
    filter: (source) => {
      const relativePath = path.relative(sourceDir, source);
      if (!relativePath) {
        return true;
      }

      const normalizedPath = relativePath.split(path.sep).join("/");
      const baseName = path.basename(source);

      if (
        shouldSkipPath(normalizedPath, skipPatterns) ||
        baseName.endsWith(".pyc") ||
        baseName.endsWith(".pyo")
      ) {
        return false;
      }

      return true;
    },
  });
}

function getBundledPythonExecutable(pythonRoot: string) {
  const candidates =
    process.platform === "win32"
      ? [path.join(pythonRoot, "python.exe"), path.join(pythonRoot, "Scripts", "python.exe")]
      : [path.join(pythonRoot, "bin", "python3"), path.join(pythonRoot, "bin", "python")];

  const executable = candidates.find((candidate) => fs.existsSync(candidate));
  if (!executable) {
    throw new Error(`Could not find bundled Python executable in ${pythonRoot}`);
  }

  return executable;
}

function tryGetBuildPythonInfo(candidate: string) {
  try {
    const payload = execFileSync(
      candidate,
      [
        "-c",
        "import json, sys, fastapi, uvicorn, aiosqlite, pydantic, camel; print(json.dumps({'executable': sys.executable, 'prefix': sys.prefix, 'version': sys.version.split()[0]}))",
      ],
      { encoding: "utf-8" },
    ).trim();

    return JSON.parse(payload) as {
      executable: string;
      prefix: string;
      version: string;
    };
  } catch {
    return null;
  }
}

function getBuildPythonInfo() {
  const candidates = [
    process.env.CAPE_AGENT_BUNDLE_PYTHON_BIN,
    process.env.CAPE_AGENT_PYTHON_BIN,
    process.env.PYENV_ROOT ? path.join(process.env.PYENV_ROOT, "shims", "python3") : undefined,
    process.env.PYENV_ROOT ? path.join(process.env.PYENV_ROOT, "shims", "python") : undefined,
    process.env.HOME ? path.join(process.env.HOME, ".pyenv", "shims", "python3") : undefined,
    process.env.HOME ? path.join(process.env.HOME, ".pyenv", "shims", "python") : undefined,
    "python3",
    "python",
  ].filter((candidate): candidate is string => Boolean(candidate));

  for (const candidate of candidates) {
    const info = tryGetBuildPythonInfo(candidate);
    if (info) {
      return info;
    }
  }

  throw new Error(
    "Could not find a Python interpreter with fastapi, uvicorn, aiosqlite, pydantic, and camel installed",
  );
}

function getBuildPythonMetadata() {
  return getBuildPythonInfo() as {
    executable: string;
    prefix: string;
    version: string;
  };
}

function stageBackendResources() {
  const sourceBackendDir = path.resolve(__dirname, "../backend");

  copyDirectory(sourceBackendDir, stagedBackendDir, [
    ".backend_port",
    "cape_agent.db",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "build",
    "dist",
  ], { dereference: true });

  for (const entry of fs.readdirSync(stagedBackendDir)) {
    if (entry.endsWith(".egg-info")) {
      fs.rmSync(path.join(stagedBackendDir, entry), { recursive: true, force: true });
    }
  }
}

function stagePythonRuntime() {
  const pythonInfo = getBuildPythonMetadata();
  console.log(
    `[packaging] Bundling Python ${pythonInfo.version} from ${pythonInfo.prefix} (${pythonInfo.executable})`,
  );

  copyDirectory(pythonInfo.prefix, stagedPythonDir, ["__pycache__"], {
    dereference: false,
  });

  const bundledPython = getBundledPythonExecutable(stagedPythonDir);
  execFileSync(
    bundledPython,
    [
      "-c",
      "import fastapi, uvicorn, aiosqlite, pydantic, camel; print('bundled-python-ok')",
    ],
    { stdio: "inherit" },
  );
}

if (shouldStagePackagedResources()) {
  fs.rmSync(stagedBackendRoot, { recursive: true, force: true });
  stageBackendResources();
  stagePythonRuntime();
}

const config: ForgeConfig = {
  packagerConfig: {
    asar: true,
    icon: path.resolve(__dirname, "src/resources/icon"),
    extraResource: [stagedBackendDir, stagedPythonDir],
  },
  rebuildConfig: {},
  makers: [
    new MakerSquirrel({}),
    new MakerZIP({}, ["darwin"]),
    new MakerDeb({}),
    new MakerRpm({}),
  ],
  plugins: [
    new VitePlugin({
      build: [
        {
          entry: "src/main/index.ts",
          config: "vite.main.config.ts",
          target: "main",
        },
        {
          entry: "src/main/preload.ts",
          config: "vite.preload.config.ts",
          target: "preload",
        },
      ],
      renderer: [
        {
          name: "main_window",
          config: "vite.renderer.config.ts",
        },
      ],
    }),
  ],
};

export default config;
