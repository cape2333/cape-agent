"use strict";
const electron = require("electron");
const path = require("path");
require("child_process");
const fs = require("fs");
require("http");
function getProjectRoot() {
  return path.join(__dirname, "..", "..", "..", "..");
}
function readPortFile() {
  try {
    const portFile = path.join(getProjectRoot(), ".backend_port");
    const port = parseInt(fs.readFileSync(portFile, "utf-8").trim(), 10);
    if (port > 0) return port;
  } catch {
  }
  return 8001;
}
function getBackendUrl() {
  return `http://127.0.0.1:${readPortFile()}`;
}
const createWindow = () => {
  console.log("Creating main window...");
  const mainWindow = new electron.BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    show: false,
    // Don't show until ready
    icon: path.join(__dirname, "../../src/resources/icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    },
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 16, y: 16 },
    roundedCorners: true
  });
  mainWindow.once("ready-to-show", () => {
    console.log("Window ready to show");
    mainWindow.show();
    mainWindow.focus();
  });
  setTimeout(() => {
    if (!mainWindow.isVisible()) {
      console.log("Fallback: showing window after timeout");
      mainWindow.show();
      mainWindow.focus();
    }
  }, 5e3);
  {
    console.log("Loading dev server URL:", "http://localhost:5173");
    mainWindow.loadURL("http://localhost:5173");
    mainWindow.webContents.openDevTools();
  }
  mainWindow.webContents.on("did-fail-load", (_event, errorCode, errorDescription) => {
    console.error("Failed to load:", errorCode, errorDescription);
  });
};
electron.ipcMain.handle("get-backend-url", () => getBackendUrl());
electron.app.on("ready", async () => {
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
});
