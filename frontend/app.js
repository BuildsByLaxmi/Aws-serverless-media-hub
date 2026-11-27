/* app.js — Frontend Application Lead (Person 3)
 * AWS Serverless Media Transcoder and Thumbnail Pipeline
 * Supports:
 *   1. Batch uploads (up to 10 files) with concurrency & progress
 *   2. Real-time 7-stage serverless status polling
 *   3. Advanced Section 3: Before & After comparison with Chart.js size bar,
 *      PSNR quality meter (image only), compression gauge, and resolution telemetry
 *   4. Advanced Section 4: Professional Optimization Dashboard with 5 interactive Chart.js graphs
 *      (Storage, Daily Timeline, Media Types, Format Distribution, and PSNR Quality Tiers)
 *   5. Advanced Section 5: Media Management Interface with search, filtering, multi-column sorting,
 *      pagination, detailed inspection modal, and RFC-4180 CSV export
 *   6. Offline demonstration fallback mode with zero console errors
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

// History management state
let allHistoryItems = [];
let currentPage = 1;
let pageSize = 10;

// Chart.js instances (matching teammate's Chart.js architecture)
let itemSizeChartInstance = null;
let storageChartInstance = null;
let dailyActivityChartInstance = null;
let typeDistChartInstance = null;
let formatDistChartInstance = null;
let qualityDistChartInstance = null;

const saveState = () => {
  localStorage.setItem("mediaIds", JSON.stringify([...tracked]));
  localStorage.setItem("lastBatch", JSON.stringify(lastBatch));
};

const fmtBytes = n => {
  if (n == null || isNaN(n)) return "–";
  if (n >= 1073741824) return (n / 1073741824).toFixed(2) + " GB";
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
  $("progressBar").style.width = pct + "%";
}

function setPipelineStatus(status) {
  const elStatus = $("statusText");
  elStatus.textContent = status;
  elStatus.className = `status ${status}`;
}

function resetPipeline() {
  document.querySelectorAll("#pipeline li").forEach(li => (li.className = ""));
  $("progressBar").style.width = "0%";
  $("errorBox").classList.add("hidden");
  $("errorBox").textContent = "";
  setPipelineStatus("IDLE");
}

function setPipelineError(msg) {
  setPipelineStatus("FAILED");
  const eb = $("errorBox");
  eb.textContent = msg;
  eb.classList.remove("hidden");
}

/* ---------- Signed Upload PUT ---------- */
function putFileToStorage(url, file, onPct) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    xhr.setRequestHeader("cache-control", "max-age=3600");
    xhr.upload.onprogress = e => {
      if (e.lengthComputable && onPct) {
        onPct(Math.round((100 * e.loaded) / e.total));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(`Storage PUT failed with status ${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error("Network error during file upload"));
    xhr.send(file);
  });
}

/* ---------- Upload Controller ---------- */
async function handleUpload() {
  if (!selectedFiles.length) return;
  if (selectedFiles.length > MAX_BATCH) {
    setPipelineError(`Please choose at most ${MAX_BATCH} files at a time.`);
    return;
  }

  const btn = $("uploadBtn");
  const msg = $("uploadMsg");
  btn.disabled = true;
  resetPipeline();
  setPipelineStatus("UPLOADING");
  setPipelineStep("client", "done");
  setPipelineStep("input", "active");

  lastBatch = [];
  const errors = [];
  const total = selectedFiles.length;

  for (let i = 0; i < total; i++) {
    const file = selectedFiles[i];
    const prefix = total > 1 ? `[${i + 1}/${total}] ` : "";
    try {
      msg.textContent = `${prefix}Requesting pre-signed URL...`;
      const up = await api("/api/uploads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename: file.name,
          size: file.size,
          content_type: file.type || "application/octet-stream"
        })
      });

      msg.textContent = `${prefix}Uploading to private bucket (0%)...`;
      await putFileToStorage(up.signed_url, file, p => {
        msg.textContent = `${prefix}Uploading to private bucket (${p}%)...`;
      });

      msg.textContent = `${prefix}Finalizing upload...`;
      await api(`/api/uploads/${up.media_id}/complete`, { method: "POST" });

      tracked.add(up.media_id);
      lastBatch.push(up.media_id);
      saveState();
    } catch (err) {
      errors.push(`${file.name}: ${err.message}`);
    }
  }

  btn.disabled = false;
  if (errors.length) {
    setPipelineError(`Upload issues: ${errors.join(" | ")}`);
    msg.textContent = "Upload completed with warnings.";
  } else {
    msg.textContent = `Successfully uploaded ${total} file(s). Processing...`;
    setPipelineStep("input", "done");
    setPipelineStep("worker", "active");
    setPipelineStatus("PROCESSING");
  }

  selectedFiles = [];
  $("fileInput").value = "";
  $("fileInfo").classList.add("hidden");
  refreshAll();

  if (lastBatch.length) {
    pollMediaItem(lastBatch[lastBatch.length - 1]);
  }
}

/* ---------- Active Item Polling ---------- */
async function pollMediaItem(mediaId) {
  let attempts = 0;
  const maxAttempts = 60; // 2 minutes max

  const interval = setInterval(async () => {
    attempts++;
    try {
      const m = await api(`/api/media/${mediaId}`);
      if (m.status === "PROCESSING") {
        setPipelineStep("worker", "done");
        setPipelineStep("engine", "active");
        setPipelineStatus("PROCESSING");
      } else if (m.status === "COMPLETED") {
        clearInterval(interval);
        setPipelineStep("engine", "done");
        setPipelineStep("output", "done");
        setPipelineStep("db", "done");
        setPipelineStep("cdn", "done");
        setPipelineStatus("COMPLETED");
        $("progressBar").style.width = "100%";
        $("uploadMsg").textContent = "Processing complete! Telemetry recorded.";
        renderActiveComparison(m);
        refreshAll();
      } else if (m.status === "FAILED") {
        clearInterval(interval);
        setPipelineError(m.error_message || "Media processing failed.");
        renderActiveComparison(m);
        refreshAll();
      }
    } catch {
      // transient network poll error
    }

    if (attempts >= maxAttempts) {
      clearInterval(interval);
      setPipelineStatus("TIMEOUT");
    }
  }, POLL_MS);
}

/* ---------- Section 3: Before & After View & Advanced Analytics ---------- */
function renderActiveComparison(m) {
  const panel = $("resultPanel");
  panel.classList.remove("hidden");

  // Feature Badges
  const badges = $("featureBadges");
  badges.textContent = "";

  if (m.media_type === "image" && m.psnr_db != null) {
    const isEx = m.psnr_db >= 35;
    badges.appendChild(el("span", `PSNR: ${m.psnr_db} dB (${m.psnr_label || "Verified"})`, `pill-badge pill-psnr ${isEx ? "excellent" : ""}`));
  } else if (m.media_type === "video") {
    badges.appendChild(el("span", "Video: FFmpeg H.264 CRF 23", "pill-badge pill-psnr"));
  }

  if (m.settings_used && m.settings_used.reason) {
    badges.appendChild(el("span", `Policy: ${m.settings_used.reason}`, "pill-badge pill-policy"));
  }

  // Views
  const bView = $("beforeView");
  const aView = $("afterView");
  const tView = $("thumbView");
  bView.textContent = "";
  aView.textContent = "";
  tView.textContent = "";

  const isVideo = m.media_type === "video";
  const makeMediaEl = (url, isVideoAsset) => {
    if (!url) {
      const ph = el("div", "Asset not generated", "muted");
      ph.style.padding = "40px 10px";
      return ph;
    }
    if (isVideoAsset) {
      const v = document.createElement("video");
      v.src = url;
      v.controls = true;
      v.preload = "metadata";
      return v;
    }
    const img = document.createElement("img");
    img.src = url;
    img.alt = "Processed output";
    return img;
  };

  bView.appendChild(makeMediaEl(m.original_url, isVideo));
  aView.appendChild(makeMediaEl(m.processed_url, isVideo));
  tView.appendChild(makeMediaEl(m.thumbnail_url, false));

  // Captions & Sizes
  $("beforeCaption").textContent = `Original (${m.media_type || "media"})`;
  $("beforeSize").textContent = fmtBytes(m.original_size);
  $("afterCaption").textContent = `Optimized (${(m.settings_used?.format || (isVideo ? "mp4" : "webp")).toUpperCase()})`;
  $("afterSize").textContent = fmtBytes(m.optimized_size);
  $("thumbSize").textContent = m.thumbnail_url ? "200×200 thumb" : "–";

  // Quick Stats Row
  $("sOriginal").textContent = fmtBytes(m.original_size);
  $("sOptimized").textContent = fmtBytes(m.optimized_size);
  $("sSaved").textContent = fmtBytes(m.space_saved_bytes);
  $("sReduction").textContent = m.compression_percentage != null ? `${m.compression_percentage}%` : "–";
  $("sDims").textContent = `${fmtDims(m.original_width, m.original_height)} ➔ ${fmtDims(m.optimized_width, m.optimized_height)}`;
  
  if (isVideo) {
    $("sPsnr").textContent = "N/A (Video)";
  } else {
    $("sPsnr").textContent = m.psnr_db != null ? `${m.psnr_db} dB (${m.psnr_label})` : "–";
  }
  $("sTime").textContent = m.processing_time != null ? `${m.processing_time}s` : "–";

  // Section 3 Advanced Visual Analytics Cards
  renderItemAnalytics(m);

  // Asset links
  const links = $("links");
  links.textContent = "";
  if (m.original_url) {
    const a = el("a", "Download Original", "");
    a.href = m.original_url;
    a.download = m.original_filename || "original";
    a.target = "_blank";
    links.appendChild(a);
  }
  if (m.processed_url) {
    const a = el("a", "Download Optimized Output", "");
    a.href = m.processed_url;
    a.download = `optimized_${m.original_filename || "output"}`;
    a.target = "_blank";
    links.appendChild(a);
  }
  if (m.thumbnail_url) {
    const a = el("a", "Download Thumbnail", "");
    a.href = m.thumbnail_url;
    a.download = `thumb_${m.original_filename || "thumb.webp"}`;
    a.target = "_blank";
    links.appendChild(a);
  }

  $("recordJson").textContent = JSON.stringify(m, null, 2);
}

/* ---------- Section 3 Advanced Charts & Meters ---------- */
function renderItemAnalytics(m) {
  const origKb = m.original_size ? Math.round(m.original_size / 1024) : 0;
  const optKb = m.optimized_size ? Math.round(m.optimized_size / 1024) : 0;
  const savedKb = Math.max(0, origKb - optKb);

  // 1. Size Comparison Chart
  const ctx = $("itemSizeChart")?.getContext("2d");
  if (ctx && window.Chart) {
    if (itemSizeChartInstance) itemSizeChartInstance.destroy();
    itemSizeChartInstance = new Chart(ctx, {
      type: "bar",
      data: {
        labels: ["Original", "Optimized", "Saved"],
        datasets: [{
          data: [origKb, optKb, savedKb],
          backgroundColor: ["#232f3e", "#2f6fde", "#1e9e5a"],
          borderRadius: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: c => ` ${c.parsed.y.toLocaleString()} KB`
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            ticks: { callback: v => v + " KB", font: { size: 10 } }
          },
          x: { ticks: { font: { size: 11, weight: "bold" } } }
        }
      }
    });
  }

  // 2. PSNR Meter (Images only, transparent explanation for video)
  const psnrVal = $("itemPsnrVal");
  const psnrFill = $("itemPsnrFill");
  const psnrNote = $("itemPsnrNote");

  if (m.media_type === "video") {
    psnrVal.textContent = "N/A for Video";
    psnrVal.style.color = "var(--muted)";
    psnrFill.style.width = "0%";
    psnrNote.textContent = "PSNR is an image spatial fidelity metric. Video stream optimized using perceptual H.264 CRF encoding.";
  } else if (m.psnr_db != null) {
    psnrVal.textContent = `${m.psnr_db} dB`;
    psnrVal.style.color = m.psnr_db >= 35 ? "var(--ok)" : m.psnr_db >= 30 ? "var(--info)" : "var(--warn)";
    // Normalize 20 dB to 45 dB range
    const pct = Math.min(100, Math.max(0, ((m.psnr_db - 20) / 25) * 100));
    psnrFill.style.width = `${pct}%`;
    psnrNote.textContent = `Fidelity Classification: ${m.psnr_label || "Verified"} (ITU-R standard threshold: 30 dB)`;
  } else {
    psnrVal.textContent = "–";
    psnrFill.style.width = "0%";
    psnrNote.textContent = "Quality score calculating...";
  }

  // 3. Compression Savings Bar
  const pct = m.compression_percentage != null ? m.compression_percentage : 0;
  $("itemReductionVal").textContent = `${pct}%`;
  $("itemReductionBar").style.width = `${Math.min(100, Math.max(0, pct))}%`;
  $("itemSavingsBytesNote").textContent = `${fmtBytes(m.space_saved_bytes || 0)} space saved on disk`;

  // 4. Dimensions & Execution Telemetry
  $("itemOrigDim").textContent = fmtDims(m.original_width, m.original_height);
  $("itemOptDim").textContent = fmtDims(m.optimized_width, m.optimized_height);
  $("itemProcTime").textContent = m.processing_time != null ? `${m.processing_time}s` : "–";
  $("itemPolicyNote").textContent = m.settings_used?.reason || (m.media_type === "video" ? "720p H.264 baseline" : "Adaptive WebP tier");
}

/* ---------- Section 4: Optimization Dashboard & 5 Charts ---------- */
async function refreshDashboard() {
  let stats;
  try {
    stats = await api("/api/stats");
  } catch (err) {
    console.warn("Failed to load /api/stats:", err);
    return;
  }

  // KPI Summary Cards
  $("dTotal").textContent = stats.total_files || 0;
  $("dProcessed").textContent = stats.files_processed || 0;
  $("dInProgress").textContent = stats.in_progress || 0;
  $("dFailed").textContent = stats.failed || 0;
  $("dOriginal").textContent = fmtBytes(stats.total_original_bytes || 0);
  $("dOptimized").textContent = fmtBytes(stats.total_optimized_bytes || 0);
  $("dSaved").textContent = fmtBytes(stats.total_saved_bytes || 0);
  $("dReduction").textContent = `${stats.average_reduction_percent || 0.0}%`;
  $("dAvgPsnr").textContent = stats.average_psnr_db != null ? `${stats.average_psnr_db} dB` : "–";
  $("dAvgTime").textContent = stats.average_processing_time_sec ? `${stats.average_processing_time_sec}s` : "–";

  // Batch summary
  if (lastBatch.length > 1) {
    try {
      const bStats = await api(`/api/batch?ids=${lastBatch.join(",")}`);
      $("batchBox").classList.remove("hidden");
      $("batchCount").textContent = bStats.files_processed;
      const bg = $("batchGrid");
      bg.textContent = "";
      const bItems = [
        ["Batch files", bStats.files_processed],
        ["Original size", fmtBytes(bStats.total_original_bytes)],
        ["Optimized size", fmtBytes(bStats.total_optimized_bytes)],
        ["Space saved", fmtBytes(bStats.total_saved_bytes)],
        ["Batch reduction", `${bStats.average_reduction_percent}%`]
      ];
      for (const [k, v] of bItems) {
        const c = el("div", null, "dash-card");
        c.appendChild(el("span", k));
        c.appendChild(el("b", String(v)));
        bg.appendChild(c);
      }
    } catch {
      $("batchBox").classList.add("hidden");
    }
  } else {
    $("batchBox").classList.add("hidden");
  }

  // Render Charts if data exists and Chart.js is loaded
  const hasData = (stats.total_files || 0) > 0;
  if (!hasData) {
    $("dashEmptyState").classList.remove("hidden");
    $("dashChartsGrid").classList.add("hidden");
    return;
  }

  $("dashEmptyState").classList.add("hidden");
  $("dashChartsGrid").classList.remove("hidden");

  if (!window.Chart) return;

  renderDashboardCharts(stats);
}

function renderDashboardCharts(stats) {
  // Chart 1: Storage Breakdown (Original vs Optimized vs Saved)
  const ctxStorage = $("storageChart")?.getContext("2d");
  if (ctxStorage) {
    const origMb = stats.storage_comparison?.original_mb || +(stats.total_original_bytes / 1048576).toFixed(2);
    const optMb = stats.storage_comparison?.optimized_mb || +(stats.total_optimized_bytes / 1048576).toFixed(2);
    const savedMb = stats.storage_comparison?.saved_mb || +(stats.total_saved_bytes / 1048576).toFixed(2);

    if (storageChartInstance) storageChartInstance.destroy();
    storageChartInstance = new Chart(ctxStorage, {
      type: "bar",
      data: {
        labels: ["Original", "Optimized", "Saved"],
        datasets: [{
          data: [origMb, optMb, savedMb],
          backgroundColor: ["#232f3e", "#2f6fde", "#1e9e5a"],
          borderRadius: 6
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: c => ` ${c.parsed.y} MB` } }
        },
        scales: {
          y: { beginAtZero: true, ticks: { callback: v => v + " MB" } }
        }
      }
    });
  }

  // Chart 2: Daily Activity Timeline
  const ctxDaily = $("dailyActivityChart")?.getContext("2d");
  if (ctxDaily) {
    const daily = stats.daily_activity || [];
    const labels = daily.length ? daily.map(d => d.date.slice(5)) : ["Today"];
    const uploaded = daily.length ? daily.map(d => d.uploaded) : [stats.total_files];
    const completed = daily.length ? daily.map(d => d.completed) : [stats.files_processed];

    if (dailyActivityChartInstance) dailyActivityChartInstance.destroy();
    dailyActivityChartInstance = new Chart(ctxDaily, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Uploaded",
            data: uploaded,
            borderColor: "#ff9900",
            backgroundColor: "rgba(255, 153, 0, 0.15)",
            tension: 0.3,
            fill: true
          },
          {
            label: "Completed",
            data: completed,
            borderColor: "#1e9e5a",
            backgroundColor: "rgba(30, 158, 90, 0.15)",
            tension: 0.3,
            fill: true
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
        plugins: { legend: { position: "top", labels: { boxWidth: 12 } } }
      }
    });
  }

  // Chart 3: Media Type Distribution
  const ctxType = $("typeDistChart")?.getContext("2d");
  if (ctxType) {
    const imgCount = stats.media_type_distribution?.image || 0;
    const vidCount = stats.media_type_distribution?.video || 0;

    if (typeDistChartInstance) typeDistChartInstance.destroy();
    typeDistChartInstance = new Chart(ctxType, {
      type: "doughnut",
      data: {
        labels: ["Images", "Videos"],
        datasets: [{
          data: [imgCount, vidCount],
          backgroundColor: ["#ff9900", "#2f6fde"],
          borderWidth: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom" },
          tooltip: {
            callbacks: {
              label: c => ` ${c.label}: ${c.parsed} (${stats.total_files ? Math.round((c.parsed / stats.total_files) * 100) : 0}%)`
            }
          }
        }
      }
    });
  }

  // Chart 4: Intelligent Format Distribution
  const ctxFormat = $("formatDistChart")?.getContext("2d");
  if (ctxFormat) {
    const fDist = stats.format_distribution || { WEBP: stats.files_processed || 0 };
    const labels = Object.keys(fDist);
    const data = Object.values(fDist);

    if (formatDistChartInstance) formatDistChartInstance.destroy();
    formatDistChartInstance = new Chart(ctxFormat, {
      type: "doughnut",
      data: {
        labels,
        datasets: [{
          data,
          backgroundColor: ["#1e9e5a", "#ff9900", "#2f6fde", "#8e44ad"],
          borderWidth: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: "bottom" } }
      }
    });
  }

  // Chart 5: PSNR Quality Tiers
  const ctxQuality = $("qualityDistChart")?.getContext("2d");
  if (ctxQuality) {
    const q = stats.quality_distribution || {};
    const labels = ["Excellent (≥35 dB)", "Good (30-35 dB)", "Acceptable (25-30 dB)", "Low (<25 dB)"];
    const values = [
      q.excellent_35_plus || 0,
      q.good_30_35 || 0,
      q.acceptable_25_30 || 0,
      q.low_under_25 || 0
    ];

    if (qualityDistChartInstance) qualityDistChartInstance.destroy();
    qualityDistChartInstance = new Chart(ctxQuality, {
      type: "bar",
      data: {
        labels,
        datasets: [{
          data: values,
          backgroundColor: ["#1e9e5a", "#2f6fde", "#d98b00", "#d64545"],
          borderRadius: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, ticks: { precision: 0 } },
          x: { ticks: { font: { size: 11 } } }
        }
      }
    });
  }
}

/* ---------- Section 5: Processed Media History & Management ---------- */
async function loadHistoryItems() {
  const ids = [...tracked].reverse();
  const items = [];

  for (const mid of ids) {
    try {
      const m = await api(`/api/media/${mid}`);
      items.push(m);
    } catch {
      // deleted or inaccessible
    }
  }

  allHistoryItems = items;
  renderHistoryTable();
}

function renderHistoryTable() {
  const tbody = $("historyBody");
  const query = ($("historySearch")?.value || "").toLowerCase().trim();
  const typeFilter = $("historyTypeFilter")?.value || "all";
  const statusFilter = $("historyStatusFilter")?.value || "all";
  const sort = $("historySort")?.value || "date_desc";

  // 1. Filter
  let filtered = allHistoryItems.filter(it => {
    if (query) {
      const matchName = (it.original_filename || "").toLowerCase().includes(query);
      const matchId = (it.media_id || "").toLowerCase().includes(query);
      if (!matchName && !matchId) return false;
    }
    if (typeFilter !== "all" && it.media_type !== typeFilter) return false;
    if (statusFilter !== "all" && it.status !== statusFilter) return false;
    return true;
  });

  // 2. Sort
  filtered.sort((a, b) => {
    if (sort === "date_desc") return (b.created_at || "").localeCompare(a.created_at || "");
    if (sort === "date_asc") return (a.created_at || "").localeCompare(b.created_at || "");
    if (sort === "size_desc") return (b.original_size || 0) - (a.original_size || 0);
    if (sort === "size_asc") return (a.original_size || 0) - (b.original_size || 0);
    if (sort === "savings_desc") return (b.compression_percentage || 0) - (a.compression_percentage || 0);
    if (sort === "time_asc") return (a.processing_time || 999) - (b.processing_time || 999);
    return 0;
  });

  $("historyItemCount").textContent = `${filtered.length} item(s) found`;

  // 3. Pagination
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  if (currentPage > totalPages) currentPage = totalPages;
  if (currentPage < 1) currentPage = 1;

  $("pageIndicator").textContent = `Page ${currentPage} of ${totalPages}`;
  $("prevPageBtn").disabled = currentPage <= 1;
  $("nextPageBtn").disabled = currentPage >= totalPages;

  const startIdx = (currentPage - 1) * pageSize;
  const pageItems = filtered.slice(startIdx, startIdx + pageSize);

  tbody.textContent = "";
  if (!pageItems.length) {
    const tr = el("tr");
    const td = el("td", allHistoryItems.length ? "No matching records found." : "No media files uploaded yet. Choose an image or video above to begin.", "muted");
    td.colSpan = 11;
    td.style.textAlign = "center";
    td.style.padding = "24px";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  for (const it of pageItems) {
    const tr = el("tr");

    // Thumb
    const tdThumb = el("td");
    if (it.thumbnail_url) {
      const img = el("img", null, "");
      img.src = it.thumbnail_url;
      img.alt = "Thumb";
      tdThumb.appendChild(img);
    } else {
      tdThumb.appendChild(el("span", "–", "muted"));
    }

    // Filename
    const tdName = el("td");
    const fn = el("div", it.original_filename || it.media_id, "");
    fn.style.fontWeight = "500";
    const sub = el("div", it.media_id ? it.media_id.slice(-12) : "", "muted");
    sub.style.fontSize = "11px";
    tdName.append(fn, sub);

    // Type
    const tdType = el("td");
    const typeBadge = el("span", (it.media_type || "IMG").toUpperCase(), "badge");
    typeBadge.style.fontSize = "10px";
    typeBadge.style.padding = "2px 6px";
    typeBadge.style.background = it.media_type === "video" ? "#2f6fde" : "#ff9900";
    typeBadge.style.color = "#fff";
    typeBadge.style.borderColor = "transparent";
    tdType.appendChild(typeBadge);

    // Status
    const tdStatus = el("td");
    tdStatus.appendChild(el("span", it.status, `status ${it.status}`));

    // Sizes & Savings
    const tdOrig = el("td", fmtBytes(it.original_size));
    const tdOpt = el("td", fmtBytes(it.optimized_size));
    const tdSaved = el("td", it.space_saved_bytes ? `${fmtBytes(it.space_saved_bytes)} (${it.compression_percentage}%)` : "–", it.space_saved_bytes ? "good" : "");

    // Quality (PSNR)
    const tdQuality = el("td");
    if (it.media_type === "video") {
      tdQuality.appendChild(el("span", "N/A (Video)", "muted"));
    } else if (it.psnr_db != null) {
      tdQuality.appendChild(el("span", `${it.psnr_db} dB`, it.psnr_db >= 35 ? "good" : ""));
    } else {
      tdQuality.appendChild(el("span", "–", "muted"));
    }

    // Format
    const tdFormat = el("td");
    const fmtStr = (it.settings_used?.format || (it.media_type === "video" ? "MP4" : "WEBP")).toUpperCase();
    tdFormat.appendChild(el("span", fmtStr, "badge"));

    // Time
    const tdTime = el("td", it.processing_time != null ? `${it.processing_time}s` : "–");

    // Actions
    const tdActions = el("td");
    const btnInspect = el("button", "Inspect", "btn small ghost");
    btnInspect.style.marginRight = "6px";
    btnInspect.onclick = () => openDetailModal(it);
    tdActions.appendChild(btnInspect);

    if (it.status === "COMPLETED" && it.processed_url) {
      const aDl = el("a", "Download", "btn small");
      aDl.href = it.processed_url;
      aDl.download = `optimized_${it.original_filename}`;
      aDl.target = "_blank";
      tdActions.appendChild(aDl);
    }

    tr.append(tdThumb, tdName, tdType, tdStatus, tdOrig, tdOpt, tdSaved, tdQuality, tdFormat, tdTime, tdActions);
    tbody.appendChild(tr);
  }
}

/* ---------- Detailed Report Modal ---------- */
function openDetailModal(item) {
  const modal = $("detailModal");
  const title = $("modalTitle");
  const body = $("modalBody");

  title.textContent = `Telemetry Report: ${item.original_filename || item.media_id}`;
  body.textContent = "";

  const isVideo = item.media_type === "video";

  // Modal Top Media Preview
  const previewWrap = el("div", null, "compare");
  previewWrap.style.margin = "0 0 16px";

  const figBefore = el("figure");
  figBefore.appendChild(el("figcaption", "Original Asset"));
  const viewBefore = el("div", null, "media-view");
  if (item.original_url) {
    if (isVideo) {
      const v = document.createElement("video");
      v.src = item.original_url;
      v.controls = true;
      viewBefore.appendChild(v);
    } else {
      const img = document.createElement("img");
      img.src = item.original_url;
      viewBefore.appendChild(img);
    }
  } else {
    viewBefore.appendChild(el("div", "No preview", "muted"));
  }
  figBefore.appendChild(viewBefore);
  figBefore.appendChild(el("div", fmtBytes(item.original_size), "size"));

  const figAfter = el("figure");
  figAfter.appendChild(el("figcaption", "Optimized Asset"));
  const viewAfter = el("div", null, "media-view");
  if (item.processed_url) {
    if (isVideo) {
      const v = document.createElement("video");
      v.src = item.processed_url;
      v.controls = true;
      viewAfter.appendChild(v);
    } else {
      const img = document.createElement("img");
      img.src = item.processed_url;
      viewAfter.appendChild(img);
    }
  } else {
    viewAfter.appendChild(el("div", "No preview", "muted"));
  }
  figAfter.appendChild(viewAfter);
  figAfter.appendChild(el("div", fmtBytes(item.optimized_size), "size"));

  previewWrap.append(figBefore, figAfter);
  body.appendChild(previewWrap);

  // Technical Metadata Grid
  const metaGrid = el("div", null, "meta-grid");
  const addCard = (label, val) => {
    const c = el("div", null, "meta-card");
    c.appendChild(el("span", label));
    c.appendChild(el("b", String(val)));
    metaGrid.appendChild(c);
  };

  addCard("Media ID", item.media_id);
  addCard("Container Type", (item.media_type || "image").toUpperCase());
  addCard("Processing Status", item.status);
  addCard("Original Size", fmtBytes(item.original_size));
  addCard("Optimized Size", fmtBytes(item.optimized_size));
  addCard("Storage Reduction", `${item.compression_percentage || 0}% (${fmtBytes(item.space_saved_bytes || 0)})`);
  addCard("Dimensions Before", fmtDims(item.original_width, item.original_height));
  addCard("Dimensions After", fmtDims(item.optimized_width, item.optimized_height));
  addCard("PSNR Quality Score", isVideo ? "N/A for Video (CRF 23)" : (item.psnr_db != null ? `${item.psnr_db} dB (${item.psnr_label || "Good"})` : "–"));
  addCard("Processing Duration", item.processing_time != null ? `${item.processing_time}s` : "–");
  addCard("Output Format", (item.settings_used?.format || (isVideo ? "mp4" : "webp")).toUpperCase());
  addCard("Policy Decision", item.settings_used?.reason || "Standard serverless profile");
  addCard("Created At", item.created_at || "–");

  body.appendChild(metaGrid);
  modal.classList.remove("hidden");
}

function closeDetailModal() {
  $("detailModal").classList.add("hidden");
}

/* ---------- CSV Export Functionality ---------- */
function exportHistoryToCsv() {
  if (!allHistoryItems.length) {
    alert("No history records available to export.");
    return;
  }

  const headers = [
    "Media ID",
    "Filename",
    "Media Type",
    "Status",
    "Original Bytes",
    "Optimized Bytes",
    "Saved Bytes",
    "Reduction Pct",
    "PSNR dB",
    "Processing Time Sec",
    "Output Format",
    "Created At"
  ];

  const escapeCsv = v => {
    if (v == null) return '""';
    const s = String(v).replace(/"/g, '""');
    return `"${s}"`;
  };

  const rows = allHistoryItems.map(it => [
    escapeCsv(it.media_id),
    escapeCsv(it.original_filename),
    escapeCsv(it.media_type),
    escapeCsv(it.status),
    it.original_size || 0,
    it.optimized_size || 0,
    it.space_saved_bytes || 0,
    it.compression_percentage || 0,
    it.media_type === "video" ? "N/A" : (it.psnr_db != null ? it.psnr_db : ""),
    it.processing_time != null ? it.processing_time : "",
    escapeCsv(it.settings_used?.format || (it.media_type === "video" ? "mp4" : "webp")),
    escapeCsv(it.created_at || "")
  ].join(","));

  const csvContent = [headers.join(","), ...rows].join("\r\n");
  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `media_pipeline_history_${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/* ---------- Demo Sample Data Helper ---------- */
function loadDemoSample() {
  const sampleItems = [
    {
      media_id: "photo_landscape_demo_01",
      original_filename: "nature_mountain_4k.jpg",
      media_type: "image",
      status: "COMPLETED",
      original_size: 4210450,
      optimized_size: 685120,
      space_saved_bytes: 3525330,
      compression_percentage: 83.7,
      original_width: 3840,
      original_height: 2160,
      optimized_width: 1920,
      optimized_height: 1080,
      psnr_db: 36.42,
      psnr_label: "Excellent",
      processing_time: 0.42,
      settings_used: { format: "webp", quality: 80, reason: "WEBP_SAVINGS_EXCEEDED_THRESHOLD" },
      created_at: new Date(Date.now() - 3600000 * 2).toISOString(),
      thumbnail_url: "tests/test_images/landscape.jpg",
      original_url: "tests/test_images/landscape.jpg",
      processed_url: "tests/test_images/landscape.jpg"
    },
    {
      media_id: "drone_footage_clip_demo_02",
      original_filename: "campus_aerial_clip.mp4",
      media_type: "video",
      status: "COMPLETED",
      original_size: 18450120,
      optimized_size: 5120400,
      space_saved_bytes: 13329720,
      compression_percentage: 72.2,
      original_width: 1920,
      original_height: 1080,
      optimized_width: 1280,
      optimized_height: 720,
      psnr_db: null,
      psnr_label: null,
      processing_time: 2.14,
      settings_used: { format: "mp4", reason: "VIDEO_720P_CRF23" },
      created_at: new Date(Date.now() - 3600000 * 4).toISOString(),
      thumbnail_url: "tests/test_images/landscape.jpg",
      original_url: "tests/test_videos/sample_video.mp4",
      processed_url: "tests/test_videos/sample_video.mp4"
    },
    {
      media_id: "product_macro_shot_demo_03",
      original_filename: "microcontroller_board.png",
      media_type: "image",
      status: "COMPLETED",
      original_size: 2840000,
      optimized_size: 420100,
      space_saved_bytes: 2419900,
      compression_percentage: 85.2,
      original_width: 2400,
      original_height: 1800,
      optimized_width: 1600,
      optimized_height: 1200,
      psnr_db: 34.85,
      psnr_label: "Good",
      processing_time: 0.38,
      settings_used: { format: "webp", quality: 82, reason: "HIGH_FREQUENCY_IMAGE_OPTIMIZATION" },
      created_at: new Date(Date.now() - 3600000 * 6).toISOString(),
      thumbnail_url: "tests/test_images/large_photo.jpg",
      original_url: "tests/test_images/large_photo.jpg",
      processed_url: "tests/test_images/large_photo.jpg"
    }
  ];

  for (const s of sampleItems) {
    tracked.add(s.media_id);
  }
  saveState();

  // Prepend to current in-memory history
  allHistoryItems = [...sampleItems, ...allHistoryItems.filter(x => !sampleItems.some(s => s.media_id === x.media_id))];
  renderActiveComparison(sampleItems[0]);
  renderHistoryTable();
  refreshDashboard();
}

/* ---------- Global Refresh ---------- */
async function refreshAll() {
  refreshDashboard();
  loadHistoryItems();
}

/* ---------- Event Listeners & Boot ---------- */
document.addEventListener("DOMContentLoaded", () => {
  const fileInput = $("fileInput");
  const dropZone = $("dropZone");
  const uploadBtn = $("uploadBtn");
  const fileInfo = $("fileInfo");

  // Drag & drop
  ["dragenter", "dragover"].forEach(evt => {
    dropZone.addEventListener(evt, e => {
      e.preventDefault();
      dropZone.style.borderColor = "var(--brand)";
      dropZone.style.background = "#fff8ed";
    });
  });
  ["dragleave", "drop"].forEach(evt => {
    dropZone.addEventListener(evt, e => {
      e.preventDefault();
      dropZone.style.borderColor = "var(--line)";
      dropZone.style.background = "#fff";
    });
  });
  dropZone.addEventListener("drop", e => {
    if (e.dataTransfer.files?.length) {
      handleFilesSelected([...e.dataTransfer.files]);
    }
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files?.length) {
      handleFilesSelected([...fileInput.files]);
    }
  });

  function handleFilesSelected(files) {
    selectedFiles = files;
    if (!files.length) {
      uploadBtn.disabled = true;
      fileInfo.classList.add("hidden");
      return;
    }
    uploadBtn.disabled = false;
    fileInfo.classList.remove("hidden");
    const totalBytes = files.reduce((acc, f) => acc + f.size, 0);
    fileInfo.textContent = files.length === 1
      ? `Selected: ${files[0].name} (${fmtBytes(files[0].size)})`
      : `Selected: ${files.length} files (total ${fmtBytes(totalBytes)})`;
  }

  uploadBtn.addEventListener("click", handleUpload);
  $("refreshStatsBtn")?.addEventListener("click", refreshDashboard);
  $("refreshHistoryBtn")?.addEventListener("click", loadHistoryItems);

  // History toolbar listeners
  $("historySearch")?.addEventListener("input", () => { currentPage = 1; renderHistoryTable(); });
  $("historyTypeFilter")?.addEventListener("change", () => { currentPage = 1; renderHistoryTable(); });
  $("historyStatusFilter")?.addEventListener("change", () => { currentPage = 1; renderHistoryTable(); });
  $("historySort")?.addEventListener("change", () => { currentPage = 1; renderHistoryTable(); });
  $("pageSizeSelect")?.addEventListener("change", e => {
    pageSize = parseInt(e.target.value, 10) || 10;
    currentPage = 1;
    renderHistoryTable();
  });
  $("prevPageBtn")?.addEventListener("click", () => {
    if (currentPage > 1) { currentPage--; renderHistoryTable(); }
  });
  $("nextPageBtn")?.addEventListener("click", () => {
    currentPage++; renderHistoryTable();
  });

  // Modal close listeners
  $("closeModalBtn")?.addEventListener("click", closeDetailModal);
  $("modalCloseBtn")?.addEventListener("click", closeDetailModal);
  $("detailModal")?.addEventListener("click", e => {
    if (e.target.id === "detailModal") closeDetailModal();
  });

  // CSV Export & Demo Sample
  $("exportCsvBtn")?.addEventListener("click", exportHistoryToCsv);
  $("loadSampleBtn")?.addEventListener("click", loadDemoSample);

  // Connection indicator check
  fetch(API + "/api/stats")
    .then(r => {
      const mb = $("modeBadge");
      if (r.ok) {
        mb.textContent = "Live Supabase Cloud Connected";
        mb.style.background = "rgba(30, 158, 90, 0.2)";
        mb.style.borderColor = "var(--ok)";
      }
    })
    .catch(() => {
      const mb = $("modeBadge");
      mb.textContent = "Local Pipeline / Demo Mode";
    });

  // Initial loads
  refreshAll();
});