const API = window.API_URL, $ = id => document.getElementById(id);
const MAX_BATCH = 10;
const tracked = new Set(JSON.parse(localStorage.getItem("mediaIds") || "[]"));
let lastBatch = JSON.parse(localStorage.getItem("lastBatch") || "[]");
const save = () => { localStorage.setItem("mediaIds", JSON.stringify([...tracked])); localStorage.setItem("lastBatch", JSON.stringify(lastBatch)); };
const fmt = n => n == null ? "-" : n >= 1048576 ? (n / 1048576).toFixed(2) + " MB" : (n / 1024).toFixed(0) + " KB";
const dims = (w, h) => w && h ? `${w}x${h}` : "-";
const el = (tag, text, cls) => { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; };
// All server text is inserted with textContent only (never innerHTML).

async function api(path, opts) {
  const r = await fetch(API + path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

function putFile(url, file, onPct) {
  // Raw File body with its Content-Type (what storage-js sends for non-FormData bodies).
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("PUT", url);
    x.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    x.setRequestHeader("cache-control", "max-age=3600");
    x.upload.onprogress = e => { if (e.lengthComputable) onPct(Math.round(100 * e.loaded / e.total)); };
    x.onload = () => x.status >= 200 && x.status < 300 ? resolve() : reject(new Error("Storage upload failed: " + x.status));
    x.onerror = () => reject(new Error("Network error while uploading"));
    x.send(file);
  });
}

$("b").onclick = async () => {
  const files = [...$("f").files]; if (!files.length) return;
  if (files.length > MAX_BATCH) { $("msg").textContent = `Choose at most ${MAX_BATCH} files at a time.`; return; }
  $("b").disabled = true; lastBatch = []; const errors = [];
  for (let i = 0; i < files.length; i++) {       // one after another: gentle on the free tier
    const file = files[i], tag = `File ${i + 1}/${files.length}: `;
    try {
      $("msg").textContent = tag + "requesting upload...";
      const up = await api("/api/uploads", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: file.name, size: file.size, content_type: file.type }) });
      await putFile(up.signed_url, file, p => { $("msg").textContent = `${tag}uploading ${p}%`; });
      await api(`/api/uploads/${up.media_id}/complete`, { method: "POST" });
      tracked.add(up.media_id); lastBatch.push(up.media_id); save(); refresh();
    } catch (e) { errors.push(`${file.name}: ${e.message}`); }
  }
  $("b").disabled = false;
  $("msg").textContent = errors.length ? "Errors: " + errors.join(" | ") : "Uploaded. Processing...";
  refresh();
};

function beforeAfter(m) {
  const wrap = el("div", null, "ba");
  const mk = (url, label) => {
    const f = el("figure");
    let media;
    if (m.media_type === "video") { media = document.createElement("video"); media.controls = true; media.preload = "metadata"; }
    else media = document.createElement("img");
    if (url) media.src = url;
    f.append(media, el("figcaption", label));
    return f;
  };
  wrap.append(
    mk(m.original_url, `Before: ${fmt(m.original_size)}, ${dims(m.original_width, m.original_height)}`),
    mk(m.processed_url, `After: ${fmt(m.optimized_size)}, ${dims(m.optimized_width, m.optimized_height)}`));
  return wrap;
}

function report(m) {
  const rows = [
    ["Original size", fmt(m.original_size)], ["Optimized size", fmt(m.optimized_size)],
    ["Space saved", `${fmt(m.space_saved_bytes)} (${m.compression_percentage}% reduction)`],
    ["Original dimensions", dims(m.original_width, m.original_height)],
    ["Optimized dimensions", dims(m.optimized_width, m.optimized_height)],
    ["Processing time", `${m.processing_time}s`],
  ];
  if (m.psnr_db != null) rows.push(["Quality (PSNR)", `${m.psnr_db} dB, ${m.psnr_label}`]);
  if (m.settings_used && m.settings_used.reason) rows.push(["Settings chosen", m.settings_used.reason]);
  const t = el("table");
  for (const [k, v] of rows) { const tr = el("tr"); tr.append(el("th", k), el("td", v)); t.append(tr); }
  return t;
}

function summary(box, s, intro) {
  box.textContent = "";
  const line = (k, v) => { const d = el("div"); d.append(el("b", k), document.createTextNode(v)); box.append(d); };
  if (intro) box.append(el("div", intro, "note"));
  line("Files processed", String(s.files_processed));
  line("Failed", String(s.failed));
  if (s.in_progress) line("In progress", String(s.in_progress));
  line("Original total", fmt(s.total_original_bytes));
  line("Optimized total", fmt(s.total_optimized_bytes));
  line("Total storage saved", fmt(s.total_saved_bytes));
  line("Average reduction", `${s.average_reduction_percent}%`);
}

async function refreshSummaries() {
  try { summary($("dash"), await api("/api/stats"), "All uploads to this demo (no accounts, so this is everyone's total)."); }
  catch (e) { $("dash").textContent = "Dashboard unavailable: " + e.message; }
  if (lastBatch.length > 1) {
    try { $("batchbox").hidden = false; summary($("batch"), await api("/api/batch?ids=" + lastBatch.join(","))); } catch { $("batchbox").hidden = true; }
  } else $("batchbox").hidden = true;
}

let seq = 0, timer = null;
async function refresh() {
  const mine = ++seq; clearTimeout(timer);       // only the newest refresh may draw (no duplicate cards)
  const list = el("div");
  let pending = false;
  for (const id of [...tracked].reverse()) {
    let m; try { m = await api("/api/media/" + id); } catch { continue; }
    if (!["COMPLETED", "FAILED"].includes(m.status)) pending = true;
    const d = el("div", null, "card"), top = el("div", null, "row");
    if (m.thumbnail_url) { const i = el("img", null, "thumb"); i.src = m.thumbnail_url; top.append(i); }
    const t = el("div");
    t.append(el("div", m.original_filename), el("div", m.status, "s " + m.status));
    if (m.status === "COMPLETED") {
      const a = el("a", "download optimized file"); a.href = m.processed_url; a.target = "_blank"; t.append(a);
    }
    if (m.error_message) t.append(el("div", m.error_message));
    top.append(t); d.append(top);
    if (m.status === "COMPLETED") d.append(report(m), beforeAfter(m));
    list.append(d);
  }
  if (mine !== seq) return;
  $("list").replaceChildren(...list.childNodes);
  refreshSummaries();
  if (pending) timer = setTimeout(refresh, 3000);
}
refresh();
