/* Reaktör görselleştirmesi: iç içe dönen halkalar, sese tepki veren
   çubuklar, radar taraması ve yörüngedeki parçacıklar. */

(function () {
  "use strict";

  const TICKS = 96;          // ses tepkili çubuk sayısı
  const PARTICLES = 34;

  class Reactor {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");

      this.level = 0;          // yumuşatılmış ses seviyesi
      this.target = 0;         // gelen ham seviye
      this.energy = 0;         // duruma göre genel canlılık
      this.state = "booting";
      this.t = 0;

      this.bars = new Float32Array(TICKS);
      this.particles = [];
      for (let i = 0; i < PARTICLES; i++) {
        this.particles.push({
          angle: Math.random() * Math.PI * 2,
          radius: 150 + Math.random() * 170,
          speed: (Math.random() - 0.5) * 0.0026,
          size: 0.6 + Math.random() * 1.7,
          phase: Math.random() * Math.PI * 2,
        });
      }

      this._resize();
      window.addEventListener("resize", () => this._resize());
      requestAnimationFrame(() => this._frame());
    }

    _resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const rect = this.canvas.getBoundingClientRect();
      this.canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      this.canvas.height = Math.max(1, Math.floor(rect.height * dpr));
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      this.w = rect.width;
      this.h = rect.height;
      this.scale = Math.min(this.w, this.h) / 520;
    }

    setLevel(value) {
      this.target = Math.max(0, Math.min(1, value));
    }

    setState(state) {
      this.state = state;
    }

    /* Ana renk CSS değişkeninden okunur; durum değişince tema de değişir. */
    _accent() {
      const raw = getComputedStyle(document.body)
        .getPropertyValue("--accent")
        .trim();
      return raw || "#33d6ff";
    }

    _rgba(hex, alpha) {
      const h = hex.replace("#", "");
      const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
      const n = parseInt(full, 16);
      return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
    }

    _frame() {
      this.t += 1;
      const ctx = this.ctx;
      const cx = this.w / 2;
      const cy = this.h / 2 - 24 * this.scale;
      const s = this.scale;

      // Durumlara göre taban canlılık
      const baseline = {
        booting: 0.28, idle: 0.06, listening: 0.14,
        thinking: 0.4, acting: 0.5, speaking: 0.12, error: 0.3,
      }[this.state] ?? 0.1;

      this.level += (this.target - this.level) * 0.22;
      this.target *= 0.9;                      // gelen olay yoksa sön
      this.energy += (baseline - this.energy) * 0.05;

      const amp = Math.max(this.level, this.energy * 0.9);
      const color = this._accent();

      ctx.clearRect(0, 0, this.w, this.h);
      ctx.save();
      ctx.translate(cx, cy);

      this._drawParticles(ctx, color, s, amp);
      this._drawOuterRing(ctx, color, s);
      this._drawBars(ctx, color, s, amp);
      this._drawArcs(ctx, color, s);
      this._drawSweep(ctx, color, s);
      this._drawCore(ctx, color, s, amp);

      ctx.restore();
      requestAnimationFrame(() => this._frame());
    }

    /* --- katmanlar --- */

    _drawParticles(ctx, color, s, amp) {
      ctx.save();
      for (const p of this.particles) {
        p.angle += p.speed * (1 + amp * 2.5);
        const drift = Math.sin(this.t * 0.012 + p.phase) * 9 * s;
        const x = Math.cos(p.angle) * (p.radius * s + drift);
        const y = Math.sin(p.angle) * (p.radius * s + drift) * 0.94;
        const alpha = 0.1 + 0.4 * (0.5 + 0.5 * Math.sin(this.t * 0.02 + p.phase));

        ctx.beginPath();
        ctx.arc(x, y, p.size * s, 0, Math.PI * 2);
        ctx.fillStyle = this._rgba(color, alpha * (0.4 + amp));
        ctx.fill();
      }
      ctx.restore();
    }

    _drawOuterRing(ctx, color, s) {
      // İnce dış çember + köşe işaretleri
      ctx.save();
      ctx.strokeStyle = this._rgba(color, 0.1);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(0, 0, 232 * s, 0, Math.PI * 2);
      ctx.stroke();

      ctx.rotate(this.t * 0.0012);
      ctx.strokeStyle = this._rgba(color, 0.3);
      ctx.lineWidth = 2 * s;
      for (let i = 0; i < 4; i++) {
        ctx.beginPath();
        ctx.arc(0, 0, 232 * s, i * (Math.PI / 2) - 0.16, i * (Math.PI / 2) + 0.16);
        ctx.stroke();
      }
      ctx.restore();
    }

    _drawBars(ctx, color, s, amp) {
      // Ses seviyesine tepki veren çubuk halkası
      const inner = 150 * s;
      ctx.save();
      ctx.rotate(-Math.PI / 2 + this.t * 0.0006);

      for (let i = 0; i < TICKS; i++) {
        // Sahte spektrum: birkaç sinüsün karışımı, her çubuk farklı fazda
        const wobble =
          0.45 +
          0.28 * Math.sin(this.t * 0.05 + i * 0.55) +
          0.27 * Math.sin(this.t * 0.021 + i * 1.31);
        const target = amp * wobble * 58 * s;
        this.bars[i] += (target - this.bars[i]) * 0.3;

        const len = 5 * s + Math.max(0, this.bars[i]);
        const angle = (i / TICKS) * Math.PI * 2;
        const cos = Math.cos(angle);
        const sin = Math.sin(angle);

        ctx.beginPath();
        ctx.moveTo(cos * inner, sin * inner);
        ctx.lineTo(cos * (inner + len), sin * (inner + len));
        ctx.lineWidth = 2 * s;
        ctx.lineCap = "round";
        ctx.strokeStyle = this._rgba(color, 0.2 + Math.min(0.7, this.bars[i] / (30 * s)));
        ctx.stroke();
      }
      ctx.restore();
    }

    _drawArcs(ctx, color, s) {
      // Zıt yönlerde dönen kesikli halkalar
      const rings = [
        { r: 96, w: 1.4, speed: 0.006, segs: 3, gap: 0.42, a: 0.55 },
        { r: 118, w: 1, speed: -0.0035, segs: 5, gap: 0.28, a: 0.32 },
        { r: 133, w: 3, speed: 0.0018, segs: 2, gap: 0.9, a: 0.22 },
      ];

      for (const ring of rings) {
        ctx.save();
        ctx.rotate(this.t * ring.speed);
        ctx.strokeStyle = this._rgba(color, ring.a);
        ctx.lineWidth = ring.w * s;
        ctx.lineCap = "butt";
        const step = (Math.PI * 2) / ring.segs;
        for (let i = 0; i < ring.segs; i++) {
          ctx.beginPath();
          ctx.arc(0, 0, ring.r * s, i * step, i * step + step - ring.gap);
          ctx.stroke();
        }
        ctx.restore();
      }

      // İnce sabit hat
      ctx.beginPath();
      ctx.arc(0, 0, 143 * s, 0, Math.PI * 2);
      ctx.strokeStyle = this._rgba(color, 0.12);
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    _drawSweep(ctx, color, s) {
      // Radar taraması — yalnızca düşünürken/çalışırken belirginleşir
      const active = this.state === "thinking" || this.state === "acting" ||
                     this.state === "booting";
      if (!active) return;

      ctx.save();
      ctx.rotate(this.t * 0.028);
      const grad = ctx.createLinearGradient(0, 0, 150 * s, 0);
      grad.addColorStop(0, this._rgba(color, 0));
      grad.addColorStop(1, this._rgba(color, 0.5));
      ctx.strokeStyle = grad;
      ctx.lineWidth = 2 * s;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(148 * s, 0);
      ctx.stroke();
      ctx.restore();
    }

    _drawCore(ctx, color, s, amp) {
      const pulse = 1 + amp * 0.42 + Math.sin(this.t * 0.045) * 0.035;
      const r = 62 * s * pulse;

      // Dış parıltı
      const glow = ctx.createRadialGradient(0, 0, 0, 0, 0, r * 2.7);
      glow.addColorStop(0, this._rgba(color, 0.4 + amp * 0.35));
      glow.addColorStop(0.35, this._rgba(color, 0.13));
      glow.addColorStop(1, this._rgba(color, 0));
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(0, 0, r * 2.7, 0, Math.PI * 2);
      ctx.fill();

      // Çekirdek
      const core = ctx.createRadialGradient(0, -r * 0.25, r * 0.05, 0, 0, r);
      core.addColorStop(0, "#ffffff");
      core.addColorStop(0.28, this._rgba(color, 0.92));
      core.addColorStop(1, this._rgba(color, 0.06));
      ctx.fillStyle = core;
      ctx.beginPath();
      ctx.arc(0, 0, r, 0, Math.PI * 2);
      ctx.fill();

      // Çekirdek çeperi
      ctx.beginPath();
      ctx.arc(0, 0, r * 1.16, 0, Math.PI * 2);
      ctx.strokeStyle = this._rgba(color, 0.5);
      ctx.lineWidth = 1.2 * s;
      ctx.stroke();

      // İçteki dönen üçgen çizgiler
      ctx.save();
      ctx.rotate(-this.t * 0.009);
      ctx.strokeStyle = this._rgba(color, 0.28);
      ctx.lineWidth = 1 * s;
      ctx.beginPath();
      for (let i = 0; i < 3; i++) {
        const a = (i / 3) * Math.PI * 2;
        const x = Math.cos(a) * r * 0.72;
        const y = Math.sin(a) * r * 0.72;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.stroke();
      ctx.restore();
    }
  }

  window.Reactor = Reactor;
})();
