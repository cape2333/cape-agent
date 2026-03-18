import { app, BaseWindow, ipcMain, WebContentsView } from "electron";
import path from "path";
import http from "http";
import net from "net";
import { startPython, stopPython, getBackendUrl } from "./python-manager";

declare const MAIN_WINDOW_VITE_DEV_SERVER_URL: string | undefined;
declare const MAIN_WINDOW_VITE_NAME: string;

let CDP_PORT = 9222;

// Find an available port for CDP (async, must resolve before app.ready)
function findAvailablePort(startPort: number): Promise<number> {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.listen(startPort, "127.0.0.1", () => {
      server.close(() => resolve(startPort));
    });
    server.on("error", () => {
      resolve(findAvailablePort(startPort + 1));
    });
  });
}

const cdpPortReady = findAvailablePort(9222).then((port) => {
  CDP_PORT = port;
  app.commandLine.appendSwitch("remote-debugging-port", String(port));
  console.log(`[CDP] Using port ${port} for remote debugging`);
});

// ─── Browser Panel Manager ──────────────────────────────────────────────────
// Uses BaseWindow (not BrowserWindow) so that win.contentView is a plain View
// without Chromium's internal FlexLayout — this prevents child WebContentsViews
// from being auto-resized to fill the parent after navigation events.

class BrowserPanelManager {
  private win: BaseWindow | null = null;
  private mainView: WebContentsView | null = null;
  private browserView: WebContentsView | null = null;
  private visible = false;
  private sidebarWidth = 268;
  private browserRatio: number | null = null;
  private boundsInterval: ReturnType<typeof setInterval> | null = null;

  setup(win: BaseWindow, mainView: WebContentsView) {
    this.win = win;
    this.mainView = mainView;
  }

  setSidebarWidth(width: number) {
    this.sidebarWidth = width;
    this.updateLayout();
  }

  setBrowserPanelRatio(ratio: number) {
    this.browserRatio = ratio;
    this.updateLayout();
  }

  async create(): Promise<{ success: boolean; cdpTargetUrl?: string }> {
    if (!this.win) return { success: false };

    // Remove old browser view if exists
    if (this.browserView) {
      if (this.visible) {
        this.win.contentView.removeChildView(this.browserView);
        this.visible = false;
      }
      this.browserView.webContents.close();
      this.browserView = null;
    }

    this.browserView = new WebContentsView({
      webPreferences: {
        contextIsolation: true,
        nodeIntegration: false,
      },
    });

    // Ensure every page respects the panel width as its viewport
    this.browserView.webContents.on("did-finish-load", () => {
      this.injectViewportMeta();
    });

    // Temporarily attach to load the marker URL (needed for CDP target discovery)
    this.win.contentView.addChildView(this.browserView);
    this.browserView.setBounds({ x: 0, y: 0, width: 0, height: 0 });

    await this.browserView.webContents.loadURL("about:blank#cape-agent-browser");

    // Discover CDP target
    const cdpTargetUrl = await this.discoverCdpTarget();

    // Detach — starts hidden, show() will re-attach
    this.win.contentView.removeChildView(this.browserView);

    return { success: true, cdpTargetUrl: cdpTargetUrl || undefined };
  }

  show(sidebarWidth?: number, browserPanelRatio?: number) {
    if (!this.browserView || !this.win) return;
    if (sidebarWidth !== undefined) this.sidebarWidth = sidebarWidth;
    if (browserPanelRatio !== undefined) this.browserRatio = browserPanelRatio;
    if (!this.visible) {
      this.win.contentView.addChildView(this.browserView);
      this.visible = true;
    }
    this.updateLayout();
    this.startBoundsEnforcement();

    // Navigate to Google on first show (when still on the blank marker page)
    const currentUrl = this.browserView.webContents.getURL();
    if (!currentUrl || currentUrl.includes("about:blank")) {
      this.browserView.webContents.loadURL("https://www.google.com");
    }
  }

  hide() {
    this.stopBoundsEnforcement();
    if (!this.browserView || !this.win) return;
    if (this.visible) {
      this.win.contentView.removeChildView(this.browserView);
      this.visible = false;
    }
    // Restore main view to full width
    this.updateLayout();
  }

  navigate(url: string) {
    if (!this.browserView) return;
    this.browserView.webContents.loadURL(url);
  }

  resize() {
    this.updateLayout();
  }

  isVisible() {
    return this.visible;
  }

  getCurrentUrl(): string {
    return this.browserView?.webContents.getURL() || "";
  }

  destroy() {
    this.stopBoundsEnforcement();
    if (this.browserView && this.win) {
      if (this.visible) {
        this.win.contentView.removeChildView(this.browserView);
      }
      this.browserView.webContents.close();
      this.browserView = null;
      this.visible = false;
    }
  }

  /** Layout both the main content view and browser view */
  private updateLayout() {
    if (!this.win || !this.mainView) return;
    const { width, height } = this.win.getContentBounds();
    if (width <= 0 || height <= 0) return;

    if (this.visible && this.browserView) {
      // Split: main content on left, browser on right
      const panelWidth = this.getBrowserPanelWidth();
      const mainWidth = width - panelWidth;
      this.mainView.setBounds({ x: 0, y: 0, width: mainWidth, height });
      this.browserView.setBounds({ x: mainWidth, y: 0, width: panelWidth, height });
    } else {
      // Main content fills the entire window
      this.mainView.setBounds({ x: 0, y: 0, width, height });
    }
  }

  private getBrowserPanelWidth(): number {
    if (!this.win) return 400;
    const { width } = this.win.getContentBounds();
    const contentArea = Math.max(100, width - this.sidebarWidth);
    if (this.browserRatio !== null) {
      const panelWidth = Math.floor(contentArea * this.browserRatio);
      const minPanelWidth = 200;
      const maxPanelWidth = width - 300;
      return Math.max(minPanelWidth, Math.min(panelWidth, maxPanelWidth));
    }
    return Math.floor(contentArea / 2);
  }

