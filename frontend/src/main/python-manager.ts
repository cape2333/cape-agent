import { app } from "electron";
import { spawn, ChildProcess } from "child_process";
import path from "path";
import fs from "fs";
import http from "http";

let pythonProcess: ChildProcess | null = null;

function getProjectRoot(): string {
  // __dirname = frontend/.vite/build/ → 3 levels up → cape-agent/
  return path.join(__dirname, "..", "..", "..");
}

function getBackendDir(): string {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "backend");
  }
  return path.join(getProjectRoot(), "backend");
}

function getPythonCommand(): string {
  const envOverride = process.env.CAPE_AGENT_PYTHON_BIN;
  if (envOverride) {
    return envOverride;
  }

  if (app.isPackaged) {
    const candidates =
      process.platform === "win32"
        ? [
            path.join(process.resourcesPath, "python", "python.exe"),
            path.join(process.resourcesPath, "python", "Scripts", "python.exe"),
          ]
        : [
            path.join(process.resourcesPath, "python", "bin", "python3"),
            path.join(process.resourcesPath, "python", "bin", "python"),
          ];

    const bundledPython = candidates.find((candidate) => fs.existsSync(candidate));
    if (bundledPython) {
      return bundledPython;
    }
  }

  return "python3";
}

function getPortFilePath(): string {
  if (app.isPackaged) {
    return path.join(app.getPath("userData"), ".backend_port");
  }
  return path.join(getProjectRoot(), ".backend_port");
}

function getDatabasePath(): string {
  if (app.isPackaged) {
    return path.join(app.getPath("userData"), "cape_agent.db");
  }
  return path.join(getProjectRoot(), "backend", "cape_agent.db");
}

function readPortFile(): number {
  try {
    const portFile = getPortFilePath();
    const port = parseInt(fs.readFileSync(portFile, "utf-8").trim(), 10);
    if (port > 0) return port;
  } catch {
    // fallback
  }
  return 8001;
}

export function getBackendUrl(): string {
  return `http://127.0.0.1:${readPortFile()}`;
}

export async function startPython(): Promise<void> {
  const backendDir = getBackendDir();
  const portFilePath = getPortFilePath();
  const pythonCommand = getPythonCommand();
  console.log(`Starting Python backend from: ${backendDir}`);
  console.log(`Using Python runtime: ${pythonCommand}`);

  fs.mkdirSync(path.dirname(portFilePath), { recursive: true });
  fs.rmSync(portFilePath, { force: true });

  pythonProcess = spawn(pythonCommand, ["main.py"], {
    cwd: backendDir,
    stdio: ["pipe", "pipe", "pipe"],
    env: {
      ...process.env,
      CAPE_AGENT_DB_PATH: getDatabasePath(),
      CAPE_AGENT_PORT_FILE: portFilePath,
      CAPE_AGENT_RELOAD: "0",
    },
  });

  pythonProcess.stdout?.on("data", (data: Buffer) => {
    console.log(`[backend] ${data.toString().trim()}`);
  });

  pythonProcess.stderr?.on("data", (data: Buffer) => {
    console.log(`[backend:err] ${data.toString().trim()}`);
  });

  pythonProcess.on("exit", (code: number | null) => {
    console.log(`Python backend exited with code ${code}`);
    pythonProcess = null;
  });

  // Wait for backend to be ready
  await waitForHealth();
}

async function waitForHealth(maxRetries = 30, interval = 1000): Promise<void> {
  for (let i = 0; i < maxRetries; i++) {
    try {
      await checkHealth();
      console.log("Backend health check passed");
      return;
    } catch {
      await new Promise((r) => setTimeout(r, interval));
    }
  }
  throw new Error("Backend failed to start");
}

function checkHealth(): Promise<void> {
  return new Promise((resolve, reject) => {
    const req = http.get(`${getBackendUrl()}/health`, (res) => {
      if (res.statusCode === 200) resolve();
      else reject(new Error(`Health check returned ${res.statusCode}`));
    });
    req.on("error", reject);
    req.setTimeout(2000, () => {
      req.destroy();
      reject(new Error("Health check timeout"));
    });
  });
}

export function stopPython(): void {
  if (pythonProcess) {
    console.log("Stopping Python backend...");
    pythonProcess.kill("SIGTERM");
    // Force kill after 5 seconds
    setTimeout(() => {
      if (pythonProcess) {
        pythonProcess.kill("SIGKILL");
        pythonProcess = null;
      }
    }, 5000);
  }
}
