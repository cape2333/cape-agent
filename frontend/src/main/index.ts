import { app, BaseWindow, ipcMain, WebContentsView } from "electron";
import path from "path";
import { startPython, stopPython, getBackendUrl } from "./python-manager";

declare const MAIN_WINDOW_VITE_DEV_SERVER_URL: string | undefined;
declare const MAIN_WINDOW_VITE_NAME: string;

// ─── Window Creation ────────────────────────────────────────────────────────

let mainWindow: BaseWindow | null = null;
let mainContentView: WebContentsView | null = null;

const createWindow = () => {
  console.log("Creating main window (BaseWindow)...");

  mainWindow = new BaseWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    show: false,
    icon: path.join(__dirname, "../../src/resources/icon.png"),
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 16, y: 16 },
    roundedCorners: true,
  });

  // Create the main content view (renders the React app)
  mainContentView = new WebContentsView({
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Add main view to the window and size it to fill
  mainWindow.contentView.addChildView(mainContentView);
  const { width, height } = mainWindow.getContentBounds();
  mainContentView.setBounds({ x: 0, y: 0, width, height });

  // Resize main view when window resizes
  mainWindow.on("resize", () => {
    if (!mainWindow || !mainContentView) return;
    const { width, height } = mainWindow.getContentBounds();
    mainContentView.setBounds({ x: 0, y: 0, width, height });
  });

  // Show window when content is ready
  mainContentView.webContents.once("did-finish-load", () => {
    console.log("Main content loaded, showing window");
    mainWindow!.show();
    mainWindow!.focus();
  });

  // Safety fallback: show window after 5s
  setTimeout(() => {
    if (mainWindow && !mainWindow.isVisible()) {
      console.log("Fallback: showing window after timeout");
      mainWindow.show();
      mainWindow.focus();
    }
  }, 5000);

  // Load the React app
  if (MAIN_WINDOW_VITE_DEV_SERVER_URL) {
    console.log("Loading dev server URL:", MAIN_WINDOW_VITE_DEV_SERVER_URL);
    mainContentView.webContents.loadURL(MAIN_WINDOW_VITE_DEV_SERVER_URL);
    mainContentView.webContents.openDevTools({ mode: "detach" });
  } else {
    const indexPath = path.join(__dirname, `../renderer/${MAIN_WINDOW_VITE_NAME}/index.html`);
    console.log("Loading file:", indexPath);
    mainContentView.webContents.loadFile(indexPath);
  }

  mainContentView.webContents.on("did-fail-load", (_event, errorCode, errorDescription) => {
    console.error("Failed to load:", errorCode, errorDescription);
  });
};

// ─── IPC Handlers ───────────────────────────────────────────────────────────

ipcMain.handle("get-backend-url", () => getBackendUrl());

// ─── App Lifecycle ──────────────────────────────────────────────────────────

app.on("ready", async () => {
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
  if (BaseWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

app.on("will-quit", () => {
  stopPython();
});
