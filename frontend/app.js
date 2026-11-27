/* app.js — Frontend Application Lead (Person 3)
 * AWS Serverless Media Transcoder and Thumbnail Pipeline
 * Supports:
 *   1. Batch uploads (up to 10 files)
 *   2. Optimization dashboard (/api/stats and /api/batch)
 *   3. Side-by-side Before/After comparison
 *   4. PSNR quality metrics and intelligent output policy display
 *   5. Seamless same-origin API integration with offline demo fallback
 */

const CFG = window.APP_CONFIG || {};
const API = (window.API_URL || CFG.API_URL || "").replace(/\/$/, "");
const MAX_BATCH = 10;
const POLL_MS = CFG.POLL_INTERVAL_MS || 2000;
const STEPS = ["client", "input", "worker", "engine", "output", "db", "cdn"];

const $ = id => document.getElementById(id);
const tracked = new Set(JSON.parse(localStorage.getItem("mediaIds") || "[]"));
let lastBatch = JSON.parse(localStorage.getItem("lastBatch") || "[]");
let selectedFiles = [];

const saveState = () => {
  localStorage.setItem("mediaIds", JSON.stringify([...tracked]));
  localStorage.setItem("lastBatch", JSON.stringify(lastBatch));
};

const fmtBytes = n => {
  if (n == null || isNaN(n)) return "–";
  if (n >= 1048576) return (n / 1048576).toFixed(2) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(1) + " KB";
  return n + " B";
};

const fmtDims = (w, h) => (w && h ? `${w}×${h}` : "–");

// Safe text creation (XSS prevention)
const el = (tag, text, cls) => {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (cls) e.className = cls;
  return e;
};

/* ---------- API Helper ---------- */
async function api(path, opts) {
  const r = await fetch(API + path, opts);
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.detail || r.statusText || `HTTP ${r.status}`);
  }
  return r.json();
}

/* ---------- Pipeline Stepper ---------- */
function setPipelineStep(name, state = "active") {
  const idx = STEPS.indexOf(name);
  document.querySelectorAll("#pipeline li").forEach((li, i) => {
    li.className = i < idx ? "done" : i === idx ? state : "";
  });
  const pct = ((idx + (state === "done" ? 1 : 0.5)) / STEPS.length) * 100;
  $("progressBar").style.width = Math.min(pct, 100) + "%";
}

function setPipelineStatus(s) {
  const badge = $("statusText");
  badge.textContent = s;
  badge.className = "status " + s;
}

function setPipelineComplete() {
  document.querySelectorAll("#pipeline li").forEach(li => (li.className = "done"));
  $("progressBar").style.width = "100%";
  setPipelineStatus("COMPLETED");
}

function setPipelineError(msg) {
  $("errorBox").textContent = "⚠ " + msg;
  $("errorBox").classList.remove("hidden");
  setPipelineStatus("FAILED");
  const active = document.querySelector("#pipeline li.active");
  if (active) active.className = "fail";
}

/* ---------- File Drag & Drop Selection ---------- */
const drop = $("dropZone");
["dragenter", "dragover"].forEach(e =>
  drop.addEventListener(e, ev => {
    ev.preventDefault();
    drop.classList.add("over");
  })
);
["dragleave", "drop"].forEach(e =>
  drop.addEventListener(e, ev => {
    ev.preventDefault();
    drop.classList.remove("over");
  })
);
drop.addEventListener("drop", ev => {
  if (ev.dataTransfer.files.length) handleFiles(ev.dataTransfer.files);
});
$("fileInput").addEventListener("change", ev => {
  if (ev.target.files.length) handleFiles(ev.target.files);
});

