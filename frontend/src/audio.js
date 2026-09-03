/* Riley'nin ses atmosferi.

   Hiçbir ses dosyası kullanılmaz; her şey Web Audio ile canlı üretilir.
   Böylece telif derdi yok, paket küçük kalır ve sesler Riley'nin durumuna
   göre gerçek zamanlı değişir.

   Katmanlar:
     drone    — çok alçak, sürekli uğultu (reaktörün "çalışıyor" hissi)
     shimmer  — süzülmüş gürültüden gelen hafif parıltı
     olaylar  — açılış süpürmesi, uyanma cıvıltısı, onay/hata tonları
*/

(function () {
  "use strict";

  const NOTA = { do: 65.41, sol: 98.0, do2: 130.81, mi: 164.81, sol2: 196.0 };

  class RileyAudio {
    constructor() {
      this.ctx = null;
      this.master = null;
      this.droneGain = null;
      this.filter = null;
      this.lfo = null;
      this.enabled = true;
      this.started = false;
      this.seviye = 0.5;         // kullanıcı ses seviyesi 0-1
      this._nodes = [];
    }

    /* Tarayıcı kuralları gereği ilk ses bir kullanıcı hareketiyle ya da
       Electron'un izin ayarıyla başlar. */
    baslat() {
      if (this.started) return;
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;

      this.ctx = new AC();
      this.master = this.ctx.createGain();
      this.master.gain.value = this.enabled ? this.seviye * 0.5 : 0;
      this.master.connect(this.ctx.destination);

      this._droneKur();
      this.started = true;

      if (this.ctx.state === "suspended") {
        const devam = () => {
          this.ctx.resume();
          document.removeEventListener("pointerdown", devam);
          document.removeEventListener("keydown", devam);
        };
        document.addEventListener("pointerdown", devam);
        document.addEventListener("keydown", devam);
      }
    }

    /* --- sürekli katmanlar --- */

    _droneKur() {
      const ctx = this.ctx;

      this.droneGain = ctx.createGain();
      this.droneGain.gain.value = 0.0;
      this.droneGain.connect(this.master);

      // Alçak geçiren süzgeç: sesi arka planda tutar, tiz bırakmaz
      this.filter = ctx.createBiquadFilter();
      this.filter.type = "lowpass";
      this.filter.frequency.value = 420;
      this.filter.Q.value = 3;
      this.filter.connect(this.droneGain);

      // İki hafif akortsuz osilatör: "canlı" bir uğultu verir
      [NOTA.do, NOTA.sol, NOTA.do2].forEach((frekans, i) => {
        const osc = ctx.createOscillator();
        osc.type = i === 2 ? "triangle" : "sine";
        osc.frequency.value = frekans * (1 + (i - 1) * 0.0015);

        const g = ctx.createGain();
        g.gain.value = [0.5, 0.28, 0.12][i];
        osc.connect(g).connect(this.filter);
        osc.start();
        this._nodes.push(osc);
      });

      // Süzülmüş gürültü: metalik bir parıltı katar
      const gurultu = ctx.createBufferSource();
      gurultu.buffer = this._gurultuTamponu(4);
      gurultu.loop = true;

      const bant = ctx.createBiquadFilter();
      bant.type = "bandpass";
      bant.frequency.value = 1400;
      bant.Q.value = 6;

      const gurultuGain = ctx.createGain();
      gurultuGain.gain.value = 0.05;
      gurultu.connect(bant).connect(gurultuGain).connect(this.droneGain);
      gurultu.start();
      this._nodes.push(gurultu);

      // Süzgeç kesim frekansını yavaşça gezdiren LFO: nefes alan bir doku
      this.lfo = ctx.createOscillator();
      this.lfo.frequency.value = 0.06;
      const lfoGain = ctx.createGain();
      lfoGain.gain.value = 130;
      this.lfo.connect(lfoGain).connect(this.filter.frequency);
      this.lfo.start();
      this._nodes.push(this.lfo);
    }

    _gurultuTamponu(saniye) {
      const n = this.ctx.sampleRate * saniye;
      const buf = this.ctx.createBuffer(1, n, this.ctx.sampleRate);
      const data = buf.getChannelData(0);
      for (let i = 0; i < n; i++) data[i] = Math.random() * 2 - 1;
      return buf;
    }

    _rampa(param, hedef, sure) {
      if (!this.ctx) return;
      const t = this.ctx.currentTime;
      param.cancelScheduledValues(t);
      param.setValueAtTime(param.value, t);
      param.linearRampToValueAtTime(hedef, t + sure);
    }

    /* --- olay sesleri --- */

    _ton(frekans, sure, tip = "sine", hacim = 0.18, kayma = 0) {
      if (!this.ctx || !this.enabled) return;
      const t = this.ctx.currentTime;

      const osc = this.ctx.createOscillator();
      osc.type = tip;
      osc.frequency.setValueAtTime(frekans, t);
      if (kayma) osc.frequency.exponentialRampToValueAtTime(frekans + kayma, t + sure);

      const g = this.ctx.createGain();
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(hacim, t + 0.012);
      g.gain.exponentialRampToValueAtTime(0.0001, t + sure);

      osc.connect(g).connect(this.master);
      osc.start(t);
      osc.stop(t + sure + 0.05);
    }

    /* Açılış: alçaktan yükselen süpürme + üç notalık arpej */
    acilis() {
      if (!this.ctx || !this.enabled) return;
      const t = this.ctx.currentTime;

      const osc = this.ctx.createOscillator();
      osc.type = "sawtooth";
      osc.frequency.setValueAtTime(60, t);
      osc.frequency.exponentialRampToValueAtTime(900, t + 1.5);

      const suzgec = this.ctx.createBiquadFilter();
      suzgec.type = "lowpass";
      suzgec.frequency.setValueAtTime(300, t);
      suzgec.frequency.exponentialRampToValueAtTime(3600, t + 1.5);
      suzgec.Q.value = 8;

      const g = this.ctx.createGain();
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(0.1, t + 0.5);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 1.9);

      osc.connect(suzgec).connect(g).connect(this.master);
      osc.start(t);
      osc.stop(t + 2);

      [NOTA.do2, NOTA.mi, NOTA.sol2].forEach((f, i) =>
        setTimeout(() => this._ton(f * 2, 0.5, "sine", 0.12), 900 + i * 150)
      );

      // Uğultu yavaşça devreye girsin
      setTimeout(() => this.droneAc(), 600);
    }

    droneAc() {
      if (this.droneGain) this._rampa(this.droneGain.gain, 0.16, 3.0);
    }

    droneKapat() {
      if (this.droneGain) this._rampa(this.droneGain.gain, 0, 1.2);
    }

    uyandi() { this._ton(880, 0.16, "sine", 0.16, 440); }
    dinliyor() { this._ton(1320, 0.1, "sine", 0.1); }
    onay() { this._ton(660, 0.12, "sine", 0.14); setTimeout(() => this._ton(990, 0.18, "sine", 0.12), 90); }
    hata() { this._ton(220, 0.3, "sawtooth", 0.1, -60); }
    arac() { this._ton(1760, 0.06, "square", 0.045); }

    /* Duruma göre atmosferi renklendir */
    durum(yeni) {
      if (!this.ctx || !this.filter) return;
      const ayar = {
        idle: { kesim: 400, lfo: 0.06, hacim: 0.16 },
        listening: { kesim: 700, lfo: 0.16, hacim: 0.2 },
        thinking: { kesim: 900, lfo: 0.5, hacim: 0.22 },
        acting: { kesim: 1100, lfo: 0.8, hacim: 0.22 },
        speaking: { kesim: 340, lfo: 0.05, hacim: 0.1 },
        error: { kesim: 240, lfo: 0.03, hacim: 0.14 },
      }[yeni];
      if (!ayar) return;

      this._rampa(this.filter.frequency, ayar.kesim, 0.6);
      this._rampa(this.lfo.frequency, ayar.lfo, 0.6);
      if (this.droneGain && this.droneGain.gain.value > 0.001) {
        this._rampa(this.droneGain.gain, ayar.hacim, 0.6);
      }
    }

    /* --- kullanıcı denetimi --- */

    ac(durum) {
      this.enabled = durum;
      if (!this.master) return;
      this._rampa(this.master.gain, durum ? this.seviye * 0.5 : 0, 0.4);
    }

    seviyeAyarla(v) {
      this.seviye = Math.max(0, Math.min(1, v));
      if (this.master && this.enabled) {
        this._rampa(this.master.gain, this.seviye * 0.5, 0.2);
      }
    }
  }

  window.RileyAudio = RileyAudio;
})();
