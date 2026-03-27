const state = {
  jobs: [],
  selectedFiles: [],
  pollTimer: null,
  settingsReady: false,
  pagination: {
    processing: 1,
    completed: 1,
  },
};

const PAGE_SIZE = 2;

const STATUS_LABELS = {
  queued: "\u7b49\u5f85\u5f00\u59cb",
  running: "\u5904\u7406\u4e2d",
  completed: "\u5df2\u5b8c\u6210",
  stopped: "\u5df2\u505c\u6b62",
  interrupted: "\u5df2\u4e2d\u65ad",
};

const MODE_LABELS = {
  fast: "\u5feb\u901f",
  standard: "\u6807\u51c6",
  deep: "\u6df1\u5ea6",
};

const COPY = {
  emptySelection: "\u5c1a\u672a\u9009\u62e9\u6587\u4ef6\u3002\u4f60\u53ef\u4ee5\u591a\u6b21\u6dfb\u52a0\uff0c\u7cfb\u7edf\u4f1a\u7d2f\u8ba1\u5230\u540c\u4e00\u6279\u6b21\u4e2d\u3002",
  remove: "\u79fb\u9664",
  loadSettingsFailed: "\u52a0\u8f7d\u914d\u7f6e\u5931\u8d25",
  saveSettingsFailed: "\u4fdd\u5b58\u914d\u7f6e\u5931\u8d25",
  settingsSaved: "\u914d\u7f6e\u5df2\u4fdd\u5b58\u3002",
  conflictPrefix: "\u68c0\u6d4b\u5230\u540c\u540d PDF \u5185\u5bb9\u5df2\u53d8\u5316\uff1a",
  conflictExplain: "\u7cfb\u7edf\u4f1a\u7f13\u5b58\u89e3\u6790\u7ed3\u679c\uff1b\u5982\u679c\u4e0d\u91cd\u65b0\u89e3\u6790\uff0c\u540e\u7eed\u7ed3\u679c\u53ef\u80fd\u7ee7\u7eed\u6cbf\u7528\u65e7\u89e3\u6790\u5185\u5bb9\u3002",
  conflictQuestion: "\u662f\u5426\u6309\u5f53\u524d\u65b0\u6587\u4ef6\u91cd\u65b0\u89e3\u6790\u5e76\u7ee7\u7eed\u63d0\u4ea4\uff1f",
  submitCancelled: "\u5df2\u53d6\u6d88\u63d0\u4ea4\u3002",
  submitFailed: "\u63d0\u4ea4\u4efb\u52a1\u5931\u8d25",
  submitSucceeded: "\u6587\u4ef6\u5df2\u52a0\u5165\u5904\u7406\u961f\u5217\u3002",
  modeLabel: "\u6a21\u5f0f\uff1a",
  attemptLabel: "\u8f6e\u6b21\uff1a",
  processingEmpty: "\u5f53\u524d\u6ca1\u6709\u6b63\u5728\u5904\u7406\u6216\u7b49\u5f85\u5f00\u59cb\u7684\u4efb\u52a1\u3002",
  completedEmpty: "\u5df2\u5b8c\u6210\u3001\u5df2\u505c\u6b62\u6216\u4e2d\u65ad\u7684\u4efb\u52a1\u4f1a\u663e\u793a\u5728\u8fd9\u91cc\u3002",
  refreshFailed: "\u5237\u65b0\u4efb\u52a1\u5217\u8868\u5931\u8d25",
  stopFailed: "\u505c\u6b62\u4efb\u52a1\u5931\u8d25",
  stopSucceeded: "\u5df2\u53d1\u9001\u505c\u6b62\u8bf7\u6c42\u3002",
  retryFailed: "\u91cd\u65b0\u5165\u961f\u5931\u8d25",
  retrySucceeded: "\u4efb\u52a1\u5df2\u91cd\u65b0\u52a0\u5165\u5904\u7406\u961f\u5217\u3002",
  deletePrompt: "\u5220\u9664\u8be5\u4efb\u52a1\u8bb0\u5f55\u53ca\u5176\u751f\u6210\u6587\u4ef6\uff1f\u6b64\u64cd\u4f5c\u4e0d\u53ef\u6062\u590d\u3002",
  deleteFailed: "\u5220\u9664\u4efb\u52a1\u5931\u8d25",
  deleteSucceeded: "\u4efb\u52a1\u8bb0\u5f55\u5df2\u5220\u9664\u3002",
  actionFailed: "\u4efb\u52a1\u64cd\u4f5c\u5931\u8d25",
  initFailed: "\u521d\u59cb\u5316\u9875\u9762\u5931\u8d25",
  settingsHintInvalidKey:
    "\u5f53\u524d\u914d\u7f6e\u4e2d\u7684 API \u5bc6\u94a5\u4e0d\u53ef\u7528\u3002\u8bf7\u70b9\u51fb\u53f3\u4e0a\u89d2\u201c\u914d\u7f6e\u201d\uff0c\u91cd\u65b0\u586b\u5199\u771f\u5b9e API \u5bc6\u94a5\u5e76\u4fdd\u5b58\u3002",
  settingsHintInvalidBaseUrl: "API \u63a5\u53e3\u5730\u5740\u4e0d\u6b63\u786e\uff0c\u8bf7\u5728\u914d\u7f6e\u4e2d\u68c0\u67e5\u540e\u4fdd\u5b58\u3002",
  settingsHintInvalidModel: "\u6a21\u578b\u540d\u79f0\u4e0d\u80fd\u4e3a\u7a7a\uff0c\u8bf7\u5728\u914d\u7f6e\u4e2d\u8865\u5168\u540e\u4fdd\u5b58\u3002",
  settingsHintMissingPdfApiUrl:
    "PDF \u7cbe\u51c6\u6a21\u5f0f\u9700\u8981\u586b\u5199 PaddleOCR API \u5730\u5740\uff0c\u5426\u5219\u65e0\u6cd5\u89e3\u6790 PDF\u3002",
  settingsHintInvalidPdfApiUrl:
    "PaddleOCR API \u5730\u5740\u5fc5\u987b\u4ee5 http:// \u6216 https:// \u5f00\u5934\uff0c\u8bf7\u68c0\u67e5\u540e\u4fdd\u5b58\u3002",
  settingsHintMissingPdfApiKey:
    "PDF \u7cbe\u51c6\u6a21\u5f0f\u9700\u8981\u586b\u5199 PaddleOCR Token\uff0c\u5426\u5219\u65e0\u6cd5\u63d0\u4ea4 PDF \u89e3\u6790\u4efb\u52a1\u3002",
  settingsHintMissingPdfApiModel:
    "PDF \u7cbe\u51c6\u6a21\u5f0f\u9700\u8981\u586b\u5199 PaddleOCR \u6a21\u578b\u540d\u79f0\u3002",
  submitBlocked:
    "\u5f53\u524d\u914d\u7f6e\u4e0d\u53ef\u6267\u884c\uff0c\u8bf7\u5148\u70b9\u51fb\u53f3\u4e0a\u89d2\u201c\u914d\u7f6e\u201d\u5b8c\u6210\u4fe1\u606f\u586b\u5199\u5e76\u4fdd\u5b58\u3002",
  interruptedHint:
    "\u4efb\u52a1\u5df2\u4e2d\u65ad\u3002\u82e5\u8fd9\u662f\u65e7\u4efb\u52a1\uff0c\u8bf7\u5148\u5728\u201c\u914d\u7f6e\u201d\u4e2d\u91cd\u65b0\u586b\u5199\u5e76\u4fdd\u5b58 API \u5bc6\u94a5\uff0c\u7136\u540e\u70b9\u51fb\u201c\u91cd\u65b0\u5165\u961f\u201d\u3002",
  openReport: "\u67e5\u770b\u62a5\u544a",
  retry: "\u91cd\u65b0\u5165\u961f",
  stop: "\u505c\u6b62",
  delete: "\u5220\u9664\u8bb0\u5f55",
};

