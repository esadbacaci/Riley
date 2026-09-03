/* Yalıtılmış köprü: arayüze sadece pencere denetimlerini açar. */
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("rileyWindow", {
  minimize: () => ipcRenderer.send("window:minimize"),
  toggleMaximize: () => ipcRenderer.send("window:toggle-maximize"),
  close: () => ipcRenderer.send("window:close"),
  onTriggerListen: (cb) => ipcRenderer.on("trigger-listen", cb),
});

contextBridge.exposeInMainWorld("RILEY_PORT", Number(process.env.RILEY_PORT || 8756));
