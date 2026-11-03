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

  let uploadPath = null;
  let pendingIdea = null;

  function addMsg(role, text, extra = "") {
    const el = document.createElement("div");
    el.className = `msg ${role}`;
    el.innerHTML = `${escapeHtml(text)}${extra ? `<span class="meta">${escapeHtml(extra)}</span>` : ""}`;
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
      pendingIdea = (ev.data && ev.data.idea) || pendingIdea;
      confirmText.textContent = ev.message;
      dlg.showModal();
    }
  }

  function showPreview(path) {
    preview.classList.remove("hidden");
    previewPath.textContent = path;
    previewVideo.src = `/api/media?path=${encodeURIComponent(path)}`;
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
    uploadHint.textContent = `Terunggah: ${data.filename}`;
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    addMsg("user", message);
    input.value = "";
    const meta = {};
    if (uploadPath) {
      meta.input_video = uploadPath;
      meta.upload_path = uploadPath;
    }
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, meta, confirm_dynamic: false }),
    });
    const data = await res.json();
    if (data.message) addMsg("assistant", data.message);
    if (data.needs_confirm) {
      pendingIdea = data.idea || message;
      confirmText.textContent = data.message;
      dlg.showModal();
    }
    refreshJobs();
  });

  dlg.addEventListener("close", async () => {
    if (dlg.returnValue !== "ok" || !pendingIdea) return;
    const idea = pendingIdea;
    pendingIdea = null;
    addMsg("user", `[konfirmasi] Generate workflow: ${idea}`);
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: idea, confirm_dynamic: true, meta: {} }),
    });
    const data = await res.json();
    if (data.message) addMsg("assistant", data.message);
    refreshWorkflows();
    refreshJobs();
  });

  addMsg(
    "assistant",
    "Selamat datang. Ketik perintah natural language — agen akan merutekan atau membuat workflow secara dinamis."
  );
  refreshCapability();
  refreshWorkflows();
  refreshJobs();
  connectWS();
})();
