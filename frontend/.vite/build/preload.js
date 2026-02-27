"use strict";
const electron = require("electron");
electron.contextBridge.exposeInMainWorld("electronAPI", {
  getBackendUrl: () => electron.ipcRenderer.invoke("get-backend-url")
});
