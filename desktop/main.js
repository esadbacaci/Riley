/* Electron ana süreci: Python arka ucunu başlatır, çerçevesiz HUD penceresini açar. */

const { app, BrowserWindow, ipcMain, globalShortcut, Tray, Menu, nativeImage } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const http = require("http");

// Proje kökü: paketlenmiş exe çalışırken __dirname geçici bir klasörü
// gösterir. Portable derlemede PORTABLE_EXECUTABLE_DIR exe'nin gerçek
// bulunduğu klasördür; Riley.exe proje kökünde durduğu için doğru yer orası.
const ROOT =
  process.env.RILEY_ROOT ||
  (app.isPackaged
    ? process.env.PORTABLE_EXECUTABLE_DIR || path.dirname(process.execPath)
    : path.join(__dirname, ".."));
const PORT = Number(process.env.RILEY_PORT || 8756);
const URL = `http://127.0.0.1:${PORT}/`;

let win = null;
let tray = null;
let backend = null;
let quitting = false;

// "--tray" ile başlatıldığında (Windows açılışı) pencere açılmaz,
// Riley sessizce tepsiye yerleşir ve kısayolla çağrılmayı bekler.
const tepsideBasla = process.argv.includes("--tray");
const IKON = path.join(__dirname, "..", "build", "icon.ico");

/* ------------------------------------------------------------ arka uç -- */

function startBackend() {
  if (process.env.RILEY_NO_BACKEND === "1") {
    console.log("[riley] arka uç dışarıdan yönetiliyor, başlatılmıyor.");
    return;
  }

  const python = process.env.RILEY_PYTHON || "python";
  const giris = path.join(ROOT, "backend", "main.py");
  if (!require("fs").existsSync(giris)) {
    console.error("[riley] backend/main.py bulunamadı:", giris);
    return;
  }
  backend = spawn(python, [giris], {
    cwd: ROOT,
    env: { ...process.env, PYTHONIOENCODING: "utf-8", RILEY_PORT: String(PORT) },
    windowsHide: true,
  });

  backend.stdout.on("data", (d) => process.stdout.write("[py] " + d));
  backend.stderr.on("data", (d) => process.stderr.write("[py] " + d));
  backend.on("exit", (code) => {
    console.log("[riley] arka uç kapandı, kod:", code);
    backend = null;
    if (!quitting && win) {
      win.webContents.executeJavaScript(
        "document.getElementById('connTag').textContent='SUNUCU KAPANDI';"
      ).catch(() => {});
    }
  });
}

function stopBackend() {
  if (!backend) return;
  try {
    // Alt süreçleriyle birlikte kapat
    spawn("taskkill", ["/pid", String(backend.pid), "/f", "/t"], { windowsHide: true });
  } catch (err) {
    backend.kill();
  }
  backend = null;
}

/* Sunucu ayağa kalkana kadar bekle (en fazla ~30 sn). */
function waitForServer(attempt = 0) {
  return new Promise((resolve) => {
    const tryOnce = (n) => {
      const req = http.get(`${URL}api/health`, (res) => {
        res.resume();
        resolve(true);
      });
      req.on("error", () => {
        if (n > 150) return resolve(false);
        setTimeout(() => tryOnce(n + 1), 200);
      });
      req.setTimeout(1500, () => req.destroy());
    };
    tryOnce(attempt);
  });
}

/* -------------------------------------------------------------- pencere -- */

function createWindow() {
  win = new BrowserWindow({
    width: 1180,
    height: 760,
    minWidth: 720,
    minHeight: 520,
    frame: false,
    backgroundColor: "#04070d",
    show: false,
    title: "Riley",
    icon: require("fs").existsSync(IKON) ? IKON : undefined,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      // Atmosfer sesi açılışta kendiliğinden başlayabilsin
      autoplayPolicy: "no-user-gesture-required",
    },
  });

  win.once("ready-to-show", () => {
    if (!tepsideBasla) win.show();
  });

  win.on("close", (event) => {
    // Kapatma düğmesi pencereyi tepsiye gizler; çıkış tepsi menüsünden
    if (!quitting) {
      event.preventDefault();
      win.hide();
    }
  });

  win.loadURL(URL);
}

function createTray() {
  if (tray) { tray.destroy(); tray = null; }
  const icon = require("fs").existsSync(IKON)
    ? nativeImage.createFromPath(IKON)
    : nativeImage.createEmpty();
  tray = new Tray(icon);
  tray.setToolTip("Riley");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "Riley'yi göster", click: () => win && win.show() },
      { label: "Dinlemeyi başlat", click: () => win && win.webContents.send("trigger-listen") },
      { type: "separator" },
      {
        label: "Windows ile başlat",
        type: "checkbox",
        checked: app.getLoginItemSettings().openAtLogin,
        click: (menu) => {
          app.setLoginItemSettings({
            openAtLogin: menu.checked,
            args: ["--tray"],
          });
          createTray();          // menüyü yeni duruma göre yeniden kur
        },
      },
      { type: "separator" },
      { label: "Çıkış", click: () => { quitting = true; app.quit(); } },
    ])
  );
  tray.on("double-click", () => win && (win.isVisible() ? win.hide() : win.show()));
}

/* ------------------------------------------------------------ IPC köprü -- */

ipcMain.on("window:minimize", () => win && win.minimize());
ipcMain.on("window:toggle-maximize", () => {
  if (!win) return;
  win.isMaximized() ? win.unmaximize() : win.maximize();
});
ipcMain.on("window:close", () => win && win.hide());

// Ayarlardan gelen yeniden başlatma isteği: arka ucu kapatıp yeniden açar.
// Arayüz zaten bağlantı kopunca kendiliğinden yeniden bağlanıyor.
ipcMain.handle("backend:restart", async () => {
  if (process.env.RILEY_NO_BACKEND === "1") return { ok: false, reason: "harici" };
  console.log("[riley] arka uç yeniden başlatılıyor");
  stopBackend();
  await new Promise((r) => setTimeout(r, 1500));
  startBackend();
  return { ok: true };
});

/* ------------------------------------------------------------- yaşam --- */

const single = app.requestSingleInstanceLock();
if (!single) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (win) { win.show(); win.focus(); }
  });

  app.whenReady().then(async () => {
    startBackend();
    createWindow();
    createTray();

    const ok = await waitForServer();
    if (!ok) console.error("[riley] sunucuya ulaşılamadı:", URL);

    // Pencere gizliyken de çalışan global kısayol
    globalShortcut.register("Control+Alt+R", () => {
      if (!win) return;
      win.show();
      win.focus();
    });
  });

  app.on("window-all-closed", () => {});   // tepside kalmaya devam et
  app.on("before-quit", () => { quitting = true; stopBackend(); });
  app.on("will-quit", () => globalShortcut.unregisterAll());
}
