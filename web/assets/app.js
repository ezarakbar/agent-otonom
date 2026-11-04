(() => {
  const chat = document.getElementById("chat");
  const form = document.getElementById("composer");
  const input = document.getElementById("input");
  const fileInput = document.getElementById("file");
  const uploadHint = document.getElementById("upload-hint");
  const capBody = document.getElementById("cap-body");
  const wfList = document.getElementById("wf-list");
  const jobList = document.getElementById("job-list");
  const connDot = document.getElementById("conn-dot");
  const connLabel = document.getElementById("conn-label");
  const preview = document.getElementById("preview");
  const previewVideo = document.getElementById("preview-video");
  const previewPath = document.getElementById("preview-path");
  const dlg = document.getElementById("confirm-dlg");
  const confirmText = document.getElementById("confirm-text");
  const confirmTitle = document.getElementById("confirm-title");
  const optionList = document.getElementById("option-list");
  const confirmOk = document.getElementById("confirm-ok");

  let uploadPath = null;
  let uploadKind = null;
  let pending = null; // {kind, idea, brief, workflow, selectedOption}

  function addMsg(role, text, extra = "") {
    const el = document.createElement("div");
    el.className = `msg ${role}`;
    el.innerHTML = `${formatMessage(text)}${extra ? `<span class="meta">${escapeHtml(extra)}</span>` : ""}`;
    chat.appendChild(el);
    chat.scrollTop = chat.scrollHeight;
    return el;
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  function formatMessage(text) {
    // light markdown: **bold**, lines, links [t](u)
    let s = escapeHtml(text);
    s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/\[(.+?)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    s = s.replace(/^### (.+)$/gm, "<h4>$1</h4>");
    s = s.replace(/^## (.+)$/gm, "<h3>$1</h3>");
    s = s.replace(/\n/g, "<br/>");
    return s;
  }

  async function refreshCapability() {
    const res = await fetch("/api/capability");
    const cap = await res.json();
    renderCapability(cap);
  }

  function renderCapability(cap) {
    const engineRows = Object.entries(cap.engines || {})
      .map(([k, v]) => {
        const cls = v.available ? "ok" : v.required ? "fail" : "opt";
        const label = v.available ? "ready" : v.required ? "missing" : "optional";
        return `<div class="row"><span>${k}</span><span class="badge ${cls}">${label}</span></div>`;
      })
      .join("");
    capBody.innerHTML = `
      <div class="row"><span>GPU</span><span class="val">${escapeHtml(cap.gpu_vendor)}</span></div>
      <div class="row"><span>RAM</span><span class="val">${cap.ram_gb} GB</span></div>
      <div class="row"><span>Profile</span><span class="val">${escapeHtml(cap.quality_profile)}</span></div>
      <div class="row"><span>Encoder</span><span class="val">${escapeHtml(cap.video_encoder)}</span></div>
      ${engineRows}
    `;
  }

  async function refreshWorkflows() {
    const res = await fetch("/api/workflows");
    const data = await res.json();
    wfList.innerHTML = (data.workflows || [])
      .map(
        (w) =>
          `<li><strong>${escapeHtml(w.title)}</strong><small>${escapeHtml(w.description || w.id)}</small></li>`
      )
      .join("");
  }

  async function refreshJobs() {
    const res = await fetch("/api/jobs");
    const data = await res.json();
    jobList.innerHTML = (data.jobs || [])
      .slice(0, 8)
      .map(
        (j) =>
          `<li><strong>${escapeHtml(j.workflow)}</strong><small>${escapeHtml(j.status)} · ${Math.round(j.progress || 0)}%</small></li>`
      )
      .join("") || "<li><small>Belum ada job</small></li>";
  }

  function connectWS() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => {
      connDot.classList.add("on");
      connLabel.textContent = "Live";
    };
    ws.onclose = () => {
      connDot.classList.remove("on");
      connLabel.textContent = "Terputus — reconnect…";
      setTimeout(connectWS, 2000);
    };
    ws.onmessage = (ev) => {
      let data;
      try {
        data = JSON.parse(ev.data);
      } catch {
        return;
      }
      handleEvent(data);
    };
  }

  function handleEvent(ev) {
    if (ev.kind === "system" && ev.data && ev.data.capability) {
      renderCapability(ev.data.capability);
    }
    if (ev.kind === "status" || ev.kind === "progress") {
      addMsg("status", ev.message, ev.progress != null ? `${Math.round(ev.progress)}%` : "");
    } else if (ev.kind === "error") {
      addMsg("error", ev.message);
    } else if (ev.kind === "done") {
      addMsg("assistant", ev.message);
      if (ev.path && /\.(mp4|webm|mov)$/i.test(ev.path)) {
        showPreview(ev.path);
      }
      refreshJobs();
    } else if (ev.kind === "preview" && ev.path) {
      showPreview(ev.path);
    } else if (ev.kind === "confirm") {
      openConfirmFromEvent(ev);
    }
  }

  function showPreview(path) {
    preview.classList.remove("hidden");
    previewPath.textContent = path;
    previewVideo.src = `/api/media?path=${encodeURIComponent(path)}`;
  }

  function openConfirmFromEvent(ev) {
    const data = ev.data || {};
    const kind = data.action === "confirm_production" ? "production_brief" : "dynamic_workflow";
    pending = {
      kind,
      idea: data.idea || pending?.idea,
      brief: data.brief || null,
      workflow: data.workflow,
      selectedOption: data.recommended_option || (data.options && data.options[0] && data.options[0].id) || null,
    };
    confirmTitle.textContent =
      kind === "production_brief" ? "Konfirmasi brief produksi" : "Generate workflow baru?";
    confirmText.innerHTML = formatMessage(ev.message || "");
    renderOptions(data.options || [], pending.selectedOption);
    confirmOk.textContent =
      kind === "production_brief" ? "Render & Pack Upload" : "Generate & Jalankan";
    dlg.showModal();
  }

  function openConfirmFromChat(data) {
    pending = {
      kind: data.confirm_kind || "production_brief",
      idea: data.idea || input.value,
      brief: data.brief || null,
      workflow: data.workflow,
      selectedOption: data.recommended_option || (data.options && data.options[0] && data.options[0].id) || null,
    };
    confirmTitle.textContent =
      pending.kind === "production_brief" ? "Konfirmasi brief produksi" : "Generate workflow baru?";
    confirmText.innerHTML = formatMessage(data.message || "");
    renderOptions(data.options || [], pending.selectedOption);
    confirmOk.textContent =
      pending.kind === "production_brief" ? "Render & Pack Upload" : "Generate & Jalankan";
    dlg.showModal();
  }

  function renderOptions(options, selected) {
    if (!options || !options.length) {
      optionList.innerHTML = "";
      return;
    }
    optionList.innerHTML = options
      .map((o) => {
        const checked = o.id === selected ? "checked" : "";
        return `<label class="opt">
          <input type="radio" name="prod_opt" value="${escapeHtml(o.id)}" ${checked} />
          <span><strong>${escapeHtml(o.label || o.id)}</strong><small>${escapeHtml(o.description || "")}</small></span>
        </label>`;
      })
      .join("");
    optionList.querySelectorAll('input[name="prod_opt"]').forEach((el) => {
      el.addEventListener("change", () => {
        if (pending) pending.selectedOption = el.value;
      });
    });
  }

  fileInput.addEventListener("change", async () => {
    const file = fileInput.files && fileInput.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    uploadHint.textContent = "Mengunggah…";
    const res = await fetch("/api/upload", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) {
      uploadHint.textContent = data.detail || "Upload gagal";
      return;
    }
    uploadPath = data.path;
    uploadKind = data.kind || (/\.(png|jpe?g|webp)$/i.test(file.name) ? "image" : "video");
    uploadHint.textContent = `Terunggah (${uploadKind}): ${data.filename}`;
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    addMsg("user", message);
    input.value = "";
    const meta = {};
    if (uploadPath) {
      meta.upload_path = uploadPath;
      if (uploadKind === "image") meta.input_image = uploadPath;
      else meta.input_video = uploadPath;
    }
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, meta, confirm_dynamic: false, confirm_production: false }),
    });
    const data = await res.json();
    if (data.message) addMsg("assistant", data.message);
    if (data.needs_confirm) openConfirmFromChat(data);
    refreshJobs();
  });

  dlg.addEventListener("close", async () => {
    if (dlg.returnValue !== "ok" || !pending) return;
    const p = pending;
    pending = null;
    const selected =
      (optionList.querySelector('input[name="prod_opt"]:checked') || {}).value ||
      p.selectedOption;

    if (p.kind === "production_brief") {
      addMsg("user", `[konfirmasi] Render opsi: ${selected}`);
      const meta = {
        production_brief: p.brief,
        selected_option: selected,
      };
      if (uploadPath) {
        meta.upload_path = uploadPath;
        if (uploadKind === "image") meta.input_image = uploadPath;
        else meta.input_video = uploadPath;
      }
      if (p.brief && p.brief.input_image) meta.input_image = p.brief.input_image;
      if (p.brief && p.brief.input_video) meta.input_video = p.brief.input_video;

      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: p.idea,
          confirm_production: true,
          selected_option: selected,
          meta,
        }),
      });
      const data = await res.json();
      if (data.message) addMsg("assistant", data.message);
      refreshJobs();
      return;
    }

    addMsg("user", `[konfirmasi] Generate workflow: ${p.idea}`);
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: p.idea, confirm_dynamic: true, meta: {} }),
    });
    const data = await res.json();
    if (data.message) addMsg("assistant", data.message);
    refreshWorkflows();
    refreshJobs();
  });

  addMsg(
    "assistant",
    "Studio generatif siap. Ketik perintah → brief otomatis → **teks→audio (SoVITS) + teks→foto + teks→video gerak (AnimateDiff)** → subtitle, QC, pack upload. Tidak bergantung mengubah foto user jadi video."
  );
  refreshCapability();
  refreshWorkflows();
  refreshJobs();
  connectWS();
})();
