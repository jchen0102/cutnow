const $ = (s) => document.querySelector(s);
let S = null, sel = 0, curVer = null;

const fmt = (n) => (n ?? 0).toFixed(2) + "s";
const mb = (n) => ((n || 0) / 1e6).toFixed(1) + "MB";

async function api(path, body) {
  const r = await fetch(path, body ? {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
  } : undefined);
  return r.json();
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("show"), 2400);
}

function sourceName() {
  const p = String(S?.source || "").split("/").pop();
  return p ? p.replace(/\.[^.]+$/, "") : "未选素材";
}

function drawHeader() {
  const n = (S.versions || []).length;
  $("#now").textContent = `${sourceName()} · ${(S.total || 0).toFixed(1)}s · ${n ? "第 " + n + " 版" : "未渲染"}`;
  $("#export").disabled = !n;
  const running = S.job?.status === "running";
  $("#render").disabled = running;
  $("#render").textContent = running ? "渲染中…" : "渲染";
}

function drawClips() {
  const clips = S.clips || [];
  $("#cnt").textContent = clips.length ? clips.length + " 段" : "";
  $("#clips").innerHTML = clips.map((c, i) => `
    <div class="clip ${i === sel ? "sel" : ""}" data-i="${i}">
      <img src="${c.thumb}" alt="">
      <div class="m">
        <b>${c.role || "第 " + (i + 1) + " 刀"}</b>
        <span>${fmt(c.start)} 起 · ${c.dur.toFixed(2)}s${c.beats ? " · " + c.beats + " 拍" : ""}</span>
      </div>
      <div class="n">${i + 1}</div>
    </div>`).join("") || '<div class="dim">没有镜头</div>';
  $("#clips").querySelectorAll(".clip").forEach((el) => el.addEventListener("click", () => {
    sel = +el.dataset.i; drawClips(); drawStrip(); drawInspector(); seekTo(sel);
  }));
}

function drawStrip() {
  const total = S.total || 1;
  const clips = S.clips || [];
  $("#strip").innerHTML = clips.map((c, i) => {
    const w = Math.max(2, (c.dur / total) * 100);
    return `<div class="seg ${i === sel ? "sel" : ""}" data-i="${i}" style="width:${w}%">
      <span>${i + 1}</span><i>${c.dur.toFixed(1)}s</i></div>`;
  }).join("");
  $("#strip").querySelectorAll(".seg").forEach((el) => el.addEventListener("click", () => {
    sel = +el.dataset.i; drawClips(); drawStrip(); drawInspector(); seekTo(sel);
  }));
}

function seekTo(i) {
  const c = (S.clips || [])[i];
  if (!c) return;
  const v = $("#player");
  try { v.currentTime = (c.at || 0) + 0.05; } catch (e) {}
}

function drawInspector() {
  const c = (S.clips || [])[sel];
  const box = $("#inspector");
  if (!c) { box.innerHTML = '<div class="dim">先在左边选一条</div>'; return; }
  if (!c.beats) {
    box.innerHTML = `
      <div class="row"><label>类型</label><b>${c.role || "文字卡"}</b></div>
      <div class="row"><label>时长</label><b>${c.dur.toFixed(2)}s</b></div>
      <div class="tiny">文字卡没有拍数和源起点可改。</div>`;
    return;
  }
  box.innerHTML = `
    <div class="row"><label>第几刀</label><b>${sel + 1} / ${S.clips.length}</b>
      <span class="dim" style="margin-left:auto">${c.role || ""}</span></div>
    <div class="row"><label>拍数</label>
      <select id="beats">${[2, 4, 6, 8, 12, 16].map((b) =>
        `<option value="${b}" ${b === c.beats ? "selected" : ""}>${b} 拍 · ${(b * 60 / S.bpm).toFixed(2)}s</option>`).join("")}</select>
    </div>
    <div class="row"><label>源起点</label>
      <input id="start" type="number" step="0.1" value="${c.start.toFixed(2)}"></div>
    <div class="row"><label></label><button id="apply" class="primary">应用改动</button></div>`;
  $("#apply").addEventListener("click", async () => {
    const r = await api("/api/clip", { index: sel, beats: +$("#beats").value, start: +$("#start").value });
    if (r.error) return toast(r.error);
    S = r; renderAll(); toast("已改草稿，点「渲染」出片");
  });
}

function drawQc() {
  const q = S.qc, box = $("#qc");
  if (!q) { box.className = "qcbar"; box.textContent = "渲染后这里显示质检"; return; }
  if (q.pass === null) { box.className = "qcbar"; box.textContent = "质检失败：" + (q.error || ""); return; }
  const c = q.checks || {};
  box.className = "qcbar " + (q.pass ? "pass" : "fail");
  box.innerHTML = `<b>${q.pass ? "质检通过" : "质检未通过"}</b>
    <span>时长 ${(c.duration?.value ?? 0).toFixed(2)}s</span>
    <span>响度 ${c.loudness?.lufs == null ? "—" : c.loudness.lufs.toFixed(1)}</span>
    <span>黑帧 ${c.black_frames?.count ?? 0}</span>
    ${(q.failed || []).length ? `<span class="bad">${q.failed.join(" / ")}</span>` : ""}`;
}

function play(url) {
  const v = $("#player");
  $("#empty").style.display = "none";
  v.poster = "/api/poster";
  v.src = url;
  v.load();
}