function handleFiles(fileList) {
  $("errorBox").classList.add("hidden");
  const files = [...fileList];
  if (!files.length) return;
  if (files.length > MAX_BATCH) {
    setPipelineError(`Please choose at most ${MAX_BATCH} files at a time.`);
    return;
  }
  selectedFiles = files;
  $("fileInfo").classList.remove("hidden");
  if (files.length === 1) {
    const f = files[0];
    $("fileInfo").textContent = `${f.name} (${fmtBytes(f.size)}) · ${f.type || "unknown mime"}`;
  } else {
    const totalSize = files.reduce((acc, f) => acc + f.size, 0);
    $("fileInfo").textContent = `${files.length} files selected (${fmtBytes(totalSize)} total)`;
  }
  $("uploadBtn").disabled = false;
  $("uploadMsg").textContent = "Ready to upload.";
  setPipelineStatus("IDLE");
  document.querySelectorAll("#pipeline li").forEach(li => (li.className = ""));
  $("progressBar").style.width = "0%";
}

/* ---------- Storage PUT Upload (with Progress) ---------- */
function putFileToStorage(url, file, onPct) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("PUT", url);
    x.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    x.setRequestHeader("cache-control", "max-age=3600");
    x.upload.onprogress = e => {
      if (e.lengthComputable && onPct) onPct(Math.round((100 * e.loaded) / e.total));
    };
    x.onload = () => {
      if (x.status >= 200 && x.status < 300) resolve();
      else reject(new Error(`Storage PUT failed: HTTP ${x.status}`));
    };
    x.onerror = () => reject(new Error("Network connection error during upload"));
    x.send(file);
  });
}

/* ---------- Upload & Processing Execution ---------- */
$("uploadBtn").onclick = async () => {
  if (!selectedFiles.length) return;
  $("uploadBtn").disabled = true;
  $("errorBox").classList.add("hidden");
  $("resultPanel").classList.add("hidden");

  const errors = [];
  lastBatch = [];

  for (let i = 0; i < selectedFiles.length; i++) {
    const file = selectedFiles[i];
    const prefix = selectedFiles.length > 1 ? `[${i + 1}/${selectedFiles.length}] ${file.name}: ` : "";

    try {
      setPipelineStep("client", "active");
      setPipelineStatus("UPLOADING");
      $("uploadMsg").textContent = prefix + "Requesting signed upload URL...";

      // 1. Request signed URL from backend
      const up = await api("/api/uploads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: file.name, size: file.size, content_type: file.type || "application/octet-stream" })
      });

      // 2. Upload file directly to storage
      setPipelineStep("input", "active");
      $("uploadMsg").textContent = prefix + "Uploading raw file to storage...";
      await putFileToStorage(up.signed_url, file, pct => {
        $("uploadMsg").textContent = `${prefix}Uploading ${pct}%`;
        $("progressBar").style.width = Math.min(15 + pct * 0.25, 40) + "%";
      });

      // 3. Mark upload completed
      setPipelineStep("worker", "active");
      setPipelineStatus("PROCESSING");
      $("uploadMsg").textContent = prefix + "Upload complete. Notifying processing engine...";
      await api(`/api/uploads/${up.media_id}/complete`, { method: "POST" });

      tracked.add(up.media_id);
      lastBatch.push(up.media_id);
      saveState();

      // 4. Poll for results
      setPipelineStep("engine", "active");
      $("uploadMsg").textContent = prefix + "Processing media (Pillow / FFmpeg)...";
      const record = await pollStatus(up.media_id);

      if (record && record.status === "COMPLETED") {
        setPipelineComplete();
        $("uploadMsg").textContent = prefix + "Completed successfully!";
        renderResult(record);
      } else if (record && record.status === "FAILED") {
        throw new Error(record.error_message || "Processing failed");
      }
    } catch (e) {
      errors.push(`${file.name}: ${e.message}`);
      setPipelineError(e.message);
    }
  }

  $("uploadBtn").disabled = false;
  if (errors.length) {
    $("uploadMsg").textContent = "Errors: " + errors.join(" | ");
  } else {
    $("uploadMsg").textContent = "All files processed.";
  }

  refreshDashboard();
  refreshHistory();
};

