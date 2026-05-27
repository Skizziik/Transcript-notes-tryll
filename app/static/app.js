(() => {
  const $ = (id) => document.getElementById(id);

  const dz = $("dropzone");
  const fileInput = $("file-input");
  const browseBtn = $("browse-btn");
  const refreshBtn = $("refresh-btn");
  const modelsList = $("models-list");
  const modelsRefreshBtn = $("models-refresh-btn");
  const cacheInfo = $("cache-info");

  const statusDot = $("status-dot");
  const statusText = $("status-text");

  const activeRun = $("active-run");
  const activeName = $("active-name");
  const activeMeta = $("active-meta");
  const cancelBtn = $("cancel-btn");
  const activeDone = $("active-done");
  const doneActions = $("done-actions");
  const notesStream = $("notes-stream");

  const historyList = $("history-list");

  const modelSelect = $("model-select");
  const langSelect = $("lang-select");

  let currentWs = null;
  let currentRunId = null;

  // --- health check ---
  refreshHealth();
  refreshHistory();
  refreshModels();

  async function refreshHealth() {
    try {
      const r = await fetch("/api/health");
      const j = await r.json();
      if (j.claude_cli) {
        statusDot.className = "dot good";
        statusText.textContent = "Claude CLI готов";
      } else {
        statusDot.className = "dot bad";
        statusText.textContent = j.claude_message || "Claude CLI не найден";
      }
    } catch {
      statusDot.className = "dot bad";
      statusText.textContent = "сервер недоступен";
    }
  }

  // --- drop zone ---
  ["dragenter", "dragover"].forEach((evt) =>
    dz.addEventListener(evt, (e) => {
      e.preventDefault();
      dz.classList.add("drag");
    })
  );
  ["dragleave", "drop"].forEach((evt) =>
    dz.addEventListener(evt, (e) => {
      e.preventDefault();
      dz.classList.remove("drag");
    })
  );
  dz.addEventListener("drop", (e) => {
    if (e.dataTransfer?.files?.length) startUpload(e.dataTransfer.files[0]);
  });
  dz.addEventListener("click", (e) => {
    if (e.target.id === "browse-btn") return;
    fileInput.click();
  });
  browseBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    fileInput.click();
  });
  fileInput.addEventListener("change", () => {
    if (fileInput.files?.length) startUpload(fileInput.files[0]);
  });

  refreshBtn.addEventListener("click", refreshHistory);
  modelsRefreshBtn.addEventListener("click", refreshModels);
  cancelBtn.addEventListener("click", () => {
    activeRun.classList.add("hidden");
    if (currentWs) {
      try { currentWs.close(); } catch {}
      currentWs = null;
    }
  });

  // --- upload + run ---
  async function startUpload(file) {
    resetActive(file.name, prettyBytes(file.size));
    const fd = new FormData();
    fd.append("file", file);
    const params = new URLSearchParams();
    if (langSelect.value) params.set("language", langSelect.value);
    if (modelSelect.value) params.set("whisper_model", modelSelect.value);
    const url = "/api/runs?" + params.toString();
    try {
      const r = await fetch(url, { method: "POST", body: fd });
      if (!r.ok) {
        const t = await r.text();
        showToast("Ошибка: " + t, true);
        activeRun.classList.add("hidden");
        return;
      }
      const { run_id } = await r.json();
      currentRunId = run_id;
      attachWs(run_id);
      refreshHistory();
    } catch (e) {
      showToast("Не удалось загрузить файл: " + e.message, true);
    }
  }

  function resetActive(name, sizeHint) {
    activeRun.classList.remove("hidden");
    cancelBtn.classList.add("hidden");
    activeDone.classList.add("hidden");
    activeName.textContent = name;
    activeMeta.textContent = sizeHint ? `${sizeHint} · в очереди…` : "";
    notesStream.textContent = "";
    doneActions.innerHTML = "";

    document.querySelectorAll(".stage").forEach((s) => {
      s.classList.remove("done", "error");
      s.querySelector(".stage-pct").textContent = s.dataset.stage === "transcribe" ? "0%" : "—";
      s.querySelector(".fill").style.width = "0%";
      s.querySelector(".stage-msg").textContent = "";
      const bar = s.querySelector(".bar");
      bar.classList.remove("indeterminate");
      // Model stage is shown only on demand by the pipeline.
      if (s.dataset.stage === "model") s.classList.add("hidden");
    });
  }

  function attachWs(runId) {
    if (currentWs) try { currentWs.close(); } catch {}
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${location.host}/ws/${runId}`);
    currentWs = ws;
    ws.onmessage = (ev) => handleEvent(JSON.parse(ev.data));
    ws.onerror = () => showToast("Соединение с воркером прервано", true);
    ws.onclose = () => { if (currentWs === ws) currentWs = null; };
  }

  function handleEvent(ev) {
    switch (ev.type) {
      case "stage": handleStage(ev); break;
      case "transcript_ready": handleTranscriptReady(ev); break;
      case "notes_delta": appendNotes(ev.text); break;
      case "done": handleDone(ev); break;
      case "error": handleError(ev); break;
    }
  }

  function handleStage(ev) {
    const stage = document.querySelector(`.stage[data-stage="${ev.stage}"]`);
    if (!stage) return;
    const fill = stage.querySelector(".fill");
    const pct = stage.querySelector(".stage-pct");
    const msg = stage.querySelector(".stage-msg");
    const bar = stage.querySelector(".bar");

    if (typeof ev.progress === "number") {
      const p = Math.min(1, Math.max(0, ev.progress));
      fill.style.width = (p * 100).toFixed(1) + "%";
      pct.textContent = (p * 100).toFixed(0) + "%";
      bar.classList.remove("indeterminate");
      if (p >= 1) stage.classList.add("done");
    }
    if (ev.message) msg.textContent = ev.message;

    if (ev.stage === "notes" && (ev.progress === undefined || ev.progress === null)) {
      bar.classList.add("indeterminate");
      pct.textContent = "стриминг…";
    }
    if (ev.stage === "notes" && typeof ev.progress === "number" && ev.progress < 1) {
      bar.classList.add("indeterminate");
    }
  }

  function handleTranscriptReady(ev) {
    const sec = Math.round(ev.duration_sec || 0);
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    const meta = `${ev.language ?? "?"} · ${m}:${String(s).padStart(2, "0")} · ${ev.device}/${ev.compute_type}`;
    activeMeta.textContent = `${activeName.textContent.includes("·") ? "" : ""}${meta}`;
  }

  function appendNotes(text) {
    notesStream.textContent += text;
    const lp = $("live-preview");
    lp.scrollTop = lp.scrollHeight;
  }

  function handleDone(ev) {
    activeDone.classList.remove("hidden");
    cancelBtn.classList.remove("hidden");
    cancelBtn.textContent = "закрыть";
    document.querySelectorAll(".stage").forEach((s) => s.classList.add("done"));
    document.querySelectorAll(".bar.indeterminate").forEach((b) => b.classList.remove("indeterminate"));

    doneActions.innerHTML = "";
    const a = ev.artifacts || {};
    if (a.notes_docx) doneActions.appendChild(makeDownloadBtn(currentRunId, a.notes_docx, ".docx (заметки)", true));
    if (a.notes_md) doneActions.appendChild(makeDownloadBtn(currentRunId, a.notes_md, ".md"));
    if (a.transcript_txt) doneActions.appendChild(makeDownloadBtn(currentRunId, a.transcript_txt, ".txt транскрипт"));
    if (a.transcript_json) doneActions.appendChild(makeDownloadBtn(currentRunId, a.transcript_json, ".json сегменты"));

    refreshHistory();
  }

  function handleError(ev) {
    const stages = document.querySelectorAll(".stage");
    // Mark currently-incomplete stages as error.
    stages.forEach((s) => {
      const pct = s.querySelector(".stage-pct");
      if (!s.classList.contains("done")) {
        s.classList.add("error");
        s.querySelector(".bar").classList.remove("indeterminate");
        if (pct.textContent === "—" || pct.textContent === "стриминг…") pct.textContent = "ошибка";
      }
    });
    showToast("Ошибка: " + ev.message, true);
    refreshHistory();
  }

  function makeDownloadBtn(runId, name, label, primary = false) {
    const a = document.createElement("a");
    a.className = "dl-btn" + (primary ? " primary" : "");
    a.href = `/api/runs/${runId}/file/${encodeURIComponent(name)}`;
    a.download = name;
    a.textContent = label;
    return a;
  }

  // --- history ---
  async function refreshHistory() {
    try {
      const r = await fetch("/api/runs");
      const items = await r.json();
      renderHistory(items);
    } catch (e) {
      historyList.innerHTML = `<div class="empty">не удалось загрузить историю</div>`;
    }
  }

  function renderHistory(items) {
    if (!items.length) {
      historyList.innerHTML = `<div class="empty">пока пусто. Закинь аудио — здесь появится история.</div>`;
      return;
    }
    historyList.innerHTML = "";
    for (const it of items) {
      const card = document.createElement("div");
      card.className = "history-item";
      const title = it.title || it.audio_name || it.id;
      const dur = it.audio_duration_sec ? formatDuration(it.audio_duration_sec) : null;
      const meta = [
        formatDate(it.created_at),
        it.language || null,
        dur,
        prettyBytes(it.audio_size || 0),
      ].filter(Boolean).join(" · ");
      card.innerHTML = `
        <div class="h-row1">
          <div class="h-title">${escapeHtml(title)}</div>
          <span class="h-badge ${it.status}">${labelStatus(it.status)}</span>
        </div>
        <div class="h-meta">${escapeHtml(meta)} · <span title="${escapeHtml(it.audio_name||'')}">${escapeHtml(it.audio_name||'')}</span></div>
        <div class="h-actions"></div>
      `;
      const actions = card.querySelector(".h-actions");
      const a = it.artifacts || {};
      if (a.notes_docx) actions.appendChild(makeDownloadBtn(it.id, a.notes_docx, ".docx", true));
      if (a.notes_md) actions.appendChild(makeDownloadBtn(it.id, a.notes_md, ".md"));
      if (a.transcript_txt) actions.appendChild(makeDownloadBtn(it.id, a.transcript_txt, ".txt"));
      if (a.transcript_json) actions.appendChild(makeDownloadBtn(it.id, a.transcript_json, ".json"));

      const del = document.createElement("button");
      del.className = "h-del";
      del.textContent = "удалить";
      del.addEventListener("click", async () => {
        if (!confirm(`Удалить запись «${title}» и все её файлы?`)) return;
        await fetch(`/api/runs/${it.id}`, { method: "DELETE" });
        refreshHistory();
      });
      actions.appendChild(del);

      // Reattach to running runs on page reload.
      if (it.status === "running") {
        card.style.cursor = "pointer";
        card.addEventListener("click", (ev) => {
          if (ev.target.tagName === "A" || ev.target.tagName === "BUTTON") return;
          currentRunId = it.id;
          resetActive(it.audio_name, prettyBytes(it.audio_size || 0));
          attachWs(it.id);
        });
      }
      historyList.appendChild(card);
    }
  }

  function labelStatus(s) {
    return { done: "готово", running: "идёт", queued: "ожидание", error: "ошибка" }[s] || s;
  }

  // --- utils ---
  function prettyBytes(n) {
    if (!n) return "—";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
  }
  function formatDuration(sec) {
    sec = Math.round(sec);
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    if (h) return `${h}:${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`;
    return `${m}:${String(s).padStart(2,"0")}`;
  }
  function formatDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
  }

  function showToast(msg, bad = false) {
    let t = document.querySelector(".toast");
    if (!t) {
      t = document.createElement("div");
      t.className = "toast";
      document.body.appendChild(t);
    }
    t.textContent = msg;
    t.classList.toggle("bad", bad);
    t.classList.add("show");
    clearTimeout(t._h);
    t._h = setTimeout(() => t.classList.remove("show"), 4500);
  }

  // --- models ---
  const modelWsByName = new Map();

  async function refreshModels() {
    try {
      const r = await fetch("/api/models");
      const j = await r.json();
      renderModels(j.models);
      cacheInfo.innerHTML = `Кэш моделей: <code>${escapeHtml(j.cache_dir)}</code>`;
      updateModelSelector(j.models);
    } catch (e) {
      modelsList.innerHTML = `<div class="empty">не удалось загрузить список моделей</div>`;
    }
  }

  function renderModels(items) {
    modelsList.innerHTML = "";
    for (const m of items) {
      const card = document.createElement("div");
      card.className = "model-item" + (m.installed ? " installed" : "");
      card.dataset.name = m.name;
      const sizeOnDisk = m.installed ? prettyBytes(m.size_bytes) : `~${m.expected_size_mb} MB`;
      card.innerHTML = `
        <div class="m-row1">
          <div class="m-name">${escapeHtml(m.label)}</div>
          <div class="m-size">${escapeHtml(sizeOnDisk)}</div>
        </div>
        <div class="m-desc">${escapeHtml(m.description)}</div>
        <div class="m-actions"></div>
        <div class="m-progress hidden">
          <div class="bar"><div class="fill"></div></div>
          <div class="m-pct"><span class="m-pct-l">…</span><span class="m-pct-r">0%</span></div>
        </div>
      `;
      const actions = card.querySelector(".m-actions");
      if (m.installed) {
        const badge = document.createElement("span");
        badge.className = "m-badge";
        badge.textContent = "установлена";
        actions.appendChild(badge);

        const del = document.createElement("button");
        del.className = "m-delete";
        del.textContent = "удалить";
        del.addEventListener("click", () => deleteModel(m.name));
        actions.appendChild(del);
      } else {
        const install = document.createElement("button");
        install.className = "m-install";
        install.textContent = "установить";
        install.addEventListener("click", () => installModel(m.name));
        actions.appendChild(install);
      }
      modelsList.appendChild(card);

      // If a download is already in progress for this model, reattach WS.
      if (modelWsByName.has(m.name)) {
        showModelProgress(m.name);
      }
    }
  }

  function updateModelSelector(items) {
    const cur = modelSelect.value;
    modelSelect.innerHTML = "";
    for (const m of items) {
      const opt = document.createElement("option");
      opt.value = m.name;
      const mark = m.installed ? "✓" : "↓";
      opt.textContent = `${mark} ${m.label} (${m.installed ? prettyBytes(m.size_bytes) : "~" + m.expected_size_mb + " MB"})`;
      modelSelect.appendChild(opt);
    }
    // Preserve current choice if still present, else default to large-v3.
    if ([...modelSelect.options].some((o) => o.value === cur)) {
      modelSelect.value = cur;
    } else if ([...modelSelect.options].some((o) => o.value === "large-v3")) {
      modelSelect.value = "large-v3";
    }
  }

  async function installModel(name) {
    showModelProgress(name);
    try {
      const r = await fetch(`/api/models/${encodeURIComponent(name)}/download`, { method: "POST" });
      if (!r.ok) throw new Error(await r.text());
      attachModelWs(name);
    } catch (e) {
      showToast("Не удалось начать загрузку: " + e.message, true);
      hideModelProgress(name);
    }
  }

  async function deleteModel(name) {
    if (!confirm(`Удалить модель «${name}»? Файлы будут стёрты с диска.`)) return;
    try {
      const r = await fetch(`/api/models/${encodeURIComponent(name)}`, { method: "DELETE" });
      if (!r.ok) throw new Error(await r.text());
      refreshModels();
    } catch (e) {
      showToast("Не удалось удалить: " + e.message, true);
    }
  }

  function showModelProgress(name) {
    const card = modelsList.querySelector(`.model-item[data-name="${cssEsc(name)}"]`);
    if (!card) return;
    card.classList.add("downloading");
    const prog = card.querySelector(".m-progress");
    prog.classList.remove("hidden");
    const actions = card.querySelector(".m-actions");
    actions.querySelectorAll("button").forEach((b) => (b.disabled = true));
  }

  function hideModelProgress(name) {
    const card = modelsList.querySelector(`.model-item[data-name="${cssEsc(name)}"]`);
    if (!card) return;
    card.classList.remove("downloading");
    const prog = card.querySelector(".m-progress");
    if (prog) prog.classList.add("hidden");
    const actions = card.querySelector(".m-actions");
    actions.querySelectorAll("button").forEach((b) => (b.disabled = false));
  }

  function attachModelWs(name) {
    closeModelWs(name);
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${location.host}/ws/models/${encodeURIComponent(name)}`);
    modelWsByName.set(name, ws);

    ws.onmessage = (ev) => {
      const s = JSON.parse(ev.data);
      const card = modelsList.querySelector(`.model-item[data-name="${cssEsc(name)}"]`);
      if (!card) return;
      const fill = card.querySelector(".m-progress .fill");
      const left = card.querySelector(".m-pct-l");
      const right = card.querySelector(".m-pct-r");

      if (s.bytes_total > 0) {
        const frac = Math.min(1, s.bytes_done / s.bytes_total);
        fill.style.width = (frac * 100).toFixed(1) + "%";
        right.textContent = (frac * 100).toFixed(1) + "%";
      } else {
        fill.style.width = "0%";
        right.textContent = "…";
      }
      left.textContent = (s.message || "")
        + (s.bytes_total > 0 ? `  ·  ${prettyBytes(s.bytes_done)} / ${prettyBytes(s.bytes_total)}` : "");

      if (s.status === "done") {
        showToast(`Модель «${name}» установлена`);
        closeModelWs(name);
        refreshModels();
      } else if (s.status === "error") {
        showToast(`Ошибка загрузки «${name}»: ${s.error || ""}`, true);
        closeModelWs(name);
        hideModelProgress(name);
      }
    };
    ws.onerror = () => closeModelWs(name);
    ws.onclose = () => modelWsByName.delete(name);
  }

  function closeModelWs(name) {
    const ws = modelWsByName.get(name);
    if (ws) { try { ws.close(); } catch {} modelWsByName.delete(name); }
  }

  function cssEsc(s) {
    return String(s).replace(/["\\]/g, "\\$&");
  }

  // Extend handleStage support for the "model" stage — unhide it lazily.
  const _origHandleStage = handleStage;
  handleStage = function (ev) {
    if (ev.stage === "model") {
      const s = document.querySelector('.stage[data-stage="model"]');
      if (s) s.classList.remove("hidden");
    }
    return _origHandleStage(ev);
  };
})();
