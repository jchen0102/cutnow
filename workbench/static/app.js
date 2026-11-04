const $ = (s) => document.querySelector(s);
let S = null, sel = 0, curVer = null;

const fmt = (n) => (n ?? 0).toFixed(2) + "s";

async function api(path, body) {
  const r = await fetch(path, body ? {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
  } : undefined);
  return r.json();
}

function beatGrid(svgW, total, bpm) {
  const beat = 60 / bpm, n = Math.ceil(total / beat);
  let out = "";
  for (let i = 0; i <= n; i++) {
    const x = (i * beat / total) * svgW;
    const strong = i % 4 === 0;
    out += `<line x1="${x}" y1="0" x2="${x}" y2="132" stroke="${strong ? "#2b3644" : "#1a222c"}" stroke-width="1"/>`;
  }
  return out;
}

function drawTimeline() {
  const svg = $("#tl"), W = svg.clientWidth || 800, H = 132, total = S.total || 1;
  const beats = [];
  let acc = 0;
  for (const c of S.clips) { beats.push(acc); acc += c.dur; }

  let s = beatGrid(W, total, S.bpm);
  // 拍点刻度条
  s += `<rect x="0" y="0" width="${W}" height="132" fill="transparent"/>`;
  const trackY = 34, trackH = 62;
  S.clips.forEach((c, i) => {
    const x = (c.at / total) * W, w = Math.max(2, (c.dur / total) * W - 2);
    const stroke = i === sel ? "#3ddc97" : "#2b3644";
    s += `<g class="clipg" data-i="${i}" style="cursor:pointer">
      <rect x="${x}" y="${trackY}" width="${w}" height="${trackH}" rx="5" fill="#10161e" stroke="${stroke}" stroke-width="${i === sel ? 2 : 1}"/>
      <image href="${c.thumb}" x="${x}" y="${trackY}" width="${w}" height="${trackH}" preserveAspectRatio="xMidYMid slice" opacity="0.55" clip-path="inset(0 round 5px)"/>
      <rect x="${x}" y="${trackY}" width="${w}" height="${trackH}" rx="5" fill="none" stroke="${stroke}" stroke-width="${i === sel ? 2 : 1}"/>
      <text x="${x + 6}" y="${trackY + 14}" fill="#e6edf3" font-size="11" font-weight="600">${c.role || ""}</text>
      <text x="${x + 6}" y="${trackY + 28}" fill="#8b98a8" font-size="10">${c.beats}拍 ${c.dur.toFixed(2)}s</text>
      ${c.replaced ? `<circle cx="${x + w - 10}" cy="${trackY + 10}" r="4" fill="#6aa9ff"/>` : ""}
    </g>`;
  });
  s += `<line id="playhead" x1="0" y1="0" x2="0" y2="132" stroke="#ff6b6b" stroke-width="1.5"/>`;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = s;
  svg.querySelectorAll(".clipg").forEach((g) =>
    g.addEventListener("click", () => { sel = +g.dataset.i; renderAll(); }));
}

function drawShots() {
  $("#shotCount").textContent = `${S.clips.length} 段`;
  $("#shots").innerHTML = S.clips.map((c, i) => `
    <div class="shot ${i === sel ? "sel" : ""}" data-i="${i}">
      <img src="${c.thumb}" alt="">
      <div class="t"><b>${c.role || "镜头" + (i + 1)} · ${c.beats}拍</b>
        <span>${fmt(c.start)} → ${fmt(c.start + c.dur)} · ${c.dur.toFixed(2)}s</span></div>
      ${c.replaced ? '<i class="dot on" title="已换人"></i>' : ""}
    </div>`).join("");
  $("#shots").querySelectorAll(".shot").forEach((el) =>
    el.addEventListener("click", () => { sel = +el.dataset.i; renderAll(); }));
}