  /** Inject/override viewport meta tag so the page uses device-width */
  private injectViewportMeta() {
    if (!this.browserView) return;
    this.browserView.webContents.executeJavaScript(`
      (function() {
        let meta = document.querySelector('meta[name="viewport"]');
        if (!meta) {
          meta = document.createElement('meta');
          meta.name = 'viewport';
          document.head.appendChild(meta);
        }
        meta.content = 'width=device-width, initial-scale=1';
      })();
    `).catch(() => {});
  }

  private getExpectedBrowserBounds() {
    if (!this.win) return null;
    const { width, height } = this.win.getContentBounds();
    if (width <= 0 || height <= 0) return null;
    const panelWidth = this.getBrowserPanelWidth();
    const mainWidth = width - panelWidth;
    return {
      x: mainWidth,
      y: 0,
      width: panelWidth,
      height,
    };
  }

  /** Periodically check and correct browser view bounds (safety net) */
  private startBoundsEnforcement() {
    this.stopBoundsEnforcement();
    this.boundsInterval = setInterval(() => {
      if (!this.visible || !this.browserView || !this.win) return;
      const expected = this.getExpectedBrowserBounds();
      if (!expected) return;
      const actual = this.browserView.getBounds();
      if (actual.x !== expected.x || actual.y !== expected.y ||
          actual.width !== expected.width || actual.height !== expected.height) {
        console.log("[BrowserPanel] Bounds drifted, correcting");
        this.browserView.setBounds(expected);
      }
    }, 200);
  }

  private stopBoundsEnforcement() {
    if (this.boundsInterval) {
      clearInterval(this.boundsInterval);
      this.boundsInterval = null;
    }
  }

  private async discoverCdpTarget(): Promise<string | null> {
    await new Promise((r) => setTimeout(r, 500));

    return new Promise((resolve) => {
      const req = http.get(`http://127.0.0.1:${CDP_PORT}/json`, (res) => {
        let data = "";
        res.on("data", (chunk: Buffer) => { data += chunk.toString(); });
        res.on("end", () => {
          try {
            const targets = JSON.parse(data);
            const target = targets.find(
              (t: { url?: string }) => t.url && t.url.includes("cape-agent-browser")
            );
            if (target?.webSocketDebuggerUrl) {
              console.log("[CDP] Found browser panel target:", target.webSocketDebuggerUrl);
              resolve(target.webSocketDebuggerUrl);
            } else {
              console.warn("[CDP] Could not find browser panel target in", targets.length, "targets");
              resolve(null);
            }
          } catch (e) {
            console.error("[CDP] Failed to parse targets:", e);
            resolve(null);
          }
        });
      });
      req.on("error", (e) => {
        console.error("[CDP] Failed to fetch targets:", e);
        resolve(null);
      });
      req.setTimeout(3000, () => {
        req.destroy();
        resolve(null);
      });
    });
  }
}

const browserPanel = new BrowserPanelManager();

// ─── Window Creation ────────────────────────────────────────────────────────
// Uses BaseWindow instead of BrowserWindow for full control over the view
// hierarchy. BaseWindow.contentView is a plain View (no Chromium FlexLayout),
// so child WebContentsViews respect setBounds reliably.

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

  // Set up browser panel manager
  browserPanel.setup(mainWindow, mainContentView);

  // Resize all views when window resizes
  mainWindow.on("resize", () => {
    browserPanel.resize();
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

  // Auto-create browser panel on startup (hidden, for CDP readiness)
  mainContentView.webContents.on("did-finish-load", async () => {
    console.log("Auto-creating browser panel (hidden) for CDP...");
    try {
      const result = await browserPanel.create();
      if (result.success) {
        console.log("[Auto] Browser panel created, CDP target:", result.cdpTargetUrl);
      } else {
        console.warn("[Auto] Failed to auto-create browser panel");
      }
    } catch (e) {
      console.error("[Auto] Error creating browser panel:", e);
    }
  });
};

// ─── IPC Handlers ───────────────────────────────────────────────────────────

ipcMain.handle("get-backend-url", () => getBackendUrl());

ipcMain.handle("browser-panel:create", async () => {
  return browserPanel.create();
});

ipcMain.handle("browser-panel:show", (_event, sidebarWidth?: number, browserPanelRatio?: number) => {
  browserPanel.show(sidebarWidth, browserPanelRatio);
  return { success: true };
});

ipcMain.handle("browser-panel:hide", () => {
  browserPanel.hide();
  return { success: true };
});

ipcMain.handle("browser-panel:navigate", (_event, url: string) => {
  browserPanel.navigate(url);
  return { success: true };
});

ipcMain.handle("browser-panel:resize", (_event, sidebarWidth?: number, browserPanelRatio?: number) => {
  if (sidebarWidth !== undefined) browserPanel.setSidebarWidth(sidebarWidth);
  if (browserPanelRatio !== undefined) browserPanel.setBrowserPanelRatio(browserPanelRatio);
  else browserPanel.resize();
  return { success: true };
});

ipcMain.handle("browser-panel:get-info", () => {
  return {
    visible: browserPanel.isVisible(),
    currentUrl: browserPanel.getCurrentUrl(),
    cdpPort: CDP_PORT,
  };
});

ipcMain.handle("browser-panel:destroy", () => {
  browserPanel.destroy();
  return { success: true };
});

// ─── App Lifecycle ──────────────────────────────────────────────────────────

app.on("ready", async () => {
  await cdpPortReady;

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
  browserPanel.destroy();
  stopPython();
});