/* ---------- Polling Media Status ---------- */
async function pollStatus(mediaId, maxAttempts = 30) {
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    await new Promise(r => setTimeout(r, POLL_MS));
    try {
      setPipelineStep("db", "active");
      const record = await api(`/api/media/${mediaId}`);
      if (record.status === "PROCESSING") {
        setPipelineStep("engine", "active");
      } else if (record.status === "COMPLETED" || record.status === "FAILED") {
        setPipelineStep("cdn", "done");
        return record;
      }
    } catch (err) {
      console.warn("Poll attempt failed:", err);
    }
  }
  throw new Error("Processing timed out after 60 seconds.");
}

/* ---------- Render Active Comparison Result ---------- */
function renderResult(m) {
  $("resultPanel").classList.remove("hidden");

  // Feature Badges (PSNR & Policy)
  const badgesBox = $("featureBadges");
  badgesBox.replaceChildren();

  if (m.psnr_db != null) {
    const cls = m.psnr_db >= 37 ? "pill-badge pill-psnr excellent" : "pill-badge pill-psnr";
    badgesBox.appendChild(el("span", `PSNR: ${m.psnr_db} dB (${m.psnr_label || "Score"})`, cls));
  }
  if (m.settings_used && m.settings_used.reason) {
    badgesBox.appendChild(el("span", `Policy: ${m.settings_used.reason}`, "pill-badge pill-policy"));
  }

  // Views (Before, After, Thumbnail)
  const isVideo = m.media_type === "video";
  const mkMedia = (url, isThumb = false) => {
    if (!url) return el("div", "Preview unavailable", "muted");
    if (isVideo && !isThumb) {
      const v = document.createElement("video");
      v.src = url;
      v.controls = true;
      v.preload = "metadata";
      return v;
    }
    const img = document.createElement("img");
    img.src = url;
    img.alt = "";
    return img;
  };

  const beforeView = $("beforeView");
  beforeView.replaceChildren(mkMedia(m.original_url));
  $("beforeSize").textContent = `${fmtBytes(m.original_size)} (${fmtDims(m.original_width, m.original_height)})`;

  const afterView = $("afterView");
  afterView.replaceChildren(mkMedia(m.processed_url));
  $("afterSize").textContent = `${fmtBytes(m.optimized_size)} (${fmtDims(m.optimized_width, m.optimized_height)})`;

  const thumbView = $("thumbView");
  thumbView.replaceChildren(mkMedia(m.thumbnail_url, true));
  $("thumbSize").textContent = "200×200 Thumbnail";

  // Stats Grid
  $("sOriginal").textContent = fmtBytes(m.original_size);
  $("sOptimized").textContent = fmtBytes(m.optimized_size);
  const saved = (m.original_size || 0) - (m.optimized_size || 0);
  $("sSaved").textContent = `${fmtBytes(saved > 0 ? saved : 0)}`;
  $("sReduction").textContent = `${m.compression_percentage != null ? m.compression_percentage : 0}%`;
  $("sDims").textContent = `${fmtDims(m.original_width, m.original_height)} → ${fmtDims(m.optimized_width, m.optimized_height)}`;
  $("sPsnr").textContent = m.psnr_db != null ? `${m.psnr_db} dB` : "N/A (Video)";
  $("sTime").textContent = `${m.processing_time || "–"}s`;

  // Links
  const linksBox = $("links");
  linksBox.replaceChildren();
  if (m.processed_url) {
    const a1 = el("a", "⬇ Download Optimized File");
    a1.href = m.processed_url;
    a1.target = "_blank";
    a1.download = "";
    linksBox.appendChild(a1);
  }
  if (m.thumbnail_url) {
    const a2 = el("a", "⬇ Download Thumbnail");
    a2.href = m.thumbnail_url;
    a2.target = "_blank";
    a2.download = "";
    linksBox.appendChild(a2);
  }

  // JSON Details
  $("recordJson").textContent = JSON.stringify(m, null, 2);
}

