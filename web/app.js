/* Intérprete — cliente. Captura audio, lo manda al PC por WebSocket
   y pinta los subtítulos en español que vuelven. */

(() => {
  "use strict";

  const TOKEN = new URLSearchParams(location.search).get("k") || "";
  const WS_URL = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws?k=${encodeURIComponent(TOKEN)}`;

  const $ = (id) => document.getElementById(id);
  const dot = $("dot"), engineLabel = $("engine"), notice = $("notice");
  const feed = $("feed"), empty = $("empty"), live = $("live");
  const liveEn = $("liveEn"), liveEs = $("liveEs"), levelBar = $("level");
  const toggleBtn = $("toggle"), sourceSel = $("source"), modeSel = $("mode");
  const panel = $("panel"), panelBody = $("panelBody");

  let ws = null, wsReady = false, retry = 0, heartbeat = null;
  let audioCtx = null, mediaStream = null, workletNode = null;
  let capturing = false, claudeReady = false, wakeLock = null;
  const transcript = [];

  /* ---------------- avisos ---------------- */
  let noticeTimer = null;
  const banner = notice;
  function say(message, ms = 6000, kind = "info") {
    clearTimeout(noticeTimer);
    if (!message) { notice.classList.add("hidden"); notice.dataset.kind = ""; return; }
    notice.textContent = message;
    notice.dataset.kind = kind;
    notice.classList.remove("hidden");
    if (ms) noticeTimer = setTimeout(() => {
      notice.classList.add("hidden");
      notice.dataset.kind = "";
    }, ms);
  }

  /* ---------------- estado del servicio ----------------
     Una sola funcion decide todo lo que se ve: el punto, el texto, el color de
     la barra, el titulo de la pestana y el aviso fijo. Asi no puede quedar un
     indicador diciendo una cosa y otro diciendo otra. */
  let engineName = "";

  function estado(nuevo) {
    document.body.dataset.conn = nuevo;

    if (nuevo === "conectado") {
      dot.className = "dot on";
      engineLabel.textContent = engineName ? `conectado · ${engineName}` : "conectado";
      document.title = "Intérprete";
      if (banner.dataset.kind === "danger") {
        say("Conexión restablecida con el PC.", 3000, "ok");
      }
    } else if (nuevo === "conectando") {
      dot.className = "dot";
      engineLabel.textContent = "conectando…";
      document.title = "Intérprete";
    } else if (nuevo === "caido") {
      dot.className = "dot off";
      engineLabel.textContent = "SIN CONEXIÓN — reintentando";
      // Visible aunque la pestana este en segundo plano, que es justo lo que
      // pasa durante una entrevista.
      document.title = "⚠ Sin conexión — Intérprete";
      say("Se perdió la conexión con el PC. Reintentando…", 0, "danger");
    } else if (nuevo === "rechazado") {
      dot.className = "dot off";
      engineLabel.textContent = "token rechazado";
      document.title = "⚠ Token inválido — Intérprete";
      say("El servidor rechazó el token. Verifica que copiaste la URL completa, con el ?k=...", 0, "danger");
    }
  }

  /* ---------------- WebSocket ---------------- */
  function connect() {
    if (!TOKEN) {
      say("Falta el token en la URL. Abre el enlace completo que imprime el servidor (termina en ?k=...).", 0, "danger");
      return;
    }
    estado(retry === 0 ? "conectando" : "caido");
    ws = new WebSocket(WS_URL);
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      wsReady = true; retry = 0;
      lastServerMsg = Date.now();
      estado("conectado");
      clearInterval(heartbeat);
      heartbeat = setInterval(() => { if (wsReady) ws.send("ping"); }, 15000);
      ws.send(`mode:${modeSel.value}`);
    };

    ws.onclose = (event) => {
      wsReady = false;
      clearInterval(heartbeat);
      if (event.code === 4401) { estado("rechazado"); return; }
      estado("caido");
      retry = Math.min(retry + 1, 6);
      setTimeout(connect, 400 * retry);
    };

    ws.onerror = () => { /* onclose se encarga */ };
    ws.onmessage = (event) => {
      lastServerMsg = Date.now();
      handle(JSON.parse(event.data));
    };
  }

  /* Un WebSocket puede quedarse "abierto" contra un tunel que ya murio: el
     navegador no se entera hasta que intenta escribir. Si el servidor lleva
     rato sin decir nada, se fuerza la reconexion en vez de tragar audio al
     vacio. Mientras se captura llegan medidores cada 200 ms, asi que el
     silencio es senal inequivoca. */
  let lastServerMsg = Date.now();
  setInterval(() => {
    if (!wsReady) return;
    const mudo = Date.now() - lastServerMsg;
    if (capturing && mudo > 8000) { try { ws.close(); } catch {} }
    else if (!capturing && mudo > 45000) { try { ws.close(); } catch {} }
  }, 3000);

  function handle(msg) {
    switch (msg.type) {
      case "status":
        claudeReady = !!msg.claude;
        engineName = `${msg.stt.split(" / ")[0]} en GPU`;
        estado("conectado");
        break;
      case "level":
        levelBar.style.width = `${Math.round(msg.rms * 100)}%`;
        live.classList.toggle("active", !!msg.speaking);
        break;
      case "partial":
        if (msg.es) {
          liveEn.textContent = msg.en;
          liveEs.textContent = msg.es;
        } else {
          liveEn.textContent = "";
          liveEs.textContent = msg.en;
        }
        break;
      case "final":
        liveEn.textContent = ""; liveEs.textContent = "";
        addLine(msg);
        break;
      case "clear":
        liveEn.textContent = ""; liveEs.textContent = "";
        break;
      case "error":
        say(`Error del servidor: ${msg.message}`);
        break;
    }
  }

  /* ---------------- render ---------------- */
  function addLine(msg) {
    empty.classList.add("hidden");
    transcript.push(msg);

    const stuck = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 120;
    const node = document.createElement("div");
    node.className = "line fresh";

    // Con traducción: inglés pequeño arriba, español grande abajo.
    // Sin traducción: solo el inglés, en grande.
    const en = document.createElement("p");
    en.className = "en";
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = `${msg.latency_ms} ms`;
    en.appendChild(tag);
    if (msg.es) en.appendChild(document.createTextNode(msg.en));

    const es = document.createElement("p");
    es.className = "es";
    es.textContent = msg.es || msg.en;

    node.appendChild(en);
    node.appendChild(es);

    if (claudeReady) {
      const btn = document.createElement("button");
      btn.className = "ghost explain";
      btn.textContent = "explicar";
      btn.onclick = (ev) => { ev.stopPropagation(); explain(msg.en, btn); };
      node.appendChild(btn);
    }

    node.onclick = () => {
      const texto = msg.es ? `${msg.en}\n${msg.es}` : msg.en;
      navigator.clipboard.writeText(texto).then(
        () => say("Línea copiada.", 1500), () => {}
      );
    };

    feed.appendChild(node);
    while (feed.children.length > 400) feed.removeChild(feed.children[1]);
    if (stuck) feed.scrollTop = feed.scrollHeight;
  }

  /* ---------------- explicación con Claude ---------------- */
  async function explain(english, button) {
    const previous = transcript.slice(-4, -1).map((t) => t.en).join(" ");
    button.disabled = true;
    button.textContent = "…";
    panel.classList.remove("hidden");
    panelBody.textContent = "Consultando…";
    try {
      const res = await fetch("/api/explain", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ k: TOKEN, en: english, context: previous }),
      });
      const data = await res.json();
      panelBody.textContent = res.ok ? data.text : `Error: ${data.detail}`;
    } catch (err) {
      panelBody.textContent = `Error: ${err.message}`;
    } finally {
      button.disabled = false;
      button.textContent = "explicar";
    }
  }
  $("panelClose").onclick = () => panel.classList.add("hidden");

  /* ---------------- captura de audio ---------------- */
  const WORKLET = `
    class PcmTap extends AudioWorkletProcessor {
      constructor() { super(); this.buf = new Int16Array(1600); this.n = 0; }
      process(inputs) {
        const ch = inputs[0] && inputs[0][0];
        if (!ch) return true;
        for (let i = 0; i < ch.length; i++) {
          const s = Math.max(-1, Math.min(1, ch[i]));
          this.buf[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff;
          if (this.n === this.buf.length) {
            const copy = this.buf.slice();
            this.port.postMessage(copy.buffer, [copy.buffer]);
            this.n = 0;
          }
        }
        return true;
      }
    }
    registerProcessor('pcm-tap', PcmTap);
  `;

  async function startCapture() {
    if (!wsReady) { say("Todavía no hay conexión con el PC."); return; }

    const useDisplay = sourceSel.value === "display";
    try {
      if (useDisplay) {
        mediaStream = await navigator.mediaDevices.getDisplayMedia({
          video: true,
          audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
        });
        if (mediaStream.getAudioTracks().length === 0) {
          mediaStream.getTracks().forEach((t) => t.stop());
          mediaStream = null;
          say("Compartiste la pestaña pero sin audio. Vuelve a intentar y marca «También compartir el audio de la pestaña».", 0);
          return;
        }
      } else {
        mediaStream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
      }
    } catch (err) {
      say(`No se pudo capturar el audio: ${err.message}`);
      return;
    }

    // Chrome remuestrea solo al pedir el contexto directamente a 16 kHz.
    audioCtx = new AudioContext({ sampleRate: 16000, latencyHint: "interactive" });
    const blobUrl = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
    await audioCtx.audioWorklet.addModule(blobUrl);
    URL.revokeObjectURL(blobUrl);

    const source = audioCtx.createMediaStreamSource(mediaStream);
    workletNode = new AudioWorkletNode(audioCtx, "pcm-tap");
    workletNode.port.onmessage = (event) => {
      if (wsReady && ws.readyState === WebSocket.OPEN) ws.send(event.data);
    };

    // Silenciador: el worklet solo se ejecuta si el grafo llega al destino,
    // pero con ganancia 0 no se reproduce nada (ni eco en la reunión).
    const mute = audioCtx.createGain();
    mute.gain.value = 0;
    source.connect(workletNode);
    workletNode.connect(mute);
    mute.connect(audioCtx.destination);

    mediaStream.getTracks().forEach((track) => {
      track.onended = () => { if (capturing) stopCapture("Se dejó de compartir la pestaña."); };
    });

    if (wsReady) ws.send("resume");
    capturing = true;
    toggleBtn.textContent = "Detener";
    toggleBtn.classList.add("stop");
    empty.classList.add("hidden");
    say(useDisplay ? "Escuchando el audio compartido." : "Escuchando el micrófono.", 3000);
    keepAwake();
  }

  function stopCapture(reason) {
    capturing = false;
    if (wsReady) ws.send("pause");
    if (workletNode) { workletNode.port.onmessage = null; workletNode.disconnect(); workletNode = null; }
    if (audioCtx) { audioCtx.close().catch(() => {}); audioCtx = null; }
    if (mediaStream) { mediaStream.getTracks().forEach((t) => t.stop()); mediaStream = null; }
    if (wakeLock) { wakeLock.release().catch(() => {}); wakeLock = null; }
    toggleBtn.textContent = "Iniciar";
    toggleBtn.classList.remove("stop");
    levelBar.style.width = "0%";
    live.classList.remove("active");
    liveEn.textContent = ""; liveEs.textContent = "";
    if (reason) say(reason);
  }

  async function keepAwake() {
    try {
      if ("wakeLock" in navigator) wakeLock = await navigator.wakeLock.request("screen");
    } catch { /* no es crítico */ }
  }
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && capturing && !wakeLock) keepAwake();
  });

  /* ---------------- controles ---------------- */
  toggleBtn.onclick = () => (capturing ? stopCapture() : startCapture());

  $("clear").onclick = () => {
    feed.querySelectorAll(".line").forEach((n) => n.remove());
    transcript.length = 0;
    empty.classList.remove("hidden");
    if (wsReady) ws.send("reset");
  };

  $("save").onclick = () => {
    if (!transcript.length) { say("Todavía no hay nada que guardar."); return; }
    const body = transcript
      .map((t) => (t.es ? `EN: ${t.en}\nES: ${t.es}\n` : `${t.en}\n`))
      .join("\n");
    const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
    const url = URL.createObjectURL(new Blob([body], { type: "text/plain;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `entrevista-${stamp}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const MODE_KEY = "interprete.mode";
  try {
    const saved = localStorage.getItem(MODE_KEY);
    if (saved === "en" || saved === "es") modeSel.value = saved;
  } catch {}
  modeSel.onchange = () => {
    try { localStorage.setItem(MODE_KEY, modeSel.value); } catch {}
    if (wsReady) ws.send(`mode:${modeSel.value}`);
    liveEn.textContent = ""; liveEs.textContent = "";
    say(modeSel.value === "es"
      ? "Modo inglés → español."
      : "Modo solo inglés: sin traducción.", 2500);
  };

  const FONT_KEY = "interprete.fontsize";
  let fontSize = parseInt(localStorage.getItem(FONT_KEY) || "34", 10);
  function applyFont() {
    fontSize = Math.max(20, Math.min(64, fontSize));
    document.documentElement.style.setProperty("--es-size", `${fontSize}px`);
    try { localStorage.setItem(FONT_KEY, String(fontSize)); } catch {}
  }
  $("bigger").onclick = () => { fontSize += 3; applyFont(); };
  $("smaller").onclick = () => { fontSize -= 3; applyFont(); };
  applyFont();

  window.addEventListener("beforeunload", () => { if (capturing) stopCapture(); });

  connect();
})();
