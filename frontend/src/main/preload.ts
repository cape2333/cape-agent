import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("electronAPI", {
  getBackendUrl: () => ipcRenderer.invoke("get-backend-url"),
  browserPanel: {
    create: () => ipcRenderer.invoke("browser-panel:create"),
    show: (sidebarWidth?: number, browserPanelRatio?: number) => ipcRenderer.invoke("browser-panel:show", sidebarWidth, browserPanelRatio),
    hide: () => ipcRenderer.invoke("browser-panel:hide"),
    navigate: (url: string) => ipcRenderer.invoke("browser-panel:navigate", url),
    resize: (sidebarWidth?: number, browserPanelRatio?: number) => ipcRenderer.invoke("browser-panel:resize", sidebarWidth, browserPanelRatio),
    getInfo: () => ipcRenderer.invoke("browser-panel:get-info"),
    destroy: () => ipcRenderer.invoke("browser-panel:destroy"),
  },
});
