/* Arayüz mantığı: sunucuya bağlan, olayları ekrana yansıt, komut gönder. */

(function () {
  "use strict";

  const PORT = window.RILEY_PORT || 8756;
  const API = `http://127.0.0.1:${PORT}`;
  const WS_URL = `ws://127.0.0.1:${PORT}/ws`;

  const $ = (id) => document.getElementById(id);
  const el = {
    conn: $("connTag"), model: $("modelTag"), clock: $("clock"),
    state: $("statePill"), you: $("youLine"), me: $("meLine"),
    feed: $("feed"), chat: $("chat"), skills: $("skills"),
    input: $("input"), listen: $("btnListen"),
    confirm: $("confirmBox"), confirmQ: $("confirmQ"),
    cpuVal: $("cpuVal"), cpuBar: $("cpuBar"),
    ramVal: $("ramVal"), ramBar: $("ramBar"),
    gpuVal: $("gpuVal"), gpuBar: $("gpuBar"),
    hotkey: $("hotkeyHint"), wakeHint: $("wakeHint"),
    drawer: $("drawer"), not: $("ayarNot"), memlist: $("memlist"),
  };

  const STATE_LABEL = {
    booting: "BAŞLATILIYOR", idle: "HAZIR", listening: "DİNLİYOR",
    thinking: "DÜŞÜNÜYOR", acting: "ÇALIŞIYOR", speaking: "KONUŞUYOR",
    error: "HATA",
  };

  const reactor = new window.Reactor($("reactor"));
  const sesler = new window.RileyAudio();
  let socket = null;
  let retryDelay = 700;
  let replyBuffer = "";
  let sonSoru = "";
  let beceriler = [];

  /* ---------------------------------------------------------- yardımcılar */

  function stamp() {
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }

  function log(message, kind) {
    const row = document.createElement("div");
    row.className = "row" + (kind ? " " + kind : "");
    row.innerHTML = `<span class="t">${stamp()}</span><span class="m"></span>`;
    row.querySelector(".m").textContent = message;
    el.feed.appendChild(row);

    while (el.feed.children.length > 220) el.feed.removeChild(el.feed.firstChild);
    el.feed.scrollTop = el.feed.scrollHeight;
  }

  /* Sohbet dökümüne bir tur ekler; sekme kapalıyken de birikir. */
  function sohbeteEkle(kim, metin) {
    const bos = el.chat.querySelector(".empty");
    if (bos) bos.remove();

    const turn = document.createElement("div");
    turn.className = "turn" + (kim === "riley" ? " me" : "");
    turn.innerHTML = `<div class="who"></div><div class="what"></div>`;
    turn.querySelector(".who").textContent = kim === "riley" ? "RILEY" : "SEN";
    turn.querySelector(".what").textContent = metin;
    el.chat.appendChild(turn);

    while (el.chat.children.length > 120) el.chat.removeChild(el.chat.firstChild);
    el.chat.scrollTop = el.chat.scrollHeight;
  }

  let oncekiDurum = "booting";

  function setState(value) {
    // Durum geçişlerine göre kısa ses işaretleri
    if (value !== oncekiDurum) {
      const mesguldu = ["listening", "thinking", "acting", "speaking"]
        .includes(oncekiDurum);
      if (value === "listening" && oncekiDurum !== "listening") {
        sesler.dinliyor();
      } else if (value === "idle" && mesguldu) {
        sesler.uyku();          // işini bitirdi, beklemeye döndü
      }
      oncekiDurum = value;
    }

    document.body.dataset.state = value;
    el.state.textContent = STATE_LABEL[value] || value.toUpperCase();
    reactor.setState(value);
    sesler.durum(value);
    el.listen.classList.toggle("live", value === "listening");
    el.me.classList.toggle("typing", value === "thinking" || value === "speaking");
  }

  function setGauge(barEl, valEl, percent, text) {
    const p = Math.max(0, Math.min(100, percent || 0));
    barEl.style.width = p + "%";
    barEl.classList.toggle("hot", p >= 85);
    valEl.textContent = text !== undefined ? text : Math.round(p) + "%";
  }

  function markSystem(step, status, detail) {
    const li = document.querySelector(`.syslist li[data-step="${step}"]`);
    if (!li) return;
    li.className = status;
    const label = { start: "yükleniyor", ok: "hazır", warn: "uyarı", error: "hata" };
    li.querySelector("b").textContent = label[status] || status;
    if (detail) li.title = detail;
  }

  /* ------------------------------------------------------------- bağlantı */

  function connect() {
    socket = new WebSocket(WS_URL);

    socket.onopen = () => {
      const ilkBaglanti = !sesler.started;
      retryDelay = 700;
      el.conn.textContent = "ÇEVRİMİÇİ";
      el.conn.className = "tag on";
      log("Sunucuya bağlanıldı.", "ok");
      sesler.baslat();
      if (ilkBaglanti) sesler.acilis();
      becerileriYukle();
      ayarlariYukle();
    };

    socket.onclose = () => {
      el.conn.textContent = "BAĞLANTI YOK";
      el.conn.className = "tag off";
      setState("error");
      setTimeout(connect, retryDelay);
      retryDelay = Math.min(retryDelay * 1.6, 6000);
    };

    socket.onerror = () => socket.close();
    socket.onmessage = (event) => {
      let data;
      try { data = JSON.parse(event.data); } catch { return; }
      handle(data);
    };
  }

  function send(payload) {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload));
    }
  }

  /* ---------------------------------------------------------- olay işleme */

  function handle(ev) {
    switch (ev.type) {
      case "hello":
        el.model.textContent = "model: " + (ev.model || "—");
        if (ev.hotkey) el.hotkey.textContent = prettyHotkey(ev.hotkey);
        if (ev.persona) {
          $("brandMark").textContent = ev.persona;
          el.wakeHint.textContent = `veya "${ev.persona}, ..." diye seslen`;
        }
        setState(ev.state || "booting");
        break;

      case "state":
        setState(ev.value);
        break;

      case "audio.level":
        reactor.setLevel(ev.value);
        break;

      case "system.stats":
        setGauge(el.cpuBar, el.cpuVal, ev.cpu);
        setGauge(el.ramBar, el.ramVal, ev.ram,
          `${Math.round(ev.ram)}%  ${ev.ram_used}/${ev.ram_total} GB`);
        if (ev.gpu_text !== undefined) updateGpu(ev.gpu_text);
        break;

      case "boot.step":
        markSystem(ev.step, ev.status, ev.detail);
        if (ev.detail && ev.status !== "start") {
          log(`${ev.step.toUpperCase()}: ${ev.detail}`,
              ev.status === "ok" ? "ok" : ev.status);
        }
        break;

      case "boot.done":
        log(`Tüm sistemler hazır. ${ev.skills} beceri etkin.`, "ok");
        sesler.onay();
        break;

      case "wake":
        log(ev.barge_in ? "Söz kesildi, dinliyorum." : "Uyandırıldı.", "wake");
        sesler.uyandi();
        break;

      case "transcript":
      case "user.said":
        el.you.textContent = ev.text;
        el.me.textContent = "";
        replyBuffer = "";
        sonSoru = ev.text;
        log("sen: " + ev.text);
        sohbeteEkle("sen", ev.text);
        break;

      case "reply.delta":
        replyBuffer += ev.text;
        el.me.textContent = replyBuffer;
        el.me.scrollTop = el.me.scrollHeight;
        break;

      case "reply.done":
        if (ev.text) {
          replyBuffer = ev.text;
          el.me.textContent = ev.text;
          log("riley: " + ev.text, ev.error ? "error" : "");
          sohbeteEkle("riley", ev.text);
          if (ev.error) sesler.hata();
        }
        if (ev.timing) {
          const t = ev.timing;
          log(
            `⏱ ilk kelime ${(t.ilk_belirtec_ms / 1000).toFixed(1)} sn · ` +
            `konuşma ${(t.ilk_konusma_ms / 1000).toFixed(1)} sn · ` +
            `toplam ${(t.toplam_ms / 1000).toFixed(1)} sn` +
            (t.arac_sayisi ? ` · ${t.arac_sayisi} araç` : ""),
            "timing"
          );
        }
        break;

      case "tool.start":
        log(`⟩ ${ev.name}(${fmtArgs(ev.args)})`, "tool");
        sesler.arac();
        break;

      case "tool.end":
        log(`  ${ev.ok ? "✓" : "✕"} ${ev.name}: ${trim(ev.result, 160)}`,
            ev.ok ? "ok" : "error");
        break;

      case "confirm.request":
        el.confirmQ.textContent = ev.question;
        el.confirm.hidden = false;
        log("Onay bekleniyor: " + ev.tool, "warn");
        sesler.uyandi();
        break;

      case "confirm.result":
        el.confirm.hidden = true;
        log(ev.approved ? "Onaylandı." : "Reddedildi.", ev.approved ? "ok" : "warn");
        break;

      case "speech.start":
        reactor.setState("speaking");
        break;

      case "timer.fired":
        log("⏰ Hatırlatma: " + ev.label, "warn");
        break;

      case "log":
        log(ev.text, ev.level === "info" ? "" : ev.level);
        break;
    }
  }

  function updateGpu(text) {
    if (!text) { setGauge(el.gpuBar, el.gpuVal, 0, "yok"); return; }
    const util = /%(\d+)/.exec(text);
    const mem = /\((\d+)\/(\d+) MB/.exec(text);
    const percent = util ? parseInt(util[1], 10) : 0;
    const label = mem
      ? `${percent}%  ${(mem[1] / 1024).toFixed(1)}/${(mem[2] / 1024).toFixed(1)} GB`
      : percent + "%";
    setGauge(el.gpuBar, el.gpuVal, percent, label);
  }

  function fmtArgs(args) {
    if (!args) return "";
    return Object.entries(args)
      .map(([k, v]) => `${k}=${trim(String(v), 40)}`)
      .join(", ");
  }

  function trim(text, max) {
    const s = String(text ?? "");
    return s.length > max ? s.slice(0, max) + "…" : s;
  }

  function prettyHotkey(raw) {
    return raw.replace(/[<>]/g, "").split("+")
      .map((k) => k.trim().replace(/^./, (c) => c.toUpperCase()))
      .join(" + ");
  }

  /* ------------------------------------------------------------- sekmeler */

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".tabpane").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      $("pane-" + tab.dataset.tab).classList.add("active");
      sesler.arac();
    });
  });

  /* ------------------------------------------------------------ beceriler */

  async function becerileriYukle() {
    try {
      const r = await fetch(`${API}/api/skills`);
      beceriler = await r.json();
      becerileriCiz();
    } catch { /* sunucu henüz hazır değil, sonraki bağlantıda tekrar denenir */ }
  }

  function becerileriCiz(filtre = "") {
    const f = filtre.trim().toLowerCase();
    const liste = f
      ? beceriler.filter((s) =>
          s.name.toLowerCase().includes(f) || s.description.toLowerCase().includes(f))
      : beceriler;

    el.skills.innerHTML = "";
    if (!liste.length) {
      el.skills.innerHTML = '<div class="empty">Eşleşen beceri yok.</div>';
      return;
    }
    for (const s of liste) {
      const div = document.createElement("div");
      div.className = "skill";
      div.title = "Örnek komut yazmak için tıkla";
      div.innerHTML =
        `<div class="n"></div><div class="d"></div>`;
      div.querySelector(".n").textContent = s.name;
      if (s.confirm) {
        const lock = document.createElement("span");
        lock.className = "lock";
        lock.textContent = "onay ister";
        div.querySelector(".n").appendChild(lock);
      }
      div.querySelector(".d").textContent = s.description;
      div.addEventListener("click", () => {
        el.input.value = s.name + " ";
        el.input.focus();
      });
      el.skills.appendChild(div);
    }
  }

  $("skillSearch").addEventListener("input", (e) => becerileriCiz(e.target.value));

  /* -------------------------------------------------------------- ayarlar */

  let ayarGonderZaman = null;
  function ayarGonder(veri, mesaj) {
    clearTimeout(ayarGonderZaman);
    ayarGonderZaman = setTimeout(async () => {
      try {
        const r = await fetch(`${API}/api/settings`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(veri),
        });
        const sonuc = await r.json();
        el.not.textContent = sonuc.restart_required
          ? "Bu ayar yeniden başlatınca geçerli olacak."
          : (mesaj || "Kaydedildi.");
        setTimeout(() => { el.not.textContent = ""; }, 4000);
      } catch {
        el.not.textContent = "Ayar kaydedilemedi.";
      }
    }, 250);
  }

  async function ayarlariYukle() {
    try {
      const cfg = await (await fetch(`${API}/api/config`)).json();
      $("setHiz").value = cfg.tts.speed;
      $("hizVal").textContent = Number(cfg.tts.speed).toFixed(2);
      $("setUyandirma").value = cfg.wake.mode;
      $("setDevam").value = cfg.wake.follow_up_s;
      $("devamVal").textContent = `${cfg.wake.follow_up_s} sn`;
      $("setHitap").value = cfg.persona.address;
      const sttSec = $("setSttModel");
      if ([...sttSec.options].some((o) => o.value === cfg.stt.model_size)) {
        sttSec.value = cfg.stt.model_size;
      }
      $("setYetki").value = cfg.perms.level;

      const m = await (await fetch(`${API}/api/models`)).json();
      const sel = $("setModel");
      sel.innerHTML = "";
      for (const ad of m.models.length ? m.models : [m.current]) {
        const o = document.createElement("option");
        o.value = o.textContent = ad;
        sel.appendChild(o);
      }
      sel.value = m.current;

      hafizayiYukle();
    } catch { /* sunucu hazır değil */ }
  }

  async function hafizayiYukle() {
    try {
      const kayitlar = await (await fetch(`${API}/api/memory`)).json();
      el.memlist.innerHTML = "";
      if (!kayitlar.length) {
        el.memlist.innerHTML = '<div class="none">Henüz bir şey kaydedilmedi.</div>';
        return;
      }
      for (const k of kayitlar.slice(-30).reverse()) {
        const d = document.createElement("div");
        d.textContent = "• " + k.fact;
        el.memlist.appendChild(d);
      }
    } catch { /* yok say */ }
  }

  $("setHiz").addEventListener("input", (e) => {
    $("hizVal").textContent = Number(e.target.value).toFixed(2);
    ayarGonder({ tts_speed: parseFloat(e.target.value) }, "Konuşma hızı güncellendi.");
  });
  $("setDevam").addEventListener("input", (e) => {
    $("devamVal").textContent = `${e.target.value} sn`;
    ayarGonder({ follow_up_s: parseFloat(e.target.value) });
  });
  $("setSesSeviye").addEventListener("input", (e) => {
    const v = parseInt(e.target.value, 10);
    $("sesVal").textContent = `%${v}`;
    sesler.seviyeAyarla(v / 100);
    localStorage.setItem("riley.sesSeviye", String(v));
  });
  $("setUyandirma").addEventListener("change", (e) =>
    ayarGonder({ wake_mode: e.target.value }));
  $("setModel").addEventListener("change", (e) => {
    ayarGonder({ model: e.target.value }, "Model değiştirildi, yükleniyor.");
    el.model.textContent = "model: " + e.target.value;
  });
  $("setHitap").addEventListener("change", (e) =>
    ayarGonder({ address: e.target.value }));
  $("setSttModel").addEventListener("change", (e) =>
    ayarGonder({ stt_model: e.target.value }));
  $("setYetki").addEventListener("change", (e) =>
    ayarGonder({ perm_level: e.target.value }, "Yetki seviyesi değişti."));

  function cekmeceAc(ac) {
    el.drawer.hidden = !ac;
    $("btnAyar").classList.toggle("on", ac);
    if (ac) { ayarlariYukle(); sesler.arac(); }
  }
  $("btnAyar").addEventListener("click", () => cekmeceAc(el.drawer.hidden));
  $("btnAyarKapat").addEventListener("click", () => cekmeceAc(false));


  /* -------------------------------------------------------------- kılavuz */

  const kilavuz = $("kilavuz");

  function kilavuzAc(ac) {
    kilavuz.hidden = !ac;
    $("btnKilavuz").classList.toggle("on", ac);
    if (ac) sesler.arac();
  }

  $("btnKilavuz").addEventListener("click", () => kilavuzAc(kilavuz.hidden));
  $("btnKilavuzKapat").addEventListener("click", () => kilavuzAc(false));
  kilavuz.addEventListener("click", (e) => {
    if (e.target === kilavuz) kilavuzAc(false);   // dışına tıklayınca kapan
  });

  document.querySelectorAll(".knav").forEach((b) => {
    b.addEventListener("click", () => {
      document.querySelectorAll(".knav").forEach((x) => x.classList.remove("active"));
      document.querySelectorAll(".kbolum").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      $("k-" + b.dataset.bolum).classList.add("active");
      $("k-" + b.dataset.bolum).parentElement.scrollTop = 0;
    });
  });

  // İlk açılışta kılavuzu bir kez göster
  if (!localStorage.getItem("riley.kilavuzGorundu")) {
    setTimeout(() => {
      kilavuzAc(true);
      localStorage.setItem("riley.kilavuzGorundu", "1");
    }, 2500);
  }

  /* ------------------------------------------------------------ etkileşim */

  el.input.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const text = el.input.value.trim();
    if (!text) return;
    send({ type: "text", text });
    el.input.value = "";
  });

  el.listen.addEventListener("click", () => send({ type: "listen" }));

  document.querySelectorAll(".quick button").forEach((b) => {
    b.addEventListener("click", () => {
      send({ type: "text", text: b.dataset.cmd });
      sesler.arac();
    });
  });

  const btnSes = $("btnSes");
  let sesAcik = localStorage.getItem("riley.ses") !== "0";
  function sesDurumuUygula() {
    sesler.ac(sesAcik);
    btnSes.classList.toggle("on", sesAcik);
    btnSes.classList.toggle("off", !sesAcik);
    localStorage.setItem("riley.ses", sesAcik ? "1" : "0");
  }
  btnSes.addEventListener("click", () => { sesAcik = !sesAcik; sesDurumuUygula(); });

  const kayitliSeviye = parseInt(localStorage.getItem("riley.sesSeviye") || "50", 10);
  $("setSesSeviye").value = kayitliSeviye;
  $("sesVal").textContent = `%${kayitliSeviye}`;
  sesler.seviyeAyarla(kayitliSeviye / 100);
  sesDurumuUygula();

  $("btnStop").addEventListener("click", () => send({ type: "cancel" }));
  $("btnReset").addEventListener("click", () => {
    send({ type: "reset" });
    el.you.textContent = "";
    el.me.textContent = "";
    el.chat.innerHTML = '<div class="empty">Henüz konuşma yok.</div>';
  });
  $("btnYes").addEventListener("click", () => send({ type: "confirm", approved: true }));
  $("btnNo").addEventListener("click", () => send({ type: "confirm", approved: false }));

  document.addEventListener("keydown", (e) => {
    const yaziAlaninda = e.target.tagName === "INPUT" || e.target.tagName === "SELECT";
    if (e.code === "Escape") {
      if (!kilavuz.hidden) return kilavuzAc(false);
      if (!el.drawer.hidden) return cekmeceAc(false);
      send({ type: "cancel" });
      return;
    }
    if (e.code === "F1") { e.preventDefault(); return kilavuzAc(kilavuz.hidden); }
    if (yaziAlaninda) return;
    if (e.code === "Space") { e.preventDefault(); send({ type: "listen" }); }
  });

  // Pencere düğmeleri (Electron köprüsü varsa)
  const win = window.rileyWindow;
  if (win) {
    $("btnMin").addEventListener("click", () => win.minimize());
    $("btnMax").addEventListener("click", () => win.toggleMaximize());
    $("btnClose").addEventListener("click", () => win.close());
    if (win.onTriggerListen) win.onTriggerListen(() => send({ type: "listen" }));
  } else {
    document.querySelector(".wincontrols").style.display = "none";
  }

  setInterval(() => {
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    el.clock.textContent = `${p(d.getHours())}:${p(d.getMinutes())}`;
  }, 1000);

  setState("booting");
  connect();
})();
