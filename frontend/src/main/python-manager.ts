import { spawn, ChildProcess } from "child_process";
import path from "path";
import http from "http";

let pythonProcess: ChildProcess | null = null;
const BACKEND_PORT = 8001;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;

function getBackendDir(): string {
  // In development, backend is a sibling directory
  return path.join(__dirname, "..", "..", "..", "..", "backend");
}

export function getBackendUrl(): string {
  return BACKEND_URL;
}

export async function startPython(): Promise<void> {
  const backendDir = getBackendDir();
  console.log(`Starting Python backend from: ${backendDir}`);

  pythonProcess = spawn("python3", ["main.py"], {
    cwd: backendDir,
    stdio: ["pipe", "pipe", "pipe"],
    env: { ...process.env },
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
    const req = http.get(`${BACKEND_URL}/health`, (res) => {
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