/* ---------- Dashboard Refresh ---------- */
async function refreshDashboard() {
  try {
    const s = await api("/api/stats");
    $("dProcessed").textContent = String(s.files_processed || 0);
    $("dInProgress").textContent = String(s.in_progress || 0);
    $("dFailed").textContent = String(s.failed || 0);
    $("dOriginal").textContent = fmtBytes(s.total_original_bytes || 0);
    $("dOptimized").textContent = fmtBytes(s.total_optimized_bytes || 0);
    $("dSaved").textContent = fmtBytes(s.total_saved_bytes || 0);
    $("dReduction").textContent = `${s.overall_reduction_percent || 0.0}% (avg: ${s.average_reduction_percent || 0.0}%)`;
    $("modeBadge").textContent = "☁ Live Mode · Connected to Media Pipeline";
    $("modeBadge").style.borderColor = "var(--ok)";
  } catch (err) {
    console.warn("Stats API error:", err);
    $("modeBadge").textContent = "⚠ Server offline or credentials missing (demo available)";
  }

  // Batch stats if last batch has multiple files
  if (lastBatch.length > 1) {
    try {
      const b = await api("/api/batch?ids=" + lastBatch.join(","));
      $("batchBox").classList.remove("hidden");
      $("batchCount").textContent = String(b.requested || lastBatch.length);
      const bGrid = $("batchGrid");
      bGrid.replaceChildren();

      const addStat = (label, val, good = false) => {
        const c = el("div", null, good ? "dash-card good" : "dash-card");
        c.appendChild(el("span", label));
        c.appendChild(el("b", val));
        bGrid.appendChild(c);
      };
      addStat("Batch Processed", `${b.files_processed || 0}/${b.requested || lastBatch.length}`);
      addStat("Original Size", fmtBytes(b.total_original_bytes));
      addStat("Optimized Size", fmtBytes(b.total_optimized_bytes));
      addStat("Space Saved", fmtBytes(b.total_saved_bytes), true);
      addStat("Reduction", `${b.overall_reduction_percent || 0}%`, true);
    } catch (e) {
      $("batchBox").classList.add("hidden");
    }
  } else {
    $("batchBox").classList.add("hidden");
  }
}

/* ---------- History Table Refresh ---------- */
async function refreshHistory() {
  const ids = [...tracked].reverse();
  const tbody = $("historyBody");
  if (!ids.length) return;

  const rows = [];
  for (const id of ids.slice(0, 15)) {
    try {
      const m = await api(`/api/media/${id}`);
      const tr = el("tr");

      // Thumb
      const tdThumb = el("td");
      if (m.thumbnail_url) {
        const img = el("img");
        img.src = m.thumbnail_url;
        tdThumb.appendChild(img);
      } else {
        tdThumb.appendChild(el("span", "–", "muted"));
      }
      tr.appendChild(tdThumb);

      // Filename
      tr.appendChild(el("td", m.original_filename || id));

      // Type
      tr.appendChild(el("td", (m.media_type || "image").toUpperCase()));

      // Status
      const tdStatus = el("td");
      tdStatus.appendChild(el("span", m.status, `status ${m.status}`));
      tr.appendChild(tdStatus);

      // Sizes & Reduction
      tr.appendChild(el("td", fmtBytes(m.original_size)));
      tr.appendChild(el("td", fmtBytes(m.optimized_size)));
      tr.appendChild(el("td", m.compression_percentage != null ? `${m.compression_percentage}%` : "–"));

      // PSNR
      tr.appendChild(el("td", m.psnr_db != null ? `${m.psnr_db} dB` : "–"));

      // Settings
      tr.appendChild(el("td", m.settings_used && m.settings_used.reason ? m.settings_used.reason : "Default"));

      // Action
      const tdAction = el("td");
      if (m.status === "COMPLETED") {
        const btnView = el("button", "View Details", "btn small ghost");
        btnView.onclick = () => renderResult(m);
        tdAction.appendChild(btnView);
      } else if (m.status === "FAILED") {
        tdAction.appendChild(el("span", m.error_message || "Error", "muted"));
      }
      tr.appendChild(tdAction);

      rows.push(tr);
    } catch {
      continue;
    }
  }

  if (rows.length) {
    tbody.replaceChildren(...rows);
  }
}

// Event Listeners
$("refreshStatsBtn").onclick = refreshDashboard;
$("refreshHistoryBtn").onclick = refreshHistory;

// Initial Load
refreshDashboard();
refreshHistory();
