(() => {
  "use strict";

  const EXT_LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "jsx",
    ".tsx": "tsx",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".html": "html",
    ".css": "css",
    ".json": "json",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".sql": "sql",
    ".sh": "bash",
    ".md": "markdown",
    ".txt": "text",
    ".toml": "toml",
    ".ini": "ini",
    ".csv": "csv",
    ".log": "text",
    ".vue": "vue",
    ".svelte": "svelte",
    ".swift": "swift",
    ".kt": "kotlin",
    ".lua": "lua",
  };

  // High character limit (10,000,000 chars ~ 10MB text per file) so large codebases/logs are never cut off
  const MAX_FILE_CHARS = 10_000_000;

  const state = {
    settings: null,
    sessions: [],
    activeSession: null,
    attachments: [],
    isStreaming: false,
  };

  const el = {
    sidebar: document.getElementById("sidebar"),
    toggleSidebarBtn: document.getElementById("toggle-sidebar-btn"),
    sessionTitleInput: document.getElementById("session-title-input"),
    modelSelect: document.getElementById("model-select"),
    refreshModelsBtn: document.getElementById("refresh-models-btn"),
    clearSessionBtn: document.getElementById("clear-session-btn"),
    exportSessionBtn: document.getElementById("export-session-btn"),
    openSettingsBtn: document.getElementById("open-settings-btn"),
    newSessionBtn: document.getElementById("new-session-btn"),
    sessionSearchInput: document.getElementById("session-search-input"),
    sessionList: document.getElementById("session-list"),
    apiStatusDot: document.getElementById("api-status-dot"),
    apiStatusTitle: document.getElementById("api-status-title"),
    dropZone: document.getElementById("drop-zone"),
    dropOverlay: document.getElementById("drop-overlay"),
    chatScrollContainer: document.getElementById("chat-scroll-container"),
    emptyState: document.getElementById("empty-state"),
    messagesList: document.getElementById("messages-list"),
    attachmentsTray: document.getElementById("attachments-tray"),
    promptInput: document.getElementById("prompt-input"),
    fileInput: document.getElementById("file-input"),
    attachFileBtn: document.getElementById("attach-file-btn"),
    stopGenBtn: document.getElementById("stop-gen-btn"),
    sendBtn: document.getElementById("send-btn"),

    // Settings Sheet
    settingsModal: document.getElementById("settings-modal"),
    closeSettingsBtn: document.getElementById("close-settings-btn"),
    cancelSettingsBtn: document.getElementById("cancel-settings-btn"),
    saveSettingsBtn: document.getElementById("save-settings-btn"),
    settingsApiKey: document.getElementById("settings-api-key"),
    validateKeyBtn: document.getElementById("validate-key-btn"),
    apiKeyStatusMsg: document.getElementById("api-key-status-msg"),
    settingsDefaultModel: document.getElementById("settings-default-model"),
    personaSelect: document.getElementById("persona-select"),
    sessionSystemPrompt: document.getElementById("session-system-prompt"),
    sessionTempSlider: document.getElementById("session-temp-slider"),
    tempValLabel: document.getElementById("temp-val-label"),

    // Spotlight Command Palette
    cmdPaletteModal: document.getElementById("cmd-palette-modal"),
    cmdPaletteInput: document.getElementById("cmd-palette-input"),
    cmdPaletteList: document.getElementById("cmd-palette-list"),

    toastContainer: document.getElementById("toast-container"),
  };

  function showToast(message) {
    const toast = document.createElement("div");
    toast.className = "toast";
    toast.textContent = message;
    el.toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = "0";
      setTimeout(() => toast.remove(), 220);
    }, 2400);
  }

  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // --- Minimal Markdown & Code Renderer ---
  function renderMarkdown(rawText) {
    if (!rawText) return "";

    const codeBlocks = [];
    const fenceRegex = /```([a-zA-Z0-9_+-]*)\n([\s\S]*?)```/g;

    let textWithPlaceholders = rawText.replace(fenceRegex, (_, lang, code) => {
      const cleanLang = (lang || "code").trim().toLowerCase();
      const cleanCode = code.replace(/\n$/, "");
      const idx = codeBlocks.length;
      codeBlocks.push({ lang: cleanLang, code: cleanCode });
      return `\n@@CODE_BLOCK_${idx}@@\n`;
    });

    let html = escapeHtml(textWithPlaceholders);

    // Inline code
    html = html.replace(/`([^`\n]+)`/g, '<code class="inline-code">$1</code>');

    // Bold & Italic
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");

    // Headings
    html = html.replace(/^####\s+(.+)$/gm, "<h4>$1</h4>");
    html = html.replace(/^###\s+(.+)$/gm, "<h3>$1</h3>");
    html = html.replace(/^##\s+(.+)$/gm, "<h2>$1</h2>");
    html = html.replace(/^#\s+(.+)$/gm, "<h1>$1</h1>");

    // Blockquotes
    html = html.replace(/^&gt;\s+(.+)$/gm, "<blockquote>$1</blockquote>");

    // Bullet lists
    html = html.replace(/^(?:[-*])\s+(.+)$/gm, "<li>$1</li>");
    html = html.replace(/(<li>[\s\S]*?<\/li>)/g, "<ul>$1</ul>");
    html = html.replace(/<\/ul>\s*<ul>/g, "");

    // Paragraphs
    const blocks = html.split(/\n{2,}/);
    html = blocks
      .map((b) => {
        const trimmed = b.trim();
        if (!trimmed) return "";
        if (
          trimmed.startsWith("<h") ||
          trimmed.startsWith("<ul") ||
          trimmed.startsWith("<blockquote") ||
          trimmed.startsWith("@@CODE_BLOCK_")
        ) {
          return trimmed;
        }
        return `<p>${trimmed.replace(/\n/g, "<br/>")}</p>`;
      })
      .join("\n");

    // Restore code blocks
    html = html.replace(/@@CODE_BLOCK_(\d+)@@/g, (_, idxStr) => {
      const idx = parseInt(idxStr, 10);
      const item = codeBlocks[idx];
      if (!item) return "";
      const encodedCode = encodeURIComponent(item.code);
      return `
        <div class="code-block-widget">
          <div class="code-block-header">
            <span class="code-lang-tag">${escapeHtml(item.lang)}</span>
            <div class="code-header-actions">
              <button class="code-action-btn" data-copy-code="${encodedCode}">Copy</button>
              <button class="code-action-btn" data-download-code="${encodedCode}" data-lang="${escapeHtml(item.lang)}">Save</button>
            </div>
          </div>
          <pre class="code-pre"><code>${escapeHtml(item.code)}</code></pre>
        </div>
      `;
    });

    return html;
  }

  async function apiGet(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  }

  async function apiSend(url, method, body = {}) {
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  }

  async function initApp() {
    try {
      const settings = await apiGet("/api/settings");
      state.settings = settings;
      applySettingsToUI(settings);

      const sessionsRes = await apiGet("/api/sessions");
      state.sessions = sessionsRes.sessions || [];

      if (state.sessions.length === 0) {
        const created = await apiSend("/api/sessions", "POST", { title: "New Conversation" });
        state.sessions = [created];
        await selectSession(created.id);
      } else {
        renderSessionList();
        await selectSession(state.sessions[0].id);
      }

      bindEvents();

      if (!settings.has_api_key) {
        openSettingsModal();
      }
    } catch (err) {
      showToast(`Error: ${err.message}`);
    }
  }

  function applySettingsToUI(settings) {
    const models = settings.available_models || [];
    const optionsHtml = models
      .map((m) => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.name)} (${escapeHtml(m.id)})</option>`)
      .join("");
    el.modelSelect.innerHTML = optionsHtml;
    el.settingsDefaultModel.innerHTML = optionsHtml;
    const preferredModel =
      models.find((m) => m.id === settings.model)?.id ||
      models.find((m) => m.id === "gemini-4-argon")?.id ||
      (models[0] && models[0].id) ||
      "gemini-4-argon";
    el.modelSelect.value = preferredModel;
    el.settingsDefaultModel.value = preferredModel;

    const personas = settings.personas || [];
    el.personaSelect.innerHTML = personas
      .map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}</option>`)
      .join("");

    if (settings.has_api_key) {
      el.apiStatusDot.classList.remove("missing");
      el.apiStatusTitle.textContent = "Settings";
      el.settingsApiKey.placeholder = settings.masked_api_key || "API key configured";
    } else {
      el.apiStatusDot.classList.add("missing");
      el.apiStatusTitle.textContent = "Add API Key";
    }
  }

  function renderSessionList() {
    if (!state.sessions.length) {
      el.sessionList.innerHTML = "";
      return;
    }

    el.sessionList.innerHTML = state.sessions
      .map((s) => {
        const isActive = state.activeSession && state.activeSession.id === s.id;
        return `
          <div class="session-item ${isActive ? "active" : ""}" data-session-id="${escapeHtml(s.id)}">
            <div class="session-item-title">${escapeHtml(s.title)}</div>
            <div class="session-item-actions">
              <button class="session-del-btn" data-del-id="${escapeHtml(s.id)}" title="Delete">✕</button>
            </div>
          </div>
        `;
      })
      .join("");
  }

  async function refreshSessionList(searchQuery = "") {
    const q = searchQuery || el.sessionSearchInput.value || "";
    const res = await apiGet(`/api/sessions?q=${encodeURIComponent(q)}`);
    state.sessions = res.sessions || [];
    renderSessionList();
  }

  async function selectSession(sessionId) {
    try {
      const session = await apiGet(`/api/sessions/${sessionId}`);
      state.activeSession = session;

      el.sessionTitleInput.value = session.title;
      el.modelSelect.value = session.model;
      el.personaSelect.value = session.persona_id || "default";
      el.sessionSystemPrompt.value = session.system_instruction || "";
      el.sessionTempSlider.value = session.temperature ?? 0.7;
      el.tempValLabel.textContent = `Temp: ${Number(session.temperature ?? 0.7).toFixed(2)}`;

      renderSessionList();
      renderMessages();
      el.promptInput.focus();
    } catch (err) {
      showToast(`Failed to load conversation`);
    }
  }

  async function createNewSession() {
    if (state.isStreaming) return;
    try {
      const created = await apiSend("/api/sessions", "POST", {
        title: "New Conversation",
        model: el.modelSelect.value,
      });
      await refreshSessionList();
      await selectSession(created.id);
    } catch (err) {
      showToast(`Error creating conversation`);
    }
  }

  function renderMessages() {
    const messages = (state.activeSession && state.activeSession.messages) || [];

    if (messages.length === 0) {
      el.emptyState.classList.remove("hidden");
      el.messagesList.innerHTML = "";
      return;
    }

    el.emptyState.classList.add("hidden");
    el.messagesList.innerHTML = messages
      .map((msg) => buildMessageRowHtml(msg))
      .join("");

    scrollToBottom();
  }

  function isImageGenerationModel(modelId) {
    const m = (modelId || "").toLowerCase();
    return m.includes("image") || m.includes("banana");
  }

  function isImagePrompt(text) {
    const t = (text || "").toLowerCase();
    return /\b(generate|create|draw|paint|render|make|design|sketch)\b.*\b(image|picture|photo|art|wallpaper|logo|illustration|icon)\b/.test(t);
  }

  function buildGeneratedImagesHtml(attachments) {
    if (!attachments || !attachments.length) return "";
    const imgs = attachments.filter((a) => a.type === "image" && a.data_base64);
    if (!imgs.length) return "";
    return (
      `<div class="generated-images-grid">` +
      imgs
        .map((img) => {
          const dataUri = `data:${escapeHtml(img.mime_type || "image/png")};base64,${img.data_base64}`;
          const fname = escapeHtml(img.filename || "generated_image.png");
          return `
            <div class="generated-image-card">
              <img src="${dataUri}" alt="${fname}" data-lightbox-src="${dataUri}" />
              <div class="generated-image-overlay">
                <a class="img-overlay-btn" href="${dataUri}" download="${fname}">Download</a>
              </div>
            </div>
          `;
        })
        .join("") +
      `</div>`
    );
  }

  function buildMessageRowHtml(msg) {
    const isUser = msg.role === "user";

    if (isUser) {
      let attachmentsHtml = "";
      if (msg.attachments && msg.attachments.length > 0) {
        attachmentsHtml =
          `<div class="msg-attachments-list">` +
          msg.attachments
            .map((att) => {
              if (att.type === "image" && att.data_base64) {
                return `
                  <div>
                    <img class="msg-attachment-thumb" src="data:${escapeHtml(att.mime_type)};base64,${att.data_base64}" alt="${escapeHtml(att.filename)}" />
                  </div>
                `;
              }
              return `
                <div class="msg-attachment-item">
                  📎 ${escapeHtml(att.filename)}
                </div>
              `;
            })
            .join("") +
          `</div>`;
      }

      return `
        <div class="message-row user" data-msg-id="${escapeHtml(msg.id)}">
          ${attachmentsHtml}
          <div class="user-bubble">${escapeHtml(msg.content).replace(/\n/g, "<br/>")}</div>
        </div>
      `;
    }

    const bodyHtml = renderMarkdown(msg.content);
    const genImagesHtml = buildGeneratedImagesHtml(msg.attachments);
    let latencyNote = "";
    if (msg.metadata && msg.metadata.elapsed_ms) {
      latencyNote = `<span class="msg-meta-note">${(msg.metadata.elapsed_ms / 1000).toFixed(1)}s</span>`;
    }

    return `
      <div class="message-row assistant" data-msg-id="${escapeHtml(msg.id)}">
        <div class="assistant-container">
          ${bodyHtml ? `<div class="message-body">${bodyHtml}</div>` : ""}
          ${genImagesHtml}
          <div class="message-footer-actions">
            ${msg.content ? `<button class="msg-subtle-btn" data-copy-msg="${encodeURIComponent(msg.content)}">Copy</button>` : ""}
            <button class="msg-subtle-btn" data-regen-msg="${escapeHtml(msg.id)}">Retry</button>
            ${latencyNote}
          </div>
        </div>
      </div>
    `;
  }

  function scrollToBottom() {
    el.chatScrollContainer.scrollTop = el.chatScrollContainer.scrollHeight;
  }

  // --- File Attachments ---
  async function handleFilesSelected(fileList) {
    for (const file of Array.from(fileList)) {
      if (file.type.startsWith("image/")) {
        const reader = new FileReader();
        reader.onload = () => {
          const base64 = String(reader.result).split(",")[1];
          state.attachments.push({
            filename: file.name,
            type: "image",
            mime_type: file.type,
            data_base64: base64,
          });
          renderAttachmentsTray();
        };
        reader.readAsDataURL(file);
      } else if (file.type === "application/pdf") {
        const reader = new FileReader();
        reader.onload = () => {
          const base64 = String(reader.result).split(",")[1];
          state.attachments.push({
            filename: file.name,
            type: "binary",
            mime_type: "application/pdf",
            data_base64: base64,
          });
          renderAttachmentsTray();
        };
        reader.readAsDataURL(file);
      } else {
        const text = await file.text();
        let truncated = false;
        let content = text;
        if (content.length > MAX_FILE_CHARS) {
          content = content.slice(0, MAX_FILE_CHARS);
          truncated = true;
        }
        const dotIdx = file.name.lastIndexOf(".");
        const ext = dotIdx >= 0 ? file.name.slice(dotIdx).toLowerCase() : "";
        const language = EXT_LANGUAGE_MAP[ext] || "text";
        state.attachments.push({
          filename: file.name,
          type: "code",
          language,
          content,
          truncated,
        });
        renderAttachmentsTray();
      }
    }
  }

  function renderAttachmentsTray() {
    if (state.attachments.length === 0) {
      el.attachmentsTray.classList.add("hidden");
      el.attachmentsTray.innerHTML = "";
      return;
    }
    el.attachmentsTray.classList.remove("hidden");
    el.attachmentsTray.innerHTML = state.attachments
      .map(
        (att, idx) => `
        <div class="attachment-chip">
          <span>${escapeHtml(att.filename)}</span>
          <button class="attachment-chip-remove" data-remove-att="${idx}">✕</button>
        </div>
      `
      )
      .join("");
  }

  // --- Streaming Chat ---
  async function sendMessage(options = {}) {
    if (state.isStreaming || !state.activeSession) return;

    const userText = el.promptInput.value.trim();
    const currentAttachments = [...state.attachments];

    if (!userText && currentAttachments.length === 0 && !options.regenerate_from_id) {
      return;
    }

    el.promptInput.value = "";
    el.promptInput.style.height = "auto";
    state.attachments = [];
    renderAttachmentsTray();

    state.isStreaming = true;
    el.sendBtn.classList.add("hidden");
    el.stopGenBtn.classList.remove("hidden");
    el.emptyState.classList.add("hidden");

    const sessionId = state.activeSession.id;
    let streamingBody = null;
    let accumulatedText = "";

    try {
      const response = await fetch(`/api/sessions/${sessionId}/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: userText,
          attachments: currentAttachments,
          model: el.modelSelect.value,
          regenerate_from_id: options.regenerate_from_id || null,
          skip_user_save: Boolean(options.skip_user_save),
        }),
      });

      if (!response.ok) throw new Error(await response.text());

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";

        for (const rawEvent of parts) {
          const line = rawEvent.trim();
          if (!line.startsWith("data:")) continue;
          const jsonStr = line.slice(5).trim();
          if (!jsonStr) continue;
          const event = JSON.parse(jsonStr);

          if (event.type === "start") {
            if (event.user_message && !options.skip_user_save) {
              state.activeSession.messages.push(event.user_message);
              el.messagesList.insertAdjacentHTML("beforeend", buildMessageRowHtml(event.user_message));
            }
            if (event.session_title) {
              state.activeSession.title = event.session_title;
              el.sessionTitleInput.value = event.session_title;
            }

            const showImgSkeleton =
              isImageGenerationModel(el.modelSelect.value) || isImagePrompt(userText);

            const streamingRow = document.createElement("div");
            streamingRow.className = "message-row assistant";
            streamingRow.innerHTML = `
              <div class="assistant-container">
                <div class="message-body ${showImgSkeleton ? "" : "streaming-cursor"}"></div>
                <div class="streaming-image-slot">
                  ${
                    showImgSkeleton
                      ? `<div class="image-gen-loader">
                          <div class="image-gen-status">
                            <span class="image-gen-spinner"></span>
                            <span>Creating image...</span>
                          </div>
                        </div>`
                      : ""
                  }
                </div>
              </div>
            `;
            streamingBody = streamingRow.querySelector(".message-body");
            const streamingImageSlot = streamingRow.querySelector(".streaming-image-slot");
            streamingRow._imageSlot = streamingImageSlot;
            el.messagesList.appendChild(streamingRow);
            scrollToBottom();
          } else if (event.type === "delta") {
            accumulatedText += event.delta;
            if (streamingBody) {
              streamingBody.innerHTML = renderMarkdown(accumulatedText);
              scrollToBottom();
            }
          } else if (event.type === "image") {
            const rows = el.messagesList.querySelectorAll(".message-row.assistant");
            const lastRow = rows[rows.length - 1];
            const slot = lastRow && lastRow._imageSlot;
            if (slot && event.image) {
              slot.innerHTML = buildGeneratedImagesHtml([event.image]);
              scrollToBottom();
            }
          } else if (event.type === "done" || event.type === "cancelled") {
            if (event.assistant_message) {
              state.activeSession.messages.push(event.assistant_message);
            }
            await refreshSessionList();
            renderMessages();
          } else if (event.type === "error") {
            if (streamingBody) {
              streamingBody.classList.remove("streaming-cursor");
              streamingBody.innerHTML = `<p style="color: var(--danger)">${escapeHtml(event.error)}</p>`;
            }
          }
        }
      }
    } catch (err) {
      showToast(`Error: ${err.message}`);
    } finally {
      state.isStreaming = false;
      el.stopGenBtn.classList.add("hidden");
      el.sendBtn.classList.remove("hidden");
      el.promptInput.focus();
    }
  }

  async function stopGeneration() {
    if (!state.isStreaming || !state.activeSession) return;
    try {
      await apiSend(`/api/sessions/${state.activeSession.id}/cancel`, "POST");
    } catch (_) {}
  }

  // --- Spotlight Command Palette ---
  const COMMANDS = [
    { id: "new", title: "New Conversation", shortcut: "⌘N", run: () => createNewSession() },
    { id: "clear", title: "Clear Conversation", shortcut: "⌘L", run: () => clearActiveSession() },
    { id: "sidebar", title: "Toggle Sidebar", shortcut: "⌘B", run: () => el.sidebar.classList.toggle("collapsed") },
    { id: "export", title: "Export as Markdown", shortcut: "⌘E", run: () => exportSession() },
    { id: "settings", title: "Settings & API Key", shortcut: "⌘,", run: () => openSettingsModal() },
  ];

  function openCommandPalette() {
    el.cmdPaletteModal.classList.remove("hidden");
    el.cmdPaletteInput.value = "";
    renderCommandPaletteList("");
    el.cmdPaletteInput.focus();
  }

  function closeCommandPalette() {
    el.cmdPaletteModal.classList.add("hidden");
  }

  function renderCommandPaletteList(filterText) {
    const q = filterText.trim().toLowerCase();
    const items = COMMANDS.filter((c) => c.title.toLowerCase().includes(q));
    el.cmdPaletteList.innerHTML = items
      .map(
        (c, i) => `
        <div class="cmd-item ${i === 0 ? "selected" : ""}" data-cmd-id="${c.id}">
          <span>${escapeHtml(c.title)}</span>
          <span class="cmd-item-shortcut">${escapeHtml(c.shortcut)}</span>
        </div>
      `
      )
      .join("");
  }

  function openSettingsModal() {
    el.settingsModal.classList.remove("hidden");
    el.settingsApiKey.value = "";
  }

  function closeSettingsModal() {
    el.settingsModal.classList.add("hidden");
  }

  async function clearActiveSession() {
    if (!state.activeSession || state.isStreaming) return;
    const updated = await apiSend(`/api/sessions/${state.activeSession.id}/clear`, "POST");
    state.activeSession = updated;
    renderMessages();
    await refreshSessionList();
    showToast("Conversation cleared");
  }

  async function exportSession() {
    if (!state.activeSession) return;
    const data = await apiGet(`/api/sessions/${state.activeSession.id}/export?format=markdown`);
    const blob = new Blob([data.content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = data.filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  function bindEvents() {
    el.toggleSidebarBtn.addEventListener("click", () => el.sidebar.classList.toggle("collapsed"));
    el.newSessionBtn.addEventListener("click", createNewSession);
    el.clearSessionBtn.addEventListener("click", clearActiveSession);
    el.exportSessionBtn.addEventListener("click", exportSession);
    el.openSettingsBtn.addEventListener("click", openSettingsModal);
    el.closeSettingsBtn.addEventListener("click", closeSettingsModal);
    el.cancelSettingsBtn.addEventListener("click", closeSettingsModal);

    el.sessionSearchInput.addEventListener("input", () => {
      refreshSessionList(el.sessionSearchInput.value);
    });

    el.sessionList.addEventListener("click", async (e) => {
      const delBtn = e.target.closest("[data-del-id]");
      if (delBtn) {
        e.stopPropagation();
        const sid = delBtn.getAttribute("data-del-id");
        await apiSend(`/api/sessions/${sid}`, "DELETE");
        await refreshSessionList();
        if (state.sessions.length === 0) {
          await createNewSession();
        } else if (state.activeSession && state.activeSession.id === sid) {
          await selectSession(state.sessions[0].id);
        }
        return;
      }

      const item = e.target.closest("[data-session-id]");
      if (item) {
        const sid = item.getAttribute("data-session-id");
        if (!state.activeSession || state.activeSession.id !== sid) {
          await selectSession(sid);
        }
      }
    });

    el.sessionTitleInput.addEventListener("change", async () => {
      if (!state.activeSession) return;
      const newTitle = el.sessionTitleInput.value.trim() || "Untitled";
      await apiSend(`/api/sessions/${state.activeSession.id}`, "PATCH", { title: newTitle });
      await refreshSessionList();
    });

    el.modelSelect.addEventListener("change", async () => {
      if (!state.activeSession) return;
      await apiSend(`/api/sessions/${state.activeSession.id}`, "PATCH", { model: el.modelSelect.value });
      state.activeSession.model = el.modelSelect.value;
    });

    if (el.refreshModelsBtn) {
      el.refreshModelsBtn.addEventListener("click", async () => {
        try {
          const settings = await apiGet("/api/settings?refresh=1");
          state.settings = settings;
          applySettingsToUI(settings);
          if (state.activeSession) {
            el.modelSelect.value = state.activeSession.model;
          }
          showToast(`Synced ${settings.available_models.length} live models`);
        } catch (err) {
          showToast("Failed to sync models");
        }
      });
    }

    document.querySelectorAll(".suggestion-pill").forEach((btn) => {
      btn.addEventListener("click", () => {
        el.promptInput.value = btn.getAttribute("data-prompt");
        el.promptInput.focus();
      });
    });

    el.promptInput.addEventListener("input", () => {
      el.promptInput.style.height = "auto";
      el.promptInput.style.height = `${Math.min(180, el.promptInput.scrollHeight)}px`;
    });

    el.promptInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    el.sendBtn.addEventListener("click", () => sendMessage());
    el.stopGenBtn.addEventListener("click", stopGeneration);

    el.attachFileBtn.addEventListener("click", () => el.fileInput.click());
    el.fileInput.addEventListener("change", (e) => {
      if (e.target.files && e.target.files.length) {
        handleFilesSelected(e.target.files);
        e.target.value = "";
      }
    });

    el.attachmentsTray.addEventListener("click", (e) => {
      const rm = e.target.closest("[data-remove-att]");
      if (rm) {
        const idx = parseInt(rm.getAttribute("data-remove-att"), 10);
        state.attachments.splice(idx, 1);
        renderAttachmentsTray();
      }
    });

    el.dropZone.addEventListener("dragover", (e) => {
      e.preventDefault();
      el.dropOverlay.classList.remove("hidden");
    });
    el.dropZone.addEventListener("dragleave", (e) => {
      if (e.target === el.dropOverlay) el.dropOverlay.classList.add("hidden");
    });
    el.dropZone.addEventListener("drop", (e) => {
      e.preventDefault();
      el.dropOverlay.classList.add("hidden");
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
        handleFilesSelected(e.dataTransfer.files);
      }
    });

    document.body.addEventListener("click", async (e) => {
      const lightboxImg = e.target.closest("[data-lightbox-src]");
      if (lightboxImg) {
        const src = lightboxImg.getAttribute("data-lightbox-src");
        const lb = document.createElement("div");
        lb.className = "lightbox-backdrop";
        lb.innerHTML = `<img src="${src}" alt="Full size preview" />`;
        lb.addEventListener("click", () => lb.remove());
        document.body.appendChild(lb);
        return;
      }

      const copyCodeBtn = e.target.closest("[data-copy-code]");
      if (copyCodeBtn) {
        const code = decodeURIComponent(copyCodeBtn.getAttribute("data-copy-code"));
        await navigator.clipboard.writeText(code);
        const orig = copyCodeBtn.textContent;
        copyCodeBtn.textContent = "Copied";
        setTimeout(() => (copyCodeBtn.textContent = orig), 1200);
        return;
      }

      const saveCodeBtn = e.target.closest("[data-download-code]");
      if (saveCodeBtn) {
        const code = decodeURIComponent(saveCodeBtn.getAttribute("data-download-code"));
        const lang = saveCodeBtn.getAttribute("data-lang") || "txt";
        const blob = new Blob([code], { type: "text/plain;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `snippet.${lang}`;
        a.click();
        URL.revokeObjectURL(url);
        return;
      }

      const copyMsgBtn = e.target.closest("[data-copy-msg]");
      if (copyMsgBtn) {
        const text = decodeURIComponent(copyMsgBtn.getAttribute("data-copy-msg"));
        await navigator.clipboard.writeText(text);
        showToast("Copied");
        return;
      }

      const regenBtn = e.target.closest("[data-regen-msg]");
      if (regenBtn && !state.isStreaming) {
        const msgId = regenBtn.getAttribute("data-regen-msg");
        await sendMessage({ regenerate_from_id: msgId, skip_user_save: true });
      }
    });

    // Settings sheet interactions
    el.personaSelect.addEventListener("change", () => {
      const pid = el.personaSelect.value;
      const personas = (state.settings && state.settings.personas) || [];
      const found = personas.find((p) => p.id === pid);
      if (found) el.sessionSystemPrompt.value = found.prompt;
    });

    el.sessionTempSlider.addEventListener("input", () => {
      el.tempValLabel.textContent = `Temp: ${Number(el.sessionTempSlider.value).toFixed(2)}`;
    });

    el.validateKeyBtn.addEventListener("click", async () => {
      const rawKey = el.settingsApiKey.value.trim();
      el.validateKeyBtn.textContent = "...";
      try {
        const res = await apiSend("/api/settings/validate-key", "POST", { api_key: rawKey });
        if (res.valid) {
          el.apiKeyStatusMsg.innerHTML = `<span style="color: var(--green)">✓ Verified</span>`;
          const updated = await apiGet("/api/settings");
          state.settings = updated;
          applySettingsToUI(updated);
        } else {
          el.apiKeyStatusMsg.innerHTML = `<span style="color: var(--danger)">Invalid key</span>`;
        }
      } catch (err) {
        el.apiKeyStatusMsg.innerHTML = `<span style="color: var(--danger)">Failed to verify</span>`;
      } finally {
        el.validateKeyBtn.textContent = "Verify";
      }
    });

    el.saveSettingsBtn.addEventListener("click", async () => {
      const payload = {
        model: el.settingsDefaultModel.value,
      };
      if (el.settingsApiKey.value.trim()) {
        payload.api_key = el.settingsApiKey.value.trim();
      }
      const updated = await apiSend("/api/settings", "POST", payload);
      state.settings = updated;
      applySettingsToUI(updated);

      if (state.activeSession) {
        await apiSend(`/api/sessions/${state.activeSession.id}`, "PATCH", {
          persona_id: el.personaSelect.value,
          system_instruction: el.sessionSystemPrompt.value,
          temperature: parseFloat(el.sessionTempSlider.value),
        });
      }
      closeSettingsModal();
      showToast("Saved");
    });

    el.cmdPaletteInput.addEventListener("input", () => {
      renderCommandPaletteList(el.cmdPaletteInput.value);
    });

    el.cmdPaletteList.addEventListener("click", (e) => {
      const item = e.target.closest("[data-cmd-id]");
      if (item) {
        const cid = item.getAttribute("data-cmd-id");
        const cmd = COMMANDS.find((c) => c.id === cid);
        closeCommandPalette();
        if (cmd) cmd.run();
      }
    });

    window.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (el.cmdPaletteModal.classList.contains("hidden")) openCommandPalette();
        else closeCommandPalette();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "n") {
        e.preventDefault();
        createNewSession();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        el.sidebar.classList.toggle("collapsed");
      } else if ((e.ctrlKey || e.metaKey) && e.key === ",") {
        e.preventDefault();
        openSettingsModal();
      } else if (e.key === "Escape") {
        if (!el.cmdPaletteModal.classList.contains("hidden")) closeCommandPalette();
        else if (!el.settingsModal.classList.contains("hidden")) closeSettingsModal();
        else if (state.isStreaming) stopGeneration();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", initApp);
})();