const elements = {
  apiKey: document.getElementById("api-key"),
  baseUrl: document.getElementById("base-url"),
  model: document.getElementById("model"),
  runName: document.getElementById("run-name"),
  pdfParseMode: document.getElementById("pdf-parse-mode"),
  paddleocrApiUrl: document.getElementById("paddleocr-api-url"),
  paddleocrApiKey: document.getElementById("paddleocr-api-key"),
  paddleocrApiModel: document.getElementById("paddleocr-api-model"),
  mode: document.getElementById("mode"),
  fileInput: document.getElementById("file-input"),
  dropZone: document.getElementById("drop-zone"),
  selectedFiles: document.getElementById("selected-files"),
  settingsHint: document.getElementById("settings-hint"),
  clearFiles: document.getElementById("clear-files"),
  submitFiles: document.getElementById("submit-files"),
  processingJobs: document.getElementById("processing-jobs"),
  completedJobs: document.getElementById("completed-jobs"),
  processingCount: document.getElementById("processing-count"),
  completedCount: document.getElementById("completed-count"),
  processingBadge: document.getElementById("processing-badge"),
  completedBadge: document.getElementById("completed-badge"),
  processingPrev: document.getElementById("processing-prev"),
  processingPage: document.getElementById("processing-page"),
  processingNext: document.getElementById("processing-next"),
  completedPrev: document.getElementById("completed-prev"),
  completedPage: document.getElementById("completed-page"),
  completedNext: document.getElementById("completed-next"),
  openSettings: document.getElementById("open-settings"),
  closeSettings: document.getElementById("close-settings"),
  cancelSettings: document.getElementById("cancel-settings"),
  saveSettings: document.getElementById("save-settings"),
  settingsModal: document.getElementById("settings-modal"),
  notification: document.getElementById("notification"),
};

