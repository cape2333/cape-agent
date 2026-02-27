"use strict";
const electron = require("electron");
const path = require("path");
const child_process = require("child_process");
const http = require("http");
let pythonProcess = null;
const BACKEND_PORT = 8001;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
function getBackendDir() {
  return path.join(__dirname, "..", "..", "..", "..", "backend");
}
function getBackendUrl() {
  return BACKEND_URL;
}
async function startPython() {
  var _a, _b;
  const backendDir = getBackendDir();
  console.log(`Starting Python backend from: ${backendDir}`);
  pythonProcess = child_process.spawn("python3", ["main.py"], {
    cwd: backendDir,
    stdio: ["pipe", "pipe", "pipe"],
    env: { ...process.env }
  });
  (_a = pythonProcess.stdout) == null ? void 0 : _a.on("data", (data) => {
    console.log(`[backend] ${data.toString().trim()}`);
  });
  (_b = pythonProcess.stderr) == null ? void 0 : _b.on("data", (data) => {
    console.log(`[backend:err] ${data.toString().trim()}`);
  });
  pythonProcess.on("exit", (code) => {
    console.log(`Python backend exited with code ${code}`);
    pythonProcess = null;
  });
  await waitForHealth();
}
async function waitForHealth(maxRetries = 30, interval = 1e3) {
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
function checkHealth() {
  return new Promise((resolve, reject) => {
    const req = http.get(`${BACKEND_URL}/health`, (res) => {
      if (res.statusCode === 200) resolve();
      else reject(new Error(`Health check returned ${res.statusCode}`));
    });
    req.on("error", reject);
    req.setTimeout(2e3, () => {
      req.destroy();
      reject(new Error("Health check timeout"));
    });
  });
}
function stopPython() {
  if (pythonProcess) {
    console.log("Stopping Python backend...");
    pythonProcess.kill("SIGTERM");
    setTimeout(() => {
      if (pythonProcess) {
        pythonProcess.kill("SIGKILL");
        pythonProcess = null;
      }
    }, 5e3);
  }
}
const createWindow = () => {
  const mainWindow = new electron.BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    },
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 16, y: 16 },
    roundedCorners: true
  });
  {
    mainWindow.loadURL("http://localhost:5175");
  }
};
electron.ipcMain.handle("get-backend-url", () => getBackendUrl());
electron.app.on("ready", async () => {
  try {
    await startPython();
  } catch (e) {
    console.error("Failed to start Python backend:", e);
  }
  createWindow();
});
electron.app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    electron.app.quit();
  }
});
electron.app.on("activate", () => {
  if (electron.BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});
electron.app.on("will-quit", () => {
  stopPython();
});