function drawInspector() {
  const c = S.clips[sel], box = $("#inspector");
  if (!c) return box.classList.add("hidden");
  box.classList.remove("hidden");
  box.innerHTML = `
    <div class="row"><label>镜头</label><b>${sel + 1} / ${S.clips.length}</b>
      <span class="dim" style="margin-left:auto">${c.role || ""}</span></div>
    <div class="row"><label>拍数</label>
      <select id="beats">${[2, 4, 6, 8, 12, 16].map((b) => `<option value="${b}" ${b === c.beats ? "selected" : ""}>${b} 拍 · ${(b * 60 / S.bpm).toFixed(2)}s</option>`).join("")}</select>
    </div>
    <div class="row"><label>源起点</label>
      <input id="start" type="number" step="0.1" value="${c.start.toFixed(2)}">
    </div>
    <div class="row"><label></label>
      <button id="apply" class="primary">应用</button>
      <span class="dim" style="font-size:11px">改完点渲染出新版本</span></div>`;
  $("#apply").addEventListener("click", async () => {
    S = await api("/api/clip", { index: sel, beats: +$("#beats").value, start: +$("#start").value });
    renderAll();
  });
}

function drawOps() {
  $("#ops").innerHTML = S.ops.map((o) => `
    <div class="op"><b>${o.op}</b><p>${(o.evidence || "")}</p></div>`).join("");
}

function drawVersions() {
  if (!S.versions.length) { $("#versions").innerHTML = '<div class="dim">—</div>'; return; }
  const list = [...S.versions].reverse();
  if (!curVer) curVer = list[0].id;
  $("#versions").innerHTML = list.map((v) => `
    <div class="ver ${v.id === curVer ? "sel" : ""}" data-id="${v.id}" data-url="${v.url}">
      <b>${v.id}</b><span>${(v.bytes / 1e6).toFixed(1)}MB · ${v.at}</span></div>`).join("");
  $("#versions").querySelectorAll(".ver").forEach((el) => el.addEventListener("click", () => {
    curVer = el.dataset.id; play(el.dataset.url); drawVersions();
  }));
  const v = list.find((x) => x.id === curVer);
  if (v) play(v.url);
}

function play(url) {
  const v = $("#player");
  $("#empty").style.display = "none";
  if (!v.src.endsWith(url)) { v.src = url; v.poster = "/api/poster"; }
}

function hookPlayer() {
  const v = $("#player");
  v.addEventListener("timeupdate", () => {
    const ph = $("#playhead");
    if (!ph || !S) return;
    const total = S.total || 1;
    ph.setAttribute("x1", (v.currentTime / total) * ($("#tl").clientWidth || 800));
    ph.setAttribute("x2", ph.getAttribute("x1"));
  });
}

function renderAll() {
  $("#meta").innerHTML = `<span><b>${S.title}</b></span><span>${S.bpm} BPM</span>
    <span>${S.total?.toFixed(2)}s</span><span>${S.output?.width}×${S.output?.height}</span>
    <span>${S.clips.filter((c) => c.replaced).length}/${S.clips.length} 已换人</span>`;
  drawShots(); drawTimeline(); drawInspector(); drawOps(); drawVersions();
}

async function pollJob() {
  const j = S.job || {};
  const el = $("#job");
  el.className = "job " + (j.status || "");
  el.textContent = j.status === "running" ? "渲染中…" :
    j.status === "done" ? `完成 ${j.version} · ${j.elapsed}s` :
    j.status === "error" ? "失败" : "";
  if (j.status === "running") { setTimeout(refresh, 1200); }
  else if (j.status === "done" && !window._doneShown) {
    window._doneShown = true; $("#render").disabled = false; await refresh(true);
  }
}

async function refresh(keepVer) {
  S = await api("/api/state");
  if (keepVer && S.versions.length) curVer = S.versions[S.versions.length - 1].id;
  renderAll(); pollJob();
}

$("#render").addEventListener("click", async () => {
  $("#render").disabled = true; window._doneShown = false;
  await api("/api/render", { label: null });
  setTimeout(refresh, 600);
});

hookPlayer();
refresh();