function showNotification(message, kind = "") {
  elements.notification.textContent = message;
  elements.notification.className = `notification show ${kind}`.trim();
  window.clearTimeout(showNotification._timer);
  showNotification._timer = window.setTimeout(() => {
    elements.notification.className = "notification";
  }, 3200);
}

function humanizeBytes(size) {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(size >= 10 * 1024 ? 0 : 1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(size >= 10 * 1024 * 1024 ? 0 : 1)} MB`;
}

function fileNameKey(file) {
  return file.name.trim().toLowerCase();
}

function makeFileEntry(file) {
  return {
    key: `${fileNameKey(file)}::${file.size}::${file.lastModified}`,
    nameKey: fileNameKey(file),
    file,
  };
}

function openSettingsModal() {
  elements.settingsModal.classList.remove("hidden");
  elements.settingsModal.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
}

function closeSettingsModal() {
  elements.settingsModal.classList.add("hidden");
  elements.settingsModal.setAttribute("aria-hidden", "true");
  document.body.classList.remove("modal-open");
}

function selectedFilesContainPdf() {
  return state.selectedFiles.some(({ file }) => file.name.toLowerCase().endsWith(".pdf"));
}

function currentSettingsError() {
  const apiKey = elements.apiKey.value.trim();
  const baseUrl = elements.baseUrl.value.trim();
  const model = elements.model.value.trim();
  const pdfParseMode = elements.pdfParseMode.value.trim();
  const paddleocrApiUrl = elements.paddleocrApiUrl.value.trim();
  const paddleocrApiKey = elements.paddleocrApiKey.value.trim();
  const paddleocrApiModel = elements.paddleocrApiModel.value.trim();
  const accuratePdfRequested = pdfParseMode === "accurate" && selectedFilesContainPdf();

  if (!apiKey || apiKey === "***" || apiKey === "your_api_key") {
    return COPY.settingsHintInvalidKey;
  }
  if (!baseUrl || !baseUrl.startsWith("http://") && !baseUrl.startsWith("https://")) {
    return COPY.settingsHintInvalidBaseUrl;
  }
  if (baseUrl.replace(/\/+$/, "").endsWith("/chat/completions")) {
    return COPY.settingsHintInvalidBaseUrl;
  }
  if (!model) {
    return COPY.settingsHintInvalidModel;
  }
  if (accuratePdfRequested && !paddleocrApiUrl) {
    return COPY.settingsHintMissingPdfApiUrl;
  }
  if (paddleocrApiUrl && !paddleocrApiUrl.startsWith("http://") && !paddleocrApiUrl.startsWith("https://")) {
    return COPY.settingsHintInvalidPdfApiUrl;
  }
  if (accuratePdfRequested && (!paddleocrApiKey || paddleocrApiKey === "***")) {
    return COPY.settingsHintMissingPdfApiKey;
  }
  if (accuratePdfRequested && !paddleocrApiModel) {
    return COPY.settingsHintMissingPdfApiModel;
  }
  return "";
}

function renderSettingsHint() {
  const message = currentSettingsError();
  state.settingsReady = !message;
  elements.settingsHint.hidden = !message;
  elements.settingsHint.textContent = message;
  renderSelectedFiles();
}

function renderSelectedFiles() {
  elements.submitFiles.disabled = state.selectedFiles.length === 0 || !state.settingsReady;
  elements.clearFiles.disabled = state.selectedFiles.length === 0;

  if (!state.selectedFiles.length) {
    elements.selectedFiles.className = "selected-files empty";
    elements.selectedFiles.textContent = COPY.emptySelection;
    return;
  }

  elements.selectedFiles.className = "selected-files";
  elements.selectedFiles.innerHTML = state.selectedFiles
    .map(({ key, file }) => {
      const extension = (file.name.split(".").pop() || "FILE").toUpperCase();
      return `
        <article class="selected-file">
          <div class="selected-file-main">
            <div class="selected-file-name">${file.name}</div>
            <div class="selected-file-meta">
              <span>${extension}</span>
              <span>${humanizeBytes(file.size)}</span>
            </div>
          </div>
          <button class="action tertiary" type="button" data-action="remove-file" data-file-key="${key}">${COPY.remove}</button>
        </article>
      `;
    })
    .join("");
}

function mergeSelectedFiles(fileList) {
  const merged = new Map(state.selectedFiles.map((entry) => [entry.nameKey, entry]));
  for (const file of Array.from(fileList)) {
    merged.set(fileNameKey(file), makeFileEntry(file));
  }
  state.selectedFiles = Array.from(merged.values());
  renderSettingsHint();
}

function removeSelectedFile(fileKey) {
  state.selectedFiles = state.selectedFiles.filter((entry) => entry.key !== fileKey);
  renderSettingsHint();
}

function clearSelectedFiles() {
  state.selectedFiles = [];
  elements.fileInput.value = "";
  renderSettingsHint();
}

function applySettings(config) {
  const llm = config.llm || {};
  const parser = config.parser || {};
  const run = config.run || {};
  elements.apiKey.value = llm.api_key || "";
  elements.baseUrl.value = llm.base_url || "https://api.openai.com/v1";
  elements.model.value = llm.model || "gpt-4o-mini";
  elements.runName.value = run.run_name || "";
  elements.pdfParseMode.value = parser.pdf_parse_mode || "fast";
  elements.paddleocrApiUrl.value = parser.paddleocr_api_url || "";
  elements.paddleocrApiKey.value = parser.paddleocr_api_key || "";
  elements.paddleocrApiModel.value = parser.paddleocr_api_model || "PaddleOCR-VL-1.5";
  renderSettingsHint();
}

async function loadSettings() {
  const response = await fetch("/api/settings");
  if (!response.ok) {
    throw new Error(COPY.loadSettingsFailed);
  }
  const config = await response.json();
  applySettings(config);
}

async function saveSettings() {
  const error = currentSettingsError();
  if (error) {
    throw new Error(error);
  }
  const currentPdfParseMode = elements.pdfParseMode.value;
  const payload = {
    llm: {
      api_key: elements.apiKey.value.trim(),
      base_url: elements.baseUrl.value.trim(),
      model: elements.model.value.trim(),
    },
    parser: {
      paddleocr_api_url: elements.paddleocrApiUrl.value.trim(),
      paddleocr_api_key: elements.paddleocrApiKey.value.trim(),
      paddleocr_api_model: elements.paddleocrApiModel.value.trim(),
    },
    run: {
      run_name: elements.runName.value.trim() || null,
    },
  };
  const response = await fetch("/api/settings", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || COPY.saveSettingsFailed);
  }
  applySettings(data);
  elements.pdfParseMode.value = currentPdfParseMode;
  renderSettingsHint();
  closeSettingsModal();
  showNotification(COPY.settingsSaved, "success");
}

async function postJobs(confirmReparse = false) {
  const formData = new FormData();
  formData.append("mode", elements.mode.value);
  formData.append("pdf_parse_mode", elements.pdfParseMode.value);
  if (confirmReparse) {
    formData.append("confirm_reparse", "true");
  }
  for (const entry of state.selectedFiles) {
    formData.append("files", entry.file);
  }
  const response = await fetch("/api/jobs", {
    method: "POST",
    body: formData,
  });
  const data = await response.json();
  return { response, data };
}

function buildConflictMessage(conflicts) {
  const filenames = conflicts.map((item) => item.filename).join("\u3001");
  return [
    `${COPY.conflictPrefix}${filenames}\u3002`,
    "",
    COPY.conflictExplain,
    "",
    COPY.conflictQuestion,
  ].join("\n");
}

async function submitFiles() {
  if (!state.selectedFiles.length) {
    return;
  }
  if (!state.settingsReady) {
    showNotification(currentSettingsError() || COPY.submitBlocked, "error");
    return;
  }

  let result = await postJobs(false);
  if (result.response.status === 409 && result.data.requires_confirmation) {
    const confirmed = window.confirm(buildConflictMessage(result.data.conflicts || []));
    if (!confirmed) {
      showNotification(COPY.submitCancelled, "error");
      return;
    }
    result = await postJobs(true);
  }

  if (!result.response.ok) {
    throw new Error(result.data.error || COPY.submitFailed);
  }

  clearSelectedFiles();
  await pollJobs();
  showNotification(COPY.submitSucceeded, "success");
}

function renderJobList(container, jobs, emptyText, queueKind) {
  if (!jobs.length) {
    container.innerHTML = `<div class="empty-state">${emptyText}</div>`;
    return;
  }

  container.innerHTML = jobs
    .map((job) => {
      const progress = job.progress || { percent: 0, label: STATUS_LABELS.queued, detail: "" };
      const progressStages = renderProgressStages(job, progress);
      let detailText = progress.detail || "";
      if (
        job.status === "interrupted" &&
        (!detailText || detailText === "\u5df2\u5b8c\u6210" || progress.label === "\u5b8c\u6210")
      ) {
        detailText = COPY.interruptedHint;
      }
      const detail = detailText ? `<div class="job-detail">${detailText}</div>` : "";
      const actions = [];

      if (queueKind === "processing") {
        actions.push(`<button class="action warning" type="button" data-action="stop" data-job-id="${job.job_id}">${COPY.stop}</button>`);
      }

      if (queueKind === "completed") {
        if (job.status === "completed" && job.report_url) {
          actions.push(
            `<button class="action success" type="button" data-action="report" data-job-id="${job.job_id}" data-report-url="${job.report_url}">${COPY.openReport}</button>`,
          );
        }
        if (job.status === "stopped" || job.status === "interrupted") {
          actions.push(`<button class="action secondary" type="button" data-action="retry" data-job-id="${job.job_id}">${COPY.retry}</button>`);
        }
        actions.push(`<button class="action danger" type="button" data-action="delete" data-job-id="${job.job_id}">${COPY.delete}</button>`);
      }

      return `
        <article class="job-card">
          <div class="job-row">
            <div>
              <div class="job-name">${job.input_filename}</div>
              <div class="job-meta">
                <span>${COPY.modeLabel}${MODE_LABELS[job.mode] || job.mode}</span>
                <span>${COPY.attemptLabel}${job.attempt_count}</span>
              </div>
            </div>
            <span class="job-status" data-status="${job.status}">${STATUS_LABELS[job.status] || job.status}</span>
          </div>
          <div class="progress">
            <div class="progress-head">
              <span>${progress.label || STATUS_LABELS.queued}</span>
              <span>${progress.percent || 0}%</span>
            </div>
            <div class="progress-track">
              <div class="progress-fill" style="width:${Math.max(0, Math.min(100, progress.percent || 0))}%"></div>
            </div>
            ${progressStages}
          </div>
          ${detail}
          ${actions.length ? `<div class="job-actions">${actions.join("")}</div>` : ""}
        </article>
      `;
    })
    .join("");
}

function renderProgressStages(job, progress) {
  const stages = [
    { key: "parsing", label: job.input_filename.toLowerCase().endsWith(".pdf") ? "PDF\u89e3\u6790" : "\u6587\u6863\u89e3\u6790" },
    { key: "analyzing", label: "Agent\u68c0\u6d4b" },
    { key: "reporting", label: "\u62a5\u544a\u751f\u6210" },
  ];
  const currentIndex = stages.findIndex((stage) => stage.key === progress.stage);

  return `
    <div class="progress-stages" aria-hidden="true">
      ${stages
        .map((stage, index) => {
          const classes = ["progress-stage"];
          if (job.status === "completed" || (currentIndex >= 0 && index < currentIndex)) {
            classes.push("is-complete");
          }
          if (job.status !== "completed" && index === currentIndex) {
            classes.push("is-active");
          }
          return `<span class="${classes.join(" ")}">${stage.label}</span>`;
        })
        .join("")}
    </div>
  `;
}

function getPaginatedJobs(queueKind, jobs) {
  const totalPages = jobs.length ? Math.ceil(jobs.length / PAGE_SIZE) : 0;
  const currentPage = totalPages ? Math.min(state.pagination[queueKind], totalPages) : 1;
  state.pagination[queueKind] = currentPage;
  const startIndex = totalPages ? (currentPage - 1) * PAGE_SIZE : 0;
  return {
    jobs: jobs.slice(startIndex, startIndex + PAGE_SIZE),
    currentPage,
    totalPages,
  };
}

function renderPagination(queueKind, totalPages, currentPage) {
  const prevButton = elements[`${queueKind}Prev`];
  const nextButton = elements[`${queueKind}Next`];
  const pageIndicator = elements[`${queueKind}Page`];

  prevButton.disabled = totalPages <= 1 || currentPage <= 1;
  nextButton.disabled = totalPages <= 1 || currentPage >= totalPages;
  pageIndicator.textContent = totalPages ? `${currentPage} / ${totalPages}` : "0 / 0";
}

function renderQueues() {
  const processingJobs = state.jobs.filter((job) => job.status === "queued" || job.status === "running");
  const completedJobs = state.jobs.filter(
    (job) => job.status === "completed" || job.status === "stopped" || job.status === "interrupted",
  );
  const processingPage = getPaginatedJobs("processing", processingJobs);
  const completedPage = getPaginatedJobs("completed", completedJobs);

  elements.processingCount.textContent = String(processingJobs.length);
  elements.completedCount.textContent = String(completedJobs.length);
  elements.processingBadge.textContent = `${processingJobs.length} \u9879`;
  elements.completedBadge.textContent = `${completedJobs.length} \u9879`;

  renderJobList(elements.processingJobs, processingPage.jobs, COPY.processingEmpty, "processing");
  renderJobList(elements.completedJobs, completedPage.jobs, COPY.completedEmpty, "completed");
  renderPagination("processing", processingPage.totalPages, processingPage.currentPage);
  renderPagination("completed", completedPage.totalPages, completedPage.currentPage);
}

async function pollJobs() {
  const response = await fetch("/api/jobs");
  if (!response.ok) {
    throw new Error(COPY.refreshFailed);
  }
  const data = await response.json();
  state.jobs = Array.isArray(data.jobs) ? data.jobs : [];
  renderQueues();
}

async function stopJob(jobId) {
  const response = await fetch(`/api/jobs/${jobId}/stop`, { method: "POST" });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || COPY.stopFailed);
  }
  await pollJobs();
  showNotification(COPY.stopSucceeded, "success");
}

async function retryJob(jobId) {
  const response = await fetch(`/api/jobs/${jobId}/retry`, { method: "POST" });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || COPY.retryFailed);
  }
  await pollJobs();
  showNotification(COPY.retrySucceeded, "success");
}

async function deleteJob(jobId) {
  const confirmed = window.confirm(COPY.deletePrompt);
  if (!confirmed) {
    return;
  }
  const response = await fetch(`/api/jobs/${jobId}`, { method: "DELETE" });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || COPY.deleteFailed);
  }
  await pollJobs();
  showNotification(COPY.deleteSucceeded, "success");
}

function bindEvents() {
  elements.openSettings.addEventListener("click", openSettingsModal);
  elements.closeSettings.addEventListener("click", closeSettingsModal);
  elements.cancelSettings.addEventListener("click", closeSettingsModal);
  for (const field of [
    elements.apiKey,
    elements.baseUrl,
    elements.model,
    elements.runName,
    elements.pdfParseMode,
    elements.paddleocrApiUrl,
    elements.paddleocrApiKey,
    elements.paddleocrApiModel,
  ]) {
    field.addEventListener("input", renderSettingsHint);
    field.addEventListener("change", renderSettingsHint);
  }
  elements.saveSettings.addEventListener("click", async () => {
    try {
      await saveSettings();
    } catch (error) {
      showNotification(error.message || COPY.saveSettingsFailed, "error");
    }
  });

  elements.settingsModal.addEventListener("click", (event) => {
    const target = event.target;
    if (target instanceof HTMLElement && target.dataset.closeModal === "true") {
      closeSettingsModal();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !elements.settingsModal.classList.contains("hidden")) {
      closeSettingsModal();
    }
  });

  elements.fileInput.addEventListener("change", (event) => {
    mergeSelectedFiles(event.target.files || []);
    elements.fileInput.value = "";
  });

  elements.dropZone.addEventListener("dragover", (event) => {
    event.preventDefault();
    elements.dropZone.classList.add("is-dragover");
  });

  elements.dropZone.addEventListener("dragleave", () => {
    elements.dropZone.classList.remove("is-dragover");
  });

  elements.dropZone.addEventListener("drop", (event) => {
    event.preventDefault();
    elements.dropZone.classList.remove("is-dragover");
    mergeSelectedFiles(event.dataTransfer.files || []);
  });

  elements.clearFiles.addEventListener("click", clearSelectedFiles);
  elements.processingPrev.addEventListener("click", () => {
    if (state.pagination.processing > 1) {
      state.pagination.processing -= 1;
      renderQueues();
    }
  });
  elements.processingNext.addEventListener("click", () => {
    state.pagination.processing += 1;
    renderQueues();
  });
  elements.completedPrev.addEventListener("click", () => {
    if (state.pagination.completed > 1) {
      state.pagination.completed -= 1;
      renderQueues();
    }
  });
  elements.completedNext.addEventListener("click", () => {
    state.pagination.completed += 1;
    renderQueues();
  });

  elements.selectedFiles.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    if (target.dataset.action === "remove-file") {
      removeSelectedFile(target.dataset.fileKey);
    }
  });

  elements.submitFiles.addEventListener("click", async () => {
    try {
      await submitFiles();
    } catch (error) {
      showNotification(error.message || COPY.submitFailed, "error");
    }
  });

  for (const container of [elements.processingJobs, elements.completedJobs]) {
    container.addEventListener("click", async (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) {
        return;
      }
      const action = target.dataset.action;
      const jobId = target.dataset.jobId;
      if (!action || !jobId) {
        return;
      }

      try {
        if (action === "report") {
          window.open(target.dataset.reportUrl, "_blank", "noopener");
          return;
        }
        if (action === "stop") {
          await stopJob(jobId);
          return;
        }
        if (action === "retry") {
          await retryJob(jobId);
          return;
        }
        if (action === "delete") {
          await deleteJob(jobId);
        }
      } catch (error) {
        showNotification(error.message || COPY.actionFailed, "error");
      }
    });
  }
}

async function init() {
  bindEvents();
  renderSettingsHint();
  renderSelectedFiles();
  try {
    await loadSettings();
    await pollJobs();
  } catch (error) {
    showNotification(error.message || COPY.initFailed, "error");
  }
  state.pollTimer = window.setInterval(() => {
    pollJobs().catch((error) => showNotification(error.message || COPY.refreshFailed, "error"));
  }, 2000);
}

document.addEventListener("DOMContentLoaded", init);