function renderAll() {
  drawHeader(); drawClips(); drawStrip(); drawInspector(); drawQc();
}

async function refresh() {
  S = await api("/api/state");
  if (!curVer && (S.versions || []).length) {
    curVer = S.versions[S.versions.length - 1].id;
    play(S.versions[S.versions.length - 1].url);
  }
  renderAll();
  if (S.job?.status === "running") setTimeout(refresh, 1200);
  else if (S.job?.status === "done" && !window._doneShown) {
    window._doneShown = true;
    S = await api("/api/state");
    const last = (S.versions || []).slice(-1)[0];
    if (last) play(last.url);
    renderAll(); toast("渲染完成");
  }
}

/* ---------- 历史 / 高级 ---------- */

async function openHistory() {
  $("#history").classList.remove("hidden");
  const body = $("#historyBody");
  body.innerHTML = '<div class="dim">读取中…</div>';
  let rec = { items: [] };
  try { rec = await api("/api/records"); } catch (e) {}
  body.innerHTML = `
    <h3>当前在剪</h3>
    <select id="edlsel">${(S.edl_options || []).map((o) =>
      `<option value="${o.file}" ${o.file === S.edl ? "selected" : ""}>${o.id} · ${(o.total || 0).toFixed(1)}s</option>`).join("")}</select>

    <h3>版本</h3>
    <div class="hlist">${(S.versions || []).slice().reverse().map((v) =>
      `<div class="hver" data-url="${v.url}"><b>${v.id}</b><span>${mb(v.bytes)} · ${v.at}</span></div>`).join("")
      || '<div class="dim">—</div>'}</div>

    <h3>画面 / 字幕</h3>
    <div class="hrow"><button id="aspect">${S.vertical ? "切回横版 16:9" : "切竖版 9:16"}</button></div>
    <div class="hrow"><input id="subs" placeholder="用 / 或逗号分句" value="${S.subs_text || ""}">
      <button id="subsApply">应用</button></div>

    <h3>审批</h3>
    <div class="hlist">${(rec.items || []).map((it) => `
      <div class="hver"><b>${it.label}</b>
        <span>${it.status === "delivered" ? "已交付" : it.status === "approved" ? "已审批" : "未审批"}</span>
        ${it.status === "unapproved" ? `<button data-approve="${it.run_id}">审批</button>` : ""}
        ${it.status === "approved" ? `<button data-deliver="${it.run_id}">交付</button>` : ""}
      </div>`).join("") || '<div class="dim">还没有渲染记录</div>'}</div>`;

  $("#edlsel").addEventListener("change", async (e) => {
    const r = await api("/api/switch", { edl: e.target.value });
    if (r.error) return toast(r.error);
    S = r; sel = 0; renderAll(); openHistory();
  });
  body.querySelectorAll(".hver[data-url]").forEach((el) =>
    el.addEventListener("click", () => play(el.dataset.url)));
  $("#aspect").addEventListener("click", async () => {
    const r = await api("/api/aspect", { vertical: !S.vertical });
    if (r.error) return toast(r.error);
    S = r; renderAll(); openHistory();
  });
  $("#subsApply").addEventListener("click", async () => {
    const r = await api("/api/subs", { text: $("#subs").value });
    if (r.error) return toast(r.error);
    S = r; renderAll(); openHistory();
  });
  body.querySelectorAll("[data-approve]").forEach((el) => el.addEventListener("click", async () => {
    const by = (prompt("审批人名字") || "").trim();
    if (!by) return;
    const r = await api("/api/approve", { run_id: el.dataset.approve, by });
    if (r.error) return toast(r.error);
    openHistory();
  }));
  body.querySelectorAll("[data-deliver]").forEach((el) => el.addEventListener("click", async () => {
    const by = (prompt("交付人名字") || "").trim();
    if (!by) return;
    const r = await api("/api/deliver", { run_id: el.dataset.deliver, by });
    if (r.error) return toast(r.error);
    openHistory();
  }));
}

/* ---------- 事件 ---------- */

$("#render").addEventListener("click", async () => {
  window._doneShown = false;
  $("#render").disabled = true; $("#render").textContent = "渲染中…";
  const r = await api("/api/render", {});
  if (r.error) return toast(r.error);
  setTimeout(refresh, 800);
});

$("#reselect").addEventListener("click", async () => {
  if (!confirm("按当前素材重新挑一遍镜头？会覆盖当前草稿（不会自动出片）。")) return;
  $("#reselect").disabled = true; $("#reselect").textContent = "生成中…";
  const r = await api("/api/reselect", { target_seconds: S.total || 12 });
  $("#reselect").disabled = false; $("#reselect").textContent = "重新生成";
  if (r.error) return toast(r.error);
  S = r; sel = 0; renderAll(); toast("新草稿好了，点「渲染」出片");
});

$("#export").addEventListener("click", () => {
  const v = (S.versions || []).slice(-1)[0];
  if (!v) return toast("还没有成片");
  const a = document.createElement("a");
  a.href = v.url; a.download = v.id + ".mp4"; a.click();
});

$("#historyBtn").addEventListener("click", () => {
  const h = $("#history");
  if (h.classList.contains("hidden")) openHistory();
  else h.classList.add("hidden");
});
$("#historyClose").addEventListener("click", () => $("#history").classList.add("hidden"));

refresh();
