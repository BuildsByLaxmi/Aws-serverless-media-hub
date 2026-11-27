const API = window.API_URL, $ = id => document.getElementById(id);
const tracked = new Set(JSON.parse(localStorage.getItem("mediaIds") || "[]"));
const save = () => localStorage.setItem("mediaIds", JSON.stringify([...tracked]));
const fmt = n => n == null ? "-" : (n / 1024).toFixed(0) + " KB";

async function api(path, opts) {
  const r = await fetch(API + path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

$("b").onclick = async () => {
  const file = $("f").files[0]; if (!file) return;
  try {
    $("msg").textContent = "Requesting upload...";
    const up = await api("/api/uploads", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: file.name, size: file.size, content_type: file.type }) });
    $("msg").textContent = "Uploading...";
    // Same request supabase-js uploadToSignedUrl makes
    const fd = new FormData(); fd.append("cacheControl", "3600"); fd.append("", file);
    const put = await fetch(up.signed_url, { method: "PUT", body: fd, headers: { "x-upsert": "false" } });
    if (!put.ok) throw new Error("Storage upload failed: " + put.status);
    await api(`/api/uploads/${up.media_id}/complete`, { method: "POST" });
    tracked.add(up.media_id); save(); $("msg").textContent = "Uploaded. Processing...";
    refresh();
  } catch (e) { $("msg").textContent = "Error: " + e.message; }
};

async function refresh() {
  const list = $("list"); list.textContent = "";
  let pending = false;
  for (const id of [...tracked].reverse()) {
    let m; try { m = await api("/api/media/" + id); } catch { continue; }
    if (!["COMPLETED", "FAILED"].includes(m.status)) pending = true;
    const d = document.createElement("div"); d.className = "card";
    if (m.thumbnail_url) { const i = document.createElement("img"); i.src = m.thumbnail_url; d.append(i); }
    const t = document.createElement("div");
    const name = document.createElement("div"); name.textContent = m.original_filename;
    const st = document.createElement("div"); st.className = "s " + m.status; st.textContent = m.status;
    t.append(name, st);
    if (m.status === "COMPLETED") {
      const info = document.createElement("div");
      info.textContent = `${fmt(m.original_size)} -> ${fmt(m.optimized_size)} (-${m.compression_percentage}%), ${m.processing_time}s `;
      const a = document.createElement("a"); a.href = m.processed_url; a.textContent = "view / download"; a.target = "_blank";
      info.append(a); t.append(info);
    }
    if (m.error_message) { const e = document.createElement("div"); e.textContent = m.error_message; t.append(e); }
    d.append(t); list.append(d);
  }
  if (pending) setTimeout(refresh, 3000);
}
refresh();
