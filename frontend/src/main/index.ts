import { app, BrowserWindow, ipcMain } from "electron";
import path from "path";
import { startPython, stopPython, getBackendUrl } from "./python-manager";

declare const MAIN_WINDOW_VITE_DEV_SERVER_URL: string | undefined;
declare const MAIN_WINDOW_VITE_NAME: string;

const createWindow = () => {
  console.log("Creating main window...");

  const mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    show: false, // Don't show until ready
    icon: path.join(__dirname, "../../src/resources/icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 16, y: 16 },
    roundedCorners: true,
  });

  // Show window when ready to prevent visual flash
  mainWindow.once("ready-to-show", () => {
    console.log("Window ready to show");
    mainWindow.show();
    mainWindow.focus();
  });

  // Safety fallback: show window after 5s even if ready-to-show doesn't fire
  setTimeout(() => {
    if (!mainWindow.isVisible()) {
      console.log("Fallback: showing window after timeout");
      mainWindow.show();
      mainWindow.focus();
    }
  }, 5000);

  // Open DevTools in development
  if (MAIN_WINDOW_VITE_DEV_SERVER_URL) {
    console.log("Loading dev server URL:", MAIN_WINDOW_VITE_DEV_SERVER_URL);
    mainWindow.loadURL(MAIN_WINDOW_VITE_DEV_SERVER_URL);
    mainWindow.webContents.openDevTools();
  } else {
    const indexPath = path.join(__dirname, `../renderer/${MAIN_WINDOW_VITE_NAME}/index.html`);
    console.log("Loading file:", indexPath);
    mainWindow.loadFile(indexPath);
  }

  mainWindow.webContents.on("did-fail-load", (_event, errorCode, errorDescription) => {
    console.error("Failed to load:", errorCode, errorDescription);
  });
};

// IPC handlers
ipcMain.handle("get-backend-url", () => getBackendUrl());

app.on("ready", async () => {
  // In development mode, backend is started by dev.sh script
  // Only start Python if we're in production (packaged app)
  if (!MAIN_WINDOW_VITE_DEV_SERVER_URL) {
    try {
      await startPython();
    } catch (e) {
      console.error("Failed to start Python backend:", e);
    }
  }
  createWindow();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

app.on("will-quit", () => {
  stopPython();
});
