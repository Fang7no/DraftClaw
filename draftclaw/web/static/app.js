const { createApp, ref, reactive, computed, watch, onMounted, onBeforeUnmount, nextTick } = Vue;

const STORAGE_KEYS = {
  uiLang: "draftclaw-ui-lang",
  reportLang: "draftclaw-report-lang",
  lastTaskId: "draftclaw-last-task-id",
};

const MODE_CONFIG = {
  fast: { vision: false, search: false },
  standard: { vision: true, search: false },
  deep: { vision: true, search: true },
};

const TASKS_PER_PAGE = 3;

const SEVERITY_RANK = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

const MESSAGES = {
  zh: {
    uploadDescription: "配置必要接口后上传论文，任务与结果会保留，刷新页面不会丢失。",
    settingsTitle: "系统配置",
    savingSettings: "保存中...",
    saveSettings: "保存设置",
    launchTitle: "上传与检测",
    reportLanguageLabel: "报告语言",
    langChinese: "中文",
    langEnglish: "English",
    dropzoneTitle: "点击或拖拽上传 PDF",
    dropzoneDescription: "支持点击与拖拽上传，当前系统一次只处理一个任务。",
    missingConfigTitle: "配置未完成",
    singleTaskLimitTitle: "已有运行中的任务",
    singleTaskLimitBody: "当前已有任务在排队或运行，请先进入该任务或等待完成后再上传。",
    uploading: "上传并启动中...",
    startReview: "开始检测",
    resumeLastTask: "继续上次任务",
    activeTasks: "进行中任务",
    completedTasks: "已完成任务",
    loadingTasks: "正在加载任务列表",
    noActiveTasks: "当前没有进行中的任务。",
    noCompletedTasks: "当前没有已完成任务。",
    openTask: "查看",
    deleteTask: "删除",
    deletingTask: "删除中...",
    terminateTask: "终止",
    terminatingTask: "终止中...",
    deleteTaskConfirm: "删除这个任务以及关联文件？",
    terminateTaskConfirm: "终止当前检测任务？已完成的中间结果会尽量保留。",
    deleteTaskFailedTitle: "删除任务失败",
    terminateTaskFailedTitle: "终止任务失败",
    backToUpload: "返回上传页",
    refreshTask: "刷新任务",
    pdfTitle: "PDF 对照",
    locationLegend: "Location",
    evidenceLegend: "Evidence",
    page: "页",
    zoomOut: "缩小",
    zoomIn: "放大",
    loadingPdf: "正在加载 PDF",
    pdfWaiting: "PDF 尚未准备好。",
    issuesTitle: "问题列表",
    confirmedIssues: "确认问题",
    rejectedIssues: "被剔除",
    allIssues: "全部",
    searchIssues: "搜索问题内容",
    taskWaiting: "还没有可展示的任务。",
    issuesStreaming: "正在持续生成问题。",
    noIssuesFound: "当前没有问题。",
    chunkLabel: "Chunk",
    emptyValue: "暂无",
    processTitle: "检测过程",
    waiting: "等待中",
    noLogsYet: "还没有过程日志。",
    modeFast: "Fast",
    modeFastCopy: "基础 explore，速度最快。",
    modeStandard: "Standard",
    modeStandardCopy: "每个 chunk 后接 Vision 校验。",
    modeDeep: "Deep",
    modeDeepCopy: "在 Standard 上增加 Search。",
    statusPending: "排队中",
    statusRunning: "运行中",
    statusCancelling: "终止中",
    statusCancelled: "已终止",
    statusCompleted: "已完成",
    statusFailed: "失败",
    configSavedTitle: "配置已保存",
    configSavedBody: "运行时配置已刷新。",
    configSaveFailedTitle: "配置保存失败",
    uploadFailedTitle: "任务创建失败",
    uploadConflictTitle: "已有活动任务",
    uploadStartedTitle: "任务已创建",
    uploadStartedBody: "正在进入检测界面。",
    missingMineruKey: "MinerU API Key",
    missingQwenKey: "Qwen API Key",
    missingSerperKey: "Serper API Key",
    bboxReady: "已定位 bbox",
    bboxMissing: "未定位 bbox",
    decisionKeep: "已确认",
    decisionReview: "待复核",
    decisionUnchecked: "未复核",
    decisionDrop: "已剔除",
    issueCount: "个问题",
    descriptionLegend: "Description",
    reasoningLegend: "Reasoning",
    chatTitle: "对话窗口",
    chatReserved: "保留，暂未实现发送指令",
    chatPlaceholder: "后续可在此输入对模型的指令",
    chatSend: "发送",
    workflowPreprocessing: "Preprocessing",
    workflowPreprocessingDesc: "PDF 解析、Chunk 划分",
    workflowFinding: "Finding",
    workflowFindingDesc: "发现并确认问题",
    processDone: "done!",
    processRunning: "running...",
    processPending: "pending...",
    processFailed: "failed",
    processPdfParsing: "PDF Parsing",
    processChunkDividing: "Chunk Dividing",
    processChunk: "Chunk",
    processChunkReading: "Chunk Reading",
    processChunkReview: "Chunk Review",
    processPdfParser: "PDF Parser",
    processPlanAgent: "Plan Agent",
    processExploreAgent: "Explore Agent",
    processSearchAgent: "Search Agent",
    processSummaryAgent: "Summary Agent",
    processVisionAgent: "Vision Agent",
    processBBoxDebug: "BBox Debug",
    processVisionValidation: "Vision Validation",
    processStagePlanChunk: "Plan Chunk",
    processStageLocalCheck: "Local Check",
    processStageGlobalCheck: "Global Check",
    processStageFinalizeErrorList: "Finalize ErrorList",
    processStageSummarizeFindings: "Summarize Findings",
    processStageVisualCheck: "Visual Check",
    processQuery: "Query",
    processPipeline: "Pipeline",
    exportingAnnotatedPdf: "导出中...",
    downloadPreparingTitle: "正在导出 PDF 批注",
    downloadPreparingBody: "正在生成并下载带批注的 PDF，大文件可能需要几十秒。",
    downloadReadyTitle: "下载已开始",
    downloadReadyBody: "浏览器已开始下载批注 PDF；如果没有出现下载，请检查浏览器的下载权限提示。",
    downloadFailedTitle: "导出 PDF 批注失败",
    closeDialog: "关闭",
  },
  en: {
    uploadDescription: "Configure required endpoints, upload a paper, and keep tasks across refresh.",
    settingsTitle: "System Settings",
    savingSettings: "Saving...",
    saveSettings: "Save Settings",
    launchTitle: "Upload and Review",
    reportLanguageLabel: "Report Language",
    langChinese: "Chinese",
    langEnglish: "English",
    dropzoneTitle: "Click or drag a PDF here",
    dropzoneDescription: "Only one task can run at a time.",
    missingConfigTitle: "Configuration incomplete",
    singleTaskLimitTitle: "An active task already exists",
    singleTaskLimitBody: "A task is queued or running. Open it first or wait until it finishes.",
    uploading: "Uploading and starting...",
    startReview: "Start Review",
    resumeLastTask: "Resume Last Task",
    activeTasks: "Active Tasks",
    completedTasks: "Completed Tasks",
    loadingTasks: "Loading tasks",
    noActiveTasks: "No active tasks.",
    noCompletedTasks: "No completed tasks.",
    openTask: "Open",
    deleteTask: "Delete",
    deletingTask: "Deleting...",
    terminateTask: "Terminate",
    terminatingTask: "Terminating...",
    deleteTaskConfirm: "Delete this task and all related files?",
    terminateTaskConfirm: "Terminate the current review task? Completed intermediate results will be preserved when possible.",
    deleteTaskFailedTitle: "Failed to delete task",
    terminateTaskFailedTitle: "Failed to terminate task",
    backToUpload: "Back",
    refreshTask: "Refresh",
    pdfTitle: "PDF Reference",
    locationLegend: "Location",
    evidenceLegend: "Evidence",
    page: "Page",
    zoomOut: "Zoom Out",
    zoomIn: "Zoom In",
    loadingPdf: "Loading PDF",
    pdfWaiting: "The PDF is not ready yet.",
    issuesTitle: "Issues",
    confirmedIssues: "confirmed",
    rejectedIssues: "rejected",
    allIssues: "All",
    searchIssues: "Search issues",
    taskWaiting: "No task is ready to display.",
    issuesStreaming: "Issues are still streaming in.",
    noIssuesFound: "No issues found.",
    chunkLabel: "Chunk",
    emptyValue: "Empty",
    processTitle: "Process",
    waiting: "Waiting",
    noLogsYet: "No process logs yet.",
    modeFast: "Fast",
    modeFastCopy: "Basic explore only.",
    modeStandard: "Standard",
    modeStandardCopy: "Runs vision after each chunk.",
    modeDeep: "Deep",
    modeDeepCopy: "Adds search on top of standard.",
    statusPending: "Queued",
    statusRunning: "Running",
    statusCancelling: "Cancelling",
    statusCancelled: "Cancelled",
    statusCompleted: "Completed",
    statusFailed: "Failed",
    configSavedTitle: "Settings saved",
    configSavedBody: "Runtime configuration has been refreshed.",
    configSaveFailedTitle: "Failed to save settings",
    uploadFailedTitle: "Failed to create task",
    uploadConflictTitle: "Active task exists",
    uploadStartedTitle: "Task created",
    uploadStartedBody: "Opening the review view.",
    missingMineruKey: "MinerU API Key",
    missingQwenKey: "Qwen API Key",
    missingSerperKey: "Serper API Key",
    bboxReady: "bbox ready",
    bboxMissing: "bbox missing",
    decisionKeep: "Confirmed",
    decisionReview: "Needs review",
    decisionUnchecked: "Unchecked",
    decisionDrop: "Dropped",
    issueCount: "issues",
    descriptionLegend: "Description",
    reasoningLegend: "Reasoning",
    chatTitle: "Chat Window",
    chatReserved: "Reserved. Sending instructions is not implemented yet.",
    chatPlaceholder: "Instruction input will be enabled here later",
    chatSend: "Send",
    workflowPreprocessing: "Preprocessing",
    workflowPreprocessingDesc: "PDF parsing and chunk splitting",
    workflowFinding: "Finding",
    workflowFindingDesc: "Finding and confirming issues",
    processDone: "done!",
    processRunning: "running...",
    processPending: "pending...",
    processFailed: "failed",
    processPdfParsing: "PDF Parsing",
    processChunkDividing: "Chunk Dividing",
    processChunk: "Chunk",
    processChunkReading: "Chunk Reading",
    processChunkReview: "Chunk Review",
    processPdfParser: "PDF Parser",
    processPlanAgent: "Plan Agent",
    processExploreAgent: "Explore Agent",
    processSearchAgent: "Search Agent",
    processSummaryAgent: "Summary Agent",
    processVisionAgent: "Vision Agent",
    processBBoxDebug: "BBox Debug",
    processVisionValidation: "Vision Validation",
    processStagePlanChunk: "Plan Chunk",
    processStageLocalCheck: "Local Check",
    processStageGlobalCheck: "Global Check",
    processStageFinalizeErrorList: "Finalize ErrorList",
    processStageSummarizeFindings: "Summarize Findings",
    processStageVisualCheck: "Visual Check",
    processQuery: "Query",
    processPipeline: "Pipeline",
    exportingAnnotatedPdf: "Exporting...",
    downloadPreparingTitle: "Preparing annotated PDF",
    downloadPreparingBody: "The annotated PDF is being generated and downloaded. Large files can take a while.",
    downloadReadyTitle: "Download started",
    downloadReadyBody: "The annotated PDF download has started. If nothing appears, check your browser download permissions.",
    downloadFailedTitle: "Failed to export annotated PDF",
    closeDialog: "Close",
  },
};

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function safeLower(value) {
  return String(value || "").trim().toLowerCase();
}

const FAILURE_MARKER_PATTERN = /(?:^|[^a-z])(error|errors|failed|failure|exception|exceptions)(?:$|[^a-z])/;

function hasFailureMarker(...values) {
  return values.some((value) => FAILURE_MARKER_PATTERN.test(safeLower(value)));
}

function deepCopy(value) {
  return JSON.parse(JSON.stringify(value));
}

function numericValue(...values) {
  for (const value of values) {
    if (value === null || value === undefined || value === "") continue;
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function getHashTaskId() {
  const hash = window.location.hash || "";
  const match = hash.match(/^#\/task\/([^/?]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

function setHashTaskId(taskId) {
  const target = taskId ? `#/task/${encodeURIComponent(taskId)}` : "";
  if ((window.location.hash || "") !== target) {
    window.location.hash = target;
  }
}

createApp({
  setup() {
    const uiLang = ref(localStorage.getItem(STORAGE_KEYS.uiLang) || "zh");
    const reportLanguage = ref(localStorage.getItem(STORAGE_KEYS.reportLang) || "zh");
    const currentView = ref("upload");
    const mode = ref("standard");
    const selectedFile = ref(null);
    const isDragover = ref(false);
    const isUploading = ref(false);
    const isSavingConfig = ref(false);
    const deletingTaskId = ref("");
    const cancellingTaskId = ref("");
    const resumingTaskId = ref("");
    const tasks = ref([]);
    const tasksLoading = ref(false);
    const currentTask = ref(null);
    const lastViewedTaskId = ref(localStorage.getItem(STORAGE_KEYS.lastTaskId) || "");
    const activeTaskPage = ref(1);
    const completedTaskPage = ref(1);
    const fileInputRef = ref(null);
    const workspaceRef = ref(null);
    const pdfScrollRef = ref(null);
    const processScrollRef = ref(null);
    const pdfTaskId = ref("");
    const pdfLoading = ref(false);
    const pdfError = ref("");
    const pageCount = ref(0);
    const currentPageNum = ref(1);
    const zoom = ref(0.78);
    const pdfPages = ref([]);
    const selectedType = ref("all");
    const issueSearch = ref("");
    const processInstructionDraft = ref("");
    const selectedIssueId = ref("");
    const pdfFocusKind = ref("location");
    const pdfFocusIndex = ref(0);
    const showSettingsPanel = ref(false);
    const showProcessPanel = ref(true);
    const isDownloadingAnnotatedPdf = ref(false);
    const streamSource = ref(null);
    const streamTaskId = ref("");
    const taskPollTimer = ref(null);
    const taskListTimer = ref(null);
    const downloadDialogTimer = ref(null);
    const scrollSyncLock = ref(false);
    const pageChangeSource = ref("program");
    const isStackedLayout = ref(window.innerWidth <= 980);
    const panelSizes = reactive({ left: 42, middle: 28, right: 30 });
    const resizeState = reactive({ handle: "", startX: 0, left: 42, middle: 28, right: 30 });
    const expandedSections = reactive({});
    const pageShellRefs = new Map();
    const configForm = reactive({
      mineru_api_url: "https://mineru.net/api/v4",
      mineru_api_key: "",
      review_api_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
      review_api_key: "",
      review_model: "",
      recheck_llm_api_url: "",
      recheck_llm_api_key: "",
      recheck_llm_model: "",
      recheck_vlm_api_url: "",
      recheck_vlm_api_key: "",
      recheck_vlm_model: "",
      llm_request_min_interval_seconds: "0",
      search_engine: "duckduckgo",
      serper_api_key: "",
    });
    const uploadMessage = reactive({ type: "", title: "", text: "" });
    const configMessage = reactive({ type: "", title: "", text: "" });
    const downloadDialog = reactive({ visible: false, type: "info", title: "", text: "" });

    const t = (key) => (MESSAGES[uiLang.value] || MESSAGES.zh)[key] || key;

    const modeCards = computed(() => [
      { key: "fast", label: t("modeFast"), copy: localeText("基础 explore，速度最快。", "Basic explore only.") },
      {
        key: "standard",
        label: t("modeStandard"),
        copy: localeText("在 fast 模式的基础上增加 Recheck 功能。", "Add a Recheck function to the fast mode."),
      },
      { key: "deep", label: t("modeDeep"), copy: localeText("在 Standard 基础上增加 Web Search 功能。", "Adds web search on top of standard.") },
    ]);

    const modeFeatures = computed(() => MODE_CONFIG[mode.value] || MODE_CONFIG.standard);
    const activeTasks = computed(() => tasks.value.filter((item) => ["pending", "running", "cancelling"].includes(item.status)));
    const completedTasks = computed(() => tasks.value.filter((item) => ["completed", "failed", "cancelled"].includes(item.status)));
    const activeTaskPageCount = computed(() => Math.max(1, Math.ceil(activeTasks.value.length / TASKS_PER_PAGE)));
    const completedTaskPageCount = computed(() => Math.max(1, Math.ceil(completedTasks.value.length / TASKS_PER_PAGE)));
    const pagedActiveTasks = computed(() => paginateTasks(activeTasks.value, activeTaskPage.value));
    const pagedCompletedTasks = computed(() => paginateTasks(completedTasks.value, completedTaskPage.value));
    const hasActiveTask = computed(() => activeTasks.value.length > 0);
    const canSendProcessInstruction = computed(() => Boolean(processInstructionDraft.value.trim()));
    const settingsPanelStatusLabel = computed(() =>
      missingRequirements.value.length
        ? localeText("待配置", "Setup needed")
        : localeText("已配置", "Configured")
    );
    const settingsSummary = computed(() =>
      missingRequirements.value.length
        ? missingRequirements.value.join(" / ")
        : settingsPanelStatusLabel.value
    );

    const missingRequirements = computed(() => {
      const missing = [];
      if (!configValue("mineru_api_key")) {
        missing.push(t("missingMineruKey"));
      }
      if (!configValue("review_api_key")) {
        missing.push(localeText("\u5ba1\u9605\u6a21\u578b API Key", "Review Model API Key"));
      }
      if (modeFeatures.value.search && configForm.search_engine === "serper" && !configValue("serper_api_key")) {
        missing.push(t("missingSerperKey"));
      }
      return missing;
    });

    const cannotStartReview = computed(() =>
      !selectedFile.value ||
      isUploading.value ||
      isSavingConfig.value ||
      hasActiveTask.value ||
      missingRequirements.value.length > 0
    );

    const visibleIssues = computed(() => {
      return asArray(currentTask.value?.result?.issues)
        .filter((issue) => issueDecision(issue) !== "drop")
        .slice()
        .sort((left, right) => {
          const leftRank = SEVERITY_RANK[severityKey(left)] ?? 9;
          const rightRank = SEVERITY_RANK[severityKey(right)] ?? 9;
          if (leftRank !== rightRank) return leftRank - rightRank;
          return (left.chunk_id ?? 0) - (right.chunk_id ?? 0);
        });
    });

    const rejectedIssueCount = computed(() =>
      asArray(currentTask.value?.result?.issues).filter((issue) => issueDecision(issue) === "drop").length
    );

    const issueTypes = computed(() => {
      const unique = new Set();
      visibleIssues.value.forEach((issue) => {
        const type = issue.type || issue.type_key;
        if (type) unique.add(type);
      });
      return Array.from(unique);
    });

    const filteredIssues = computed(() => {
      const query = safeLower(issueSearch.value);
      return visibleIssues.value.filter((issue) => {
        const type = issue.type || issue.type_key;
        if (selectedType.value !== "all" && type !== selectedType.value) return false;
        if (!query) return true;
        const haystack = [
          issue.description,
          issueLocationText(issue),
          issueEvidenceText(issue),
          fieldText(issue.location_original),
          fieldText(issue.evidence_original),
          issueReasoningText(issue),
          issue.type,
          issue.type_key,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return haystack.includes(query);
      });
    });

    const selectedIssue = computed(() =>
      filteredIssues.value.find((issue) => issue.client_id === selectedIssueId.value) ||
      visibleIssues.value.find((issue) => issue.client_id === selectedIssueId.value) ||
      null
    );

    const latestLogId = computed(() => processLogEntries().slice(-1)[0]?.client_id || "");
    const progressPercent = computed(() => clamp(Number(currentTask.value?.progress?.percent || 0), 0, 100));
    const progressPhaseLabel = computed(() => humanizeStage(currentTask.value?.progress?.phase || "") || t("waiting"));
    const isTaskActive = computed(() => Boolean(currentTask.value && ["pending", "running", "cancelling"].includes(currentTask.value.status)));
    const canCancelCurrentTask = computed(() => Boolean(currentTask.value && ["pending", "running", "cancelling"].includes(currentTask.value.status)));
    const canExportReport = computed(() => currentTask.value?.status === "completed");
    const pdfReady = computed(() => Boolean(pdfPages.value.length));
    const workflowStages = computed(() => buildWorkflowStages());
    const processItems = computed(() => buildProcessTreeItems());

    function clearAlert(target) {
      target.type = "";
      target.title = "";
      target.text = "";
    }

    function configValue(field) {
      return String(configForm[field] || "").trim();
    }

    function openSettingsPanel() {
      showSettingsPanel.value = true;
    }

    function closeSettingsPanel() {
      showSettingsPanel.value = false;
    }

    function setAlert(target, type, title, text) {
      target.type = type;
      target.title = title;
      target.text = text;
    }

    function clearDownloadDialogTimer() {
      if (downloadDialogTimer.value) {
        window.clearTimeout(downloadDialogTimer.value);
        downloadDialogTimer.value = null;
      }
    }

    function showDownloadDialog(type, title, text) {
      clearDownloadDialogTimer();
      downloadDialog.visible = true;
      downloadDialog.type = type;
      downloadDialog.title = title;
      downloadDialog.text = text;
    }

    function closeDownloadDialog() {
      if (isDownloadingAnnotatedPdf.value) return;
      clearDownloadDialogTimer();
      downloadDialog.visible = false;
      downloadDialog.type = "info";
      downloadDialog.title = "";
      downloadDialog.text = "";
    }

    function alertClass(type) {
      return type ? `inline-alert--${type}` : "";
    }

    function parseDownloadFilename(contentDisposition, fallbackName) {
      const header = String(contentDisposition || "");
      const utfMatch = header.match(/filename\*=UTF-8''([^;]+)/i);
      if (utfMatch?.[1]) {
        try {
          return decodeURIComponent(utfMatch[1]);
        } catch (error) {
          return utfMatch[1];
        }
      }

      const plainMatch = header.match(/filename="?([^"]+)"?/i);
      if (plainMatch?.[1]) return plainMatch[1];
      return fallbackName;
    }

    function triggerBrowserDownload(blob, filename) {
      const objectUrl = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = filename;
      link.rel = "noopener";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => window.URL.revokeObjectURL(objectUrl), 30000);
    }

    async function readErrorMessage(response) {
      const contentType = safeLower(response.headers.get("content-type") || "");
      if (contentType.includes("application/json")) {
        const payload = await response.json().catch(() => ({}));
        return payload.error || payload.message || `HTTP ${response.status}`;
      }
      const text = await response.text().catch(() => "");
      return text.trim() || `HTTP ${response.status}`;
    }

    function truncateText(value, limit = 90) {
      const text = String(value || "").replace(/\s+/g, " ").trim();
      if (!text) return "";
      return text.length > limit ? `${text.slice(0, limit)}...` : text;
    }

    function stripWrappedQuotes(value) {
      const text = String(value || "").trim();
      if (text.length >= 2 && (text.startsWith("'") || text.startsWith('"')) && text[0] === text[text.length - 1]) {
        return text.slice(1, -1).trim();
      }
      return text;
    }

    function parseBracketedListText(value) {
      const text = String(value || "").trim();
      if (!text.startsWith("[") || !text.endsWith("]")) return null;
      const inner = text.slice(1, -1).trim();
      if (!inner) return [];
      if (!/['"]/.test(inner) && !/(?:^|,\s*)(?:\d+\.\s|[-*•]\s)/.test(inner)) return null;
      try {
        const parsed = JSON.parse(text);
        if (Array.isArray(parsed)) return parsed;
      } catch (error) {
        // Fall through to a lightweight splitter for Python-style list strings.
      }
      const lines = inner
        .replace(/(['"])\s*,\s*\1(?=(?:\d+\.\s|[-*•]\s))/g, "\n")
        .split(/\r?\n/)
        .map((line) => stripWrappedQuotes(line))
        .filter(Boolean);
      return lines.length > 1 ? lines : null;
    }

    function parseEnumeratedListText(value) {
      const text = String(value || "").trim();
      const inner = text.startsWith("[") && text.endsWith("]") ? text.slice(1, -1).trim() : text;
      if (!inner || !/\d+\.\s/.test(inner)) return null;

      const items = [];
      const pattern = /(?:^|,\s*|\n\s*)(?:['"])?(\d+\.\s[\s\S]*?)(?=(?:,\s*|\n\s*)(?:['"])?\d+\.\s|$)/g;
      let match = pattern.exec(inner);
      while (match) {
        const candidate = stripWrappedQuotes(String(match[1] || "").trim().replace(/[,\s]+$/, ""));
        if (candidate) items.push(candidate);
        match = pattern.exec(inner);
      }
      return items.length > 1 ? items : null;
    }

    function fieldLines(value) {
      if (Array.isArray(value)) {
        return value.flatMap((item) => fieldLines(item));
      }
      if (value === null || value === undefined) return [];
      const text = String(value || "").trim();
      if (!text) return [];
      const parsedEnumeratedList = parseEnumeratedListText(text);
      if (Array.isArray(parsedEnumeratedList)) {
        return parsedEnumeratedList.flatMap((item) => fieldLines(item));
      }
      const parsedList = parseBracketedListText(text);
      if (Array.isArray(parsedList)) {
        return parsedList.flatMap((item) => fieldLines(item));
      }
      return [text];
    }

    function fieldText(value, separator = "\n") {
      return fieldLines(value).join(separator);
    }

    function issueLocationText(issue) {
      const originalText = fieldText(issue?.location_original);
      if (originalText) return originalText;
      const displayText = fieldText(issue?.location_display);
      if (displayText) return displayText;
      return fieldText(issue?.location);
    }

    function issueEvidenceText(issue) {
      const originalText = fieldText(issue?.evidence_original);
      if (originalText) return originalText;
      const displayText = fieldText(issue?.evidence_display);
      if (displayText) return displayText;
      return fieldText(issue?.evidence);
    }

    function issueReasoningText(issue) {
      return fieldText(issue?.reasoning, "\n");
    }

    function localeText(zhText, enText) {
      return uiLang.value === "zh" ? zhText : enText;
    }

    function parseCountFromText(text, patterns = []) {
      const source = String(text || "");
      for (const pattern of patterns) {
        const match = source.match(pattern);
        if (!match) continue;
        const count = Number(match[1]);
        if (Number.isFinite(count)) return count;
      }
      return null;
    }

    function paginateTasks(list, page) {
      const safePage = Math.max(1, Number(page || 1));
      const start = (safePage - 1) * TASKS_PER_PAGE;
      return list.slice(start, start + TASKS_PER_PAGE);
    }

    function changeTaskPage(type, delta) {
      if (type === "active") {
        activeTaskPage.value = clamp(activeTaskPage.value + delta, 1, activeTaskPageCount.value);
        return;
      }
      completedTaskPage.value = clamp(completedTaskPage.value + delta, 1, completedTaskPageCount.value);
    }

    function severityKey(issue) {
      const key = safeLower(issue?.severity_key);
      if (key) return key;
      const raw = safeLower(issue?.severity);
      if (raw.includes("high") || raw.includes("高")) return "high";
      if (raw.includes("low") || raw.includes("低")) return "low";
      return "medium";
    }

    function severityLabel(issue) {
      const key = severityKey(issue);
      if (uiLang.value === "zh") return key === "high" ? "高" : key === "low" ? "低" : "中";
      return key.charAt(0).toUpperCase() + key.slice(1);
    }

    function severityClass(issue) {
      return severityKey(issue);
    }

    function issueDecision(issue) {
      const explicit = safeLower(issue?.recheck_validation?.decision) || safeLower(issue?.vision_validation?.decision);
      if (explicit) return explicit;
      if (currentTask.value?.status === "completed") return "skip";
      return "unchecked";
    }

    function decisionLabel(issue) {
      const decision = issueDecision(issue);
      if (decision === "keep") return t("decisionKeep");
      if (decision === "review") return t("decisionReview");
      if (decision === "drop") return t("decisionDrop");
      if (decision === "skip") return localeText("已跳过", "Skipped");
      return t("decisionUnchecked");
    }

    function decisionClass(issue) {
      return issueDecision(issue);
    }

    function taskStatusLabel(status) {
      const normalized = safeLower(status);
      if (normalized === "completed") return t("statusCompleted");
      if (normalized === "failed") return t("statusFailed");
      if (normalized === "cancelled") return t("statusCancelled");
      if (normalized === "cancelling") return t("statusCancelling");
      if (normalized === "running") return t("statusRunning");
      return t("statusPending");
    }

    function issueCountLabel(task) {
      const count = Number(task?.confirmed_issue_count ?? task?.issue_count ?? 0);
      return `${count} ${t("issueCount")}`;
    }

    function boxSignature(match) {
      if (!match || !Array.isArray(match.bbox)) return "";
      return `${match.page || 0}:${match.bbox.slice(0, 4).join(",")}`;
    }

    function sortMatchesByScore(matches) {
      return asArray(matches)
        .filter((match) => match && Array.isArray(match.bbox))
        .slice()
        .sort((left, right) => Number(right?.score || 0) - Number(left?.score || 0));
    }

    function preferredLocationMatch(issue) {
      return sortMatchesByScore(issue?.location_bbox_matches)[0] || issue?.best_bbox_match || sortMatchesByScore(issue?.evidence_bbox_matches)[0] || null;
    }

    function preferredTargetMatch(issue) {
      return preferredLocationMatch(issue);
    }

    function matchLabel(kind, match, index) {
      const baseLabel = kind === "location" ? t("locationLegend") : t("evidenceLegend");
      const anchorId = String(match?.anchor_id || "").trim();
      if (anchorId) return `${baseLabel} ${anchorId}`;
      return index === 0 ? baseLabel : `${baseLabel} ${index + 1}`;
    }

    function issueFocusTargets(issue, kind = "") {
      if (!issue) return [];
      const targets = [];
      const seen = new Set();
      const kindFilter = kind === "evidence" ? "evidence" : kind === "location" ? "location" : "";

      const pushTarget = (match, targetKind, index, suffix) => {
        if (!match || !Array.isArray(match.bbox)) return;
        if (kindFilter && targetKind !== kindFilter) return;
        const signature = boxSignature(match);
        if (!signature) return;
        const dedupeKey = `${targetKind}:${signature}:${String(match?.anchor_id || "").trim()}`;
        const targetId = `${targetKind}:${suffix}:${signature}:${String(match?.anchor_id || "").trim()}`;
        if (seen.has(dedupeKey)) return;
        seen.add(dedupeKey);
        targets.push({
          id: targetId,
          kind: targetKind,
          index,
          label: matchLabel(targetKind, match, index),
          match,
        });
      };

      const locationMatches = sortMatchesByScore(issue?.location_bbox_matches);
      if (locationMatches.length) {
        locationMatches.forEach((match, index) => pushTarget(match, "location", index, `loc-${index}`));
      } else if (issue?.best_bbox_match && safeLower(issue?.best_bbox_match_kind) !== "evidence") {
        pushTarget(issue.best_bbox_match, "location", 0, "best");
      }

      sortMatchesByScore(issue?.evidence_bbox_matches).forEach((match, index) =>
        pushTarget(match, "evidence", index, `evi-${index}`)
      );

      if (!targets.length && issue?.best_bbox_match) {
        pushTarget(issue.best_bbox_match, "location", 0, "fallback");
      }

      return targets;
    }

    function preferredPdfFocusKind(issue, requestedKind = pdfFocusKind.value) {
      const wantedKind = requestedKind === "evidence" ? "evidence" : "location";
      const hasLocation = issueFocusTargets(issue, "location").length > 0;
      const hasEvidence = issueFocusTargets(issue, "evidence").length > 0;
      if (wantedKind === "location" && hasLocation) return "location";
      if (wantedKind === "evidence" && hasEvidence) return "evidence";
      if (hasLocation) return "location";
      if (hasEvidence) return "evidence";
      return wantedKind;
    }

    function focusIndexForIssue(issue, kind = pdfFocusKind.value, index = pdfFocusIndex.value) {
      const targets = issueFocusTargets(issue, kind);
      if (!targets.length) return 0;
      return clamp(index, 0, targets.length - 1);
    }

    function syncPdfFocusState(issue, reset = false) {
      const nextKind = preferredPdfFocusKind(issue, reset ? "location" : pdfFocusKind.value);
      const nextIndex = reset ? 0 : focusIndexForIssue(issue, nextKind, pdfFocusIndex.value);
      pdfFocusKind.value = nextKind;
      pdfFocusIndex.value = nextIndex;
      return {
        kind: nextKind,
        index: nextIndex,
        targets: issueFocusTargets(issue, nextKind),
      };
    }

    function currentFocusTarget(issue) {
      const kind = preferredPdfFocusKind(issue, pdfFocusKind.value);
      const targets = issueFocusTargets(issue, kind);
      return targets[focusIndexForIssue(issue, kind, pdfFocusIndex.value)] || null;
    }

    function focusTargetCount(kind, issue = selectedIssue.value) {
      return issueFocusTargets(issue, kind).length;
    }

    function focusTargetPosition(issue = selectedIssue.value) {
      const kind = preferredPdfFocusKind(issue, pdfFocusKind.value);
      const targets = issueFocusTargets(issue, kind);
      if (!targets.length) return "";
      const index = focusIndexForIssue(issue, kind, pdfFocusIndex.value);
      return `${index + 1} / ${targets.length}`;
    }

    function focusTargetPositionByKind(kind, issue = selectedIssue.value) {
      const normalizedKind = kind === "evidence" ? "evidence" : "location";
      const targets = issueFocusTargets(issue, normalizedKind);
      if (!targets.length) return "";
      const index = pdfFocusKind.value === normalizedKind ? focusIndexForIssue(issue, normalizedKind, pdfFocusIndex.value) : 0;
      return `${index + 1} / ${targets.length}`;
    }

    function setPdfFocusKind(kind) {
      if (!selectedIssue.value || !focusTargetCount(kind, selectedIssue.value)) return;
      pdfFocusKind.value = kind === "evidence" ? "evidence" : "location";
      pdfFocusIndex.value = 0;
      nextTick().then(() => focusIssueBBox(selectedIssue.value));
    }

    function cyclePdfFocus(delta) {
      if (!selectedIssue.value) return;
      const { targets } = syncPdfFocusState(selectedIssue.value, false);
      if (!targets.length) return;
      pdfFocusIndex.value = (pdfFocusIndex.value + delta + targets.length) % targets.length;
      nextTick().then(() => focusIssueBBox(selectedIssue.value));
    }

    function stepPdfFocus(kind, delta) {
      if (!selectedIssue.value) return;
      const normalizedKind = kind === "evidence" ? "evidence" : "location";
      const targets = issueFocusTargets(selectedIssue.value, normalizedKind);
      if (!targets.length) return;
      if (pdfFocusKind.value !== normalizedKind) {
        pdfFocusKind.value = normalizedKind;
        pdfFocusIndex.value = delta < 0 ? targets.length - 1 : 0;
      } else {
        const currentIndex = focusIndexForIssue(selectedIssue.value, normalizedKind, pdfFocusIndex.value);
        pdfFocusIndex.value = (currentIndex + delta + targets.length) % targets.length;
      }
      nextTick().then(() => focusIssueBBox(selectedIssue.value));
    }

    function issuePage(issue) {
      return preferredTargetMatch(issue)?.page || "";
    }

    function bboxLabel(issue) {
      return preferredTargetMatch(issue) ? t("bboxReady") : t("bboxMissing");
    }

    function humanizeStage(stage) {
      const raw = String(stage || "").trim();
      if (!raw) return "";
      return raw
        .replace(/^progress_/i, "")
        .replace(/[_-]+/g, " ")
        .replace(/\s+/g, " ")
        .trim()
        .replace(/\b\w/g, (letter) => letter.toUpperCase());
    }

    function formatAgent(agent) {
      return String(agent || "System").replace(/([a-z])([A-Z])/g, "$1 $2");
    }

    function formatDateTime(value) {
      if (!value) return "";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return value;
      return date.toLocaleString(uiLang.value === "zh" ? "zh-CN" : "en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    }

    function formatTime(value) {
      if (!value) return "";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return value;
      return date.toLocaleTimeString(uiLang.value === "zh" ? "zh-CN" : "en-US", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    }

    function normalizeLog(log, index) {
      return {
        ts: log?.ts || log?.timestamp || new Date().toISOString(),
        agent: log?.agent || "System",
        stage: log?.stage || "",
        message: log?.message || "",
        data: log?.data || {},
        client_id: log?.client_id || `${log?.ts || log?.timestamp || Date.now()}-${index}-${log?.stage || "log"}`,
        _index: index,
      };
    }

    function compareLogs(left, right) {
      const leftStep = numericValue(left?.data?.step);
      const rightStep = numericValue(right?.data?.step);
      if (leftStep !== null || rightStep !== null) {
        if (leftStep === null) return 1;
        if (rightStep === null) return -1;
        if (leftStep !== rightStep) return leftStep - rightStep;
      }

      const leftTime = Date.parse(left?.ts || "");
      const rightTime = Date.parse(right?.ts || "");
      const leftHasTime = Number.isFinite(leftTime);
      const rightHasTime = Number.isFinite(rightTime);
      if (leftHasTime || rightHasTime) {
        if (!leftHasTime) return 1;
        if (!rightHasTime) return -1;
        if (leftTime !== rightTime) return leftTime - rightTime;
      }

      const leftIndex = numericValue(left?._index) ?? 0;
      const rightIndex = numericValue(right?._index) ?? 0;
      if (leftIndex !== rightIndex) return leftIndex - rightIndex;
      return String(left?.client_id || "").localeCompare(String(right?.client_id || ""));
    }

    function sortLogs(logs) {
      return logs.slice().sort(compareLogs);
    }

    function hasChunkId(log) {
      const chunkId = log?.data?.chunk_id;
      return chunkId !== null && chunkId !== undefined && chunkId !== "";
    }

    const RESUME_BOUNDARY_STAGES = new Set(["task_resume_requested", "task_resumed"]);

    function latestResumeBoundaryTime(logs = asArray(currentTask.value?.logs)) {
      let latest = Number.NEGATIVE_INFINITY;
      logs.forEach((log) => {
        if (!RESUME_BOUNDARY_STAGES.has(safeLower(log?.stage || ""))) return;
        const timestamp = Date.parse(log?.ts || "");
        if (Number.isFinite(timestamp) && timestamp > latest) {
          latest = timestamp;
        }
      });
      return Number.isFinite(latest) ? latest : null;
    }

    function isSupersededProcessFailure(log, resumeBoundaryTime) {
      if (!Number.isFinite(resumeBoundaryTime)) return false;
      const stageText = safeLower(`${log?.stage || ""} ${log?.message || ""}`);
      if (!hasFailureMarker(stageText) && !/cancelled|canceled|interrupted|cancelling/.test(stageText)) {
        return false;
      }
      const timestamp = Date.parse(log?.ts || "");
      return Number.isFinite(timestamp) && timestamp < resumeBoundaryTime;
    }

    function logPhaseLabel(log) {
      return String(log?.data?.phase || humanizeStage(log?.stage || "") || formatAgent(log?.agent || "System")).trim();
    }

    function processLogEntries() {
      const logs = asArray(currentTask.value?.logs);
      const resumeBoundaryTime = latestResumeBoundaryTime(logs);
      return logs.filter((log) => {
        const stage = safeLower(log?.stage || "");
        const stageText = safeLower(`${stage} ${log?.message || ""}`);
        if (isSupersededProcessFailure(log, resumeBoundaryTime)) return false;
        if (hasFailureMarker(stageText)) return true;
        if (stage.startsWith("progress_")) {
          const phase = safeLower(log?.data?.phase || "");
          if (/html|report|language|switch|翻译/.test(phase)) return false;
          if (hasChunkId(log)) return true;
          return /pdf|parse|chunk|bbox|vision|finding|preprocessing/.test(phase || stageText);
        }
        if (log?.agent === "PDFParser") {
          return ["output", "error", "download_bundle"].includes(stage);
        }
        if (log?.agent === "Main") {
          return ["parse_start", "parse_complete", "chunk_start", "chunk_complete", "chunk_error", "chunk_review_audit", "complete"].includes(stage);
        }
        if (log?.agent === "PlanAgent") {
          return ["output", "error"].includes(stage);
        }
        if (log?.agent === "ExploreAgent") {
          return [
            "stage1_output",
            "stage2_output",
            "stage3_output",
            "stage_local_output",
            "stage_global_output",
            "stage_final_output",
            "error",
          ].includes(stage);
        }
        if (log?.agent === "SearchAgent") {
          return [
            "batch_input",
            "batch_output",
            "search_request",
            "search_output",
            "organize_output",
            "search_error",
            "error",
          ].includes(stage);
        }
        if (log?.agent === "VisionAgent") {
          return ["output", "error"].includes(stage);
        }
        if (log?.agent === "ConfigValidator") {
          return /^config_validation/.test(stage);
        }
        return false;
      });
    }

    function processChildLabel(log) {
      return formatAgent(log?.agent || "System");
    }

    const CONFIG_VALIDATION_DONE_STAGES = new Set([
      "config_validation_cache_hit",
      "config_validation_success",
      "config_validation_done",
    ]);

    function isConfigValidationStage(stage) {
      return /^config_validation/.test(String(stage || "").trim().toLowerCase());
    }

    function isConfigValidationDoneStage(stage) {
      return CONFIG_VALIDATION_DONE_STAGES.has(String(stage || "").trim().toLowerCase());
    }

    function formatConfigValidationFailure(message) {
      const detail = String(message || "")
        .replace(/^runtime configuration validation failed:\s*/i, "")
        .trim();
      if (!detail) {
        return localeText(
          "配置校验失败：请打开 System Settings 检查 URL、Key 和 Model 后重试。",
          "Config validation failed: check System Settings and retry."
        );
      }
      if (/configuration is incomplete/i.test(detail)) {
        return localeText(
          "配置不完整：URL、Key、Model 必须一起填写或一起留空。请在 System Settings 补全后重试。",
          "Incomplete configuration: URL, API key, and model must be filled together or left blank. Fix System Settings and retry."
        );
      }
      if (/api key is required/i.test(detail) || /url is required/i.test(detail) || /model is required/i.test(detail)) {
        return localeText(
          `缺少必要配置：${truncateText(detail, 56)}。请在 System Settings 补全后重试。`,
          `Missing required configuration: ${truncateText(detail, 56)}. Complete System Settings and retry.`
        );
      }
      if (/\b401\b|unauthorized|authentication/i.test(detail)) {
        return localeText(
          "鉴权失败：请检查 API Key 和 URL 是否匹配当前服务商，然后重试。",
          "Authentication failed: check whether the API key matches the configured URL, then retry."
        );
      }
      if (/\b404\b|not found/i.test(detail)) {
        return localeText(
          "接口地址不正确：请填写服务商官网提供的 base URL，然后重试。",
          "Endpoint not found: use the provider's official base URL, then retry."
        );
      }
      return localeText(
        `配置校验失败：${truncateText(detail, 72)}。请在 System Settings 修正后重试。`,
        `Config validation failed: ${truncateText(detail, 72)}. Fix System Settings and retry.`
      );
    }

    function processEntryText(log) {
      const stage = safeLower(log?.stage || "");
      const phase = safeLower(log?.data?.phase || "");
      const rawSummary = String(
        log?.data?.summary_text ||
        log?.data?.analysis ||
        log?.data?.summary ||
        log?.message ||
        ""
      ).trim();
      const queryCount = numericValue(
        asArray(log?.data?.query_list).length || null,
        parseCountFromText(rawSummary, [/(\d+)\s+queries?/i, /(\d+)\s*条\s*queries?/i])
      );
      const issueCount = numericValue(
        log?.data?.total_issues,
        log?.data?.issue_count,
        log?.data?.confirmed_issue_count,
        parseCountFromText(rawSummary, [/output\s+(\d+)\s+final issues?/i, /(\d+)\s+issues?/i, /(\d+)\s*个问题/i])
      );
      const chunkCount = numericValue(
        log?.data?.chunk_count,
        parseCountFromText(rawSummary, [/(\d+)\s*(?:个\s*)?chunks?/i])
      );
      const imageCount = numericValue(
        log?.data?.image_count,
        log?.data?.chunk_image_input_count,
        parseCountFromText(rawSummary, [/images?=(\d+)/i, /(\d+)\s+images?/i, /(\d+)\s*张图/i])
      );
      const searchRequestCount = numericValue(
        log?.data?.request_count,
        asArray(log?.data?.search_requests).length || null,
        parseCountFromText(rawSummary, [/running\s+(\d+)\s+search requests?/i, /(\d+)\s+search requests?/i])
      );
      const searchResultCount = numericValue(
        log?.data?.results_count,
        asArray(log?.data?.search_results).length || null,
        parseCountFromText(rawSummary, [/organized\s+(\d+)\s+search/i, /returned\s+(\d+)\s+results?/i, /(\d+)\s+search results?/i])
      );
      const debugImageCount = numericValue(
        parseCountFromText(rawSummary, [/saved\s+(\d+)\s+bbox/i, [/saved\s+(\d+)\s+debug/i], [/saved=(\d+)/i]].flat())
      );

      if (hasFailureMarker(log?.stage, log?.message)) {
        if (log?.agent === "ConfigValidator") {
          return formatConfigValidationFailure(rawSummary || log?.message || "");
        }
        return localeText("执行失败", "Failed");
      }
      if (log?.agent === "PlanAgent" || /querylist/.test(stage) || queryCount !== null) {
        return queryCount !== null
          ? localeText(`生成 ${queryCount} 条 queries`, `Prepared ${queryCount} queries`)
          : localeText("已生成查询计划", "Prepared review queries");
      }
      if (log?.agent === "ExploreAgent" && ["stage1_output", "stage_local_output"].includes(stage)) {
        return issueCount !== null
          ? localeText(`本地检查发现 ${issueCount} 个问题`, `Local check found ${issueCount} issues`)
          : localeText("本地检查完成", "Local check completed");
      }
      if (log?.agent === "ExploreAgent" && ["stage2_output", "stage_global_output"].includes(stage)) {
        return issueCount !== null
          ? localeText(`全局检查发现 ${issueCount} 个问题`, `Global check found ${issueCount} issues`)
          : localeText("全局检查完成", "Global check completed");
      }
      if (log?.agent === "ExploreAgent" && ["stage3_output", "stage_final_output"].includes(stage)) {
        return issueCount !== null
          ? localeText(`发现 ${issueCount} 个问题`, `Found ${issueCount} issues`)
          : localeText("已完成问题归纳", "Finalized issues");
      }
      if (log?.agent === "VisionAgent" && stage === "output") {
        if (/keep/.test(rawSummary)) return localeText("视觉复核：保留", "Vision decided keep");
        if (/drop/.test(rawSummary)) return localeText("视觉复核：剔除", "Vision decided drop");
        if (/review/.test(rawSummary)) return localeText("视觉复核：复查", "Vision decided review");
        return localeText("已完成视觉复核", "Vision review completed");
      }
      if (log?.agent === "ConfigValidator") {
        if (/cache hit|skipped/.test(rawSummary)) return localeText("配置未变更，跳过校验", "Configuration unchanged, skipped validation");
        if (/validated successfully|validated/.test(safeLower(rawSummary))) return localeText("运行时配置校验通过", "Runtime configuration validated");
        if (hasFailureMarker(rawSummary)) return localeText("运行时配置校验失败", "Runtime configuration validation failed");
        return localeText("正在校验运行时配置", "Validating runtime configuration");
      }
      if (log?.agent === "RecheckAgent" && /text_output|chunk_output/.test(stage)) {
        if (/drop/.test(rawSummary)) return localeText("复核：剔除", "Recheck decided drop");
        if (/review/.test(rawSummary)) return localeText("复核：复查", "Recheck decided review");
        if (/keep/.test(rawSummary)) return localeText("复核：保留", "Recheck decided keep");
        return localeText("已完成复核", "Recheck completed");
      }
      if (stage === "complete" || /review completed/.test(safeLower(rawSummary))) {
        return issueCount !== null
          ? localeText(`发现 ${issueCount} 个问题`, `Found ${issueCount} issues`)
          : localeText("检测完成", "Review completed");
      }
      if (/chunk_reading_done/.test(stage) || /prepared chunk excerpt/.test(safeLower(rawSummary))) {
        return imageCount !== null
          ? localeText(`已准备 chunk 内容，含 ${imageCount} 张图`, `Chunk ready with ${imageCount} images`)
          : localeText("已准备 chunk 内容", "Chunk ready");
      }
      if (/chunk_划分_done/.test(stage) || (/chunk/.test(phase) && /划分|divid|split/.test(phase)) || chunkCount !== null) {
        return chunkCount !== null
          ? localeText(`已划分 ${chunkCount} 个 chunks`, `Prepared ${chunkCount} chunks`)
          : localeText("已完成 chunk 划分", "Prepared chunks");
      }
      if (/pdf_解析_done|parse_complete/.test(stage) || (log?.agent === "PDFParser" && stage === "output")) {
        return localeText("PDF 解析完成", "PDF parsed");
      }
      if (/pdf_解析_start|parse_start/.test(stage) || (log?.agent === "PDFParser" && stage === "input")) {
        return localeText("正在解析 PDF", "Parsing PDF");
      }
      if (/bbox/.test(`${stage} ${phase}`)) {
        return debugImageCount !== null
          ? localeText(`已保存 ${debugImageCount} 张调试图`, `Saved ${debugImageCount} debug images`)
          : localeText("已输出调试截图", "Saved debug images");
      }
      if (/recheck/.test(`${stage} ${phase}`) && safeLower(log?.data?.status || "") === "done") {
        return localeText("已完成复核", "Recheck completed");
      }
      if (/vision/.test(`${stage} ${phase}`) && safeLower(log?.data?.status || "") === "done") {
        return localeText("已完成视觉复核", "Vision review completed");
      }
      if (safeLower(log?.data?.status || "") === "start" || /start|running|processing/.test(stage)) {
        return localeText("进行中", "In progress");
      }
      if (safeLower(log?.data?.status || "") === "done") {
        return localeText("已完成", "Completed");
      }
      return logPhaseLabel(log) || humanizeStage(log?.stage || "") || formatAgent(log?.agent || "System");
    }

    function populateConfigForm(payload) {
      Object.assign(configForm, {
        mineru_api_url: payload.mineru_api_url || "https://mineru.net/api/v4",
        mineru_api_key: payload.mineru_api_key || "",
        review_api_url: payload.review_api_url || payload.qwen_api_url || "https://dashscope.aliyuncs.com/compatible-mode/v1",
        review_api_key: payload.review_api_key || payload.qwen_api_key || "",
        review_model: payload.review_model || payload.qwen_review_model || payload.qwen_model || "",
        recheck_llm_api_url: payload.recheck_llm_api_url || payload.recheck_api_url || "",
        recheck_llm_api_key: payload.recheck_llm_api_key || payload.recheck_api_key || "",
        recheck_llm_model: payload.recheck_llm_model || payload.recheck_model || payload.qwen_recheck_model || "",
        recheck_vlm_api_url: payload.recheck_vlm_api_url || payload.vision_api_url || "",
        recheck_vlm_api_key: payload.recheck_vlm_api_key || payload.vision_api_key || "",
        recheck_vlm_model: payload.recheck_vlm_model || payload.vision_model || payload.qwen_vision_model || "",
        llm_request_min_interval_seconds: String(payload.llm_request_min_interval_seconds ?? "0"),
        search_engine: payload.search_engine || "duckduckgo",
        serper_api_key: payload.serper_api_key || "",
      });
    }

    async function fetchConfig() {
      try {
        const response = await fetch("/api/config");
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        populateConfigForm(payload);
        if (!localStorage.getItem(STORAGE_KEYS.reportLang)) {
          reportLanguage.value = payload.report_language || reportLanguage.value;
        }
        if (missingRequirements.value.length) {
          showSettingsPanel.value = true;
        }
      } catch (error) {
        showSettingsPanel.value = true;
        setAlert(configMessage, "error", t("configSaveFailedTitle"), error.message);
      }
    }

    async function saveConfig(options = {}) {
      clearAlert(configMessage);
      isSavingConfig.value = true;
      try {
        const payload = deepCopy({
          pdf_parse_backend: "mineru",
          mineru_api_url: configForm.mineru_api_url,
          mineru_api_key: configForm.mineru_api_key,
          review_api_url: configForm.review_api_url,
          review_api_key: configForm.review_api_key,
          review_model: configForm.review_model,
          recheck_llm_api_url: configForm.recheck_llm_api_url,
          recheck_llm_api_key: configForm.recheck_llm_api_key,
          recheck_llm_model: configForm.recheck_llm_model,
          recheck_vlm_api_url: configForm.recheck_vlm_api_url,
          recheck_vlm_api_key: configForm.recheck_vlm_api_key,
          recheck_vlm_model: configForm.recheck_vlm_model,
          llm_request_min_interval_seconds: configForm.llm_request_min_interval_seconds,
          search_engine: configForm.search_engine,
          serper_api_key: configForm.serper_api_key,
          report_language: reportLanguage.value,
        });
        const response = await fetch("/api/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        populateConfigForm(data);
        if (!options.silent) {
          setAlert(configMessage, "success", t("configSavedTitle"), t("configSavedBody"));
        }
        return true;
      } catch (error) {
        showSettingsPanel.value = true;
        setAlert(configMessage, "error", t("configSaveFailedTitle"), error.message);
        return false;
      } finally {
        isSavingConfig.value = false;
      }
    }

    function decorateResult(taskId, result) {
      if (!result) return null;
      const nextResult = { ...result };
      nextResult.issues = asArray(result.issues).map((issue, index) => ({
        ...issue,
        reasoning: fieldText(issue?.reasoning, "\n"),
        client_id: issue.client_id || `${taskId}-${issue.chunk_id ?? "na"}-${index}-${issue.type_key || issue.type || "issue"}`,
      }));
      return nextResult;
    }

    function decorateIssues(task) {
      if (!task?.result) return task;
      task.result = decorateResult(task.id, task.result);
      return task;
    }

    function decorateTask(task) {
      const nextTask = { ...task };
      nextTask.logs = sortLogs(asArray(task.logs).map((log, index) => normalizeLog(log, index)));
      if (task.result) nextTask.result = decorateResult(task.id, task.result);
      return decorateIssues(nextTask);
    }

    function mergeIncomingResult(taskId, resultPayload) {
      if (!currentTask.value || currentTask.value.id !== taskId || !resultPayload) return;
      currentTask.value.result = {
        ...(currentTask.value.result || {}),
        ...(decorateResult(taskId, resultPayload) || {}),
      };
      ensureSelectedIssue();
      syncCurrentTaskSummary(currentTask.value);
    }

    async function refreshTasks(showLoading = false) {
      if (showLoading) tasksLoading.value = true;
      try {
        const response = await fetch("/api/tasks");
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        tasks.value = await response.json();
      } catch (error) {
        setAlert(uploadMessage, "error", t("uploadFailedTitle"), error.message);
      } finally {
        tasksLoading.value = false;
      }
    }

    function ensureSelectedIssue() {
      const issues = filteredIssues.value.length ? filteredIssues.value : visibleIssues.value;
      if (!issues.length) {
        selectedIssueId.value = "";
        return;
      }
      if (!issues.some((issue) => issue.client_id === selectedIssueId.value)) {
        selectedIssueId.value = issues[0].client_id;
      }
    }

    function setPageShellRef(pageNumber, element) {
      if (element) pageShellRefs.set(pageNumber, element);
      else pageShellRefs.delete(pageNumber);
    }

    async function loadPdf(task) {
      if (!task?.id) {
        pdfTaskId.value = "";
        pageCount.value = 0;
        currentPageNum.value = 1;
        pdfPages.value = [];
        pageShellRefs.clear();
        return;
      }

      if (pdfTaskId.value === task.id && pdfPages.value.length) {
        return;
      }

      pdfLoading.value = true;
      pdfError.value = "";
      pageShellRefs.clear();
      try {
        const response = await fetch(`/api/tasks/${task.id}/pages`);
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(payload.error || `HTTP ${response.status}`);
        }
        pdfTaskId.value = task.id;
        pdfPages.value = asArray(payload.pages)
          .map((page) => ({
            pageNumber: Number(page.page_number || page.pageNumber || 0),
            width: Number(page.width || 0),
            height: Number(page.height || 0),
            imageUrl: page.image_url || page.imageUrl || "",
          }))
          .filter((page) => page.pageNumber > 0);
        pageCount.value = Number(payload.page_count || pdfPages.value.length || 0);
        currentPageNum.value = clamp(issuePage(selectedIssue.value) || 1, 1, pageCount.value || 1);
        await nextTick();
        if (selectedIssue.value) focusIssueBBox(selectedIssue.value, "auto");
        else scrollToPage(currentPageNum.value, "auto");
      } catch (error) {
        pdfTaskId.value = "";
        pageCount.value = 0;
        currentPageNum.value = 1;
        pdfPages.value = [];
        pdfError.value = `${t("loadingPdf")}: ${error.message}`;
      } finally {
        pdfLoading.value = false;
      }
    }

    function pageDisplayWidth(page) {
      return Number(page?.width || 0) * zoom.value;
    }

    function pageDisplayHeight(page) {
      return Number(page?.height || 0) * zoom.value;
    }

    function pageShellStyle(page) {
      return {
        width: `${pageDisplayWidth(page)}px`,
        height: `${pageDisplayHeight(page)}px`,
      };
    }

    function pageViewport(pageNumber) {
      const section = pageShellRefs.get(pageNumber);
      const shell = section?.querySelector(".pdf-page-shell") || null;
      const page = pdfPages.value.find((item) => item.pageNumber === pageNumber) || null;
      return { section, shell, page };
    }

    function lockPdfScroll(behavior) {
      scrollSyncLock.value = true;
      window.setTimeout(() => {
        scrollSyncLock.value = false;
      }, behavior === "smooth" ? 350 : 0);
    }

    function pageBoxes(pageNumber) {
      const issue = selectedIssue.value;
      if (!issue) return [];
      const activeTargetId = currentFocusTarget(issue)?.id || "";
      return issueFocusTargets(issue)
        .filter((target) => target.match.page === pageNumber)
        .map((target) => ({
          id: `${pageNumber}:${target.id}`,
          kind: target.kind,
          label: target.label,
          bbox: target.match.bbox,
          active: target.id === activeTargetId,
        }));
    }

    function boxStyle(box, page) {
      const size = currentTask.value?.result?.bbox_debug_summary?.bbox_normalized_size || 1000;
      const [x1, y1, x2, y2] = box.bbox || [0, 0, 0, 0];
      const width = pageDisplayWidth(page);
      const height = pageDisplayHeight(page);
      return {
        left: `${(x1 / size) * width}px`,
        top: `${(y1 / size) * height}px`,
        width: `${((x2 - x1) / size) * width}px`,
        height: `${((y2 - y1) / size) * height}px`,
      };
    }

    function scrollToPage(pageNumber, behavior = "smooth") {
      const { section } = pageViewport(pageNumber);
      if (!section || !pdfScrollRef.value) return;
      const containerRect = pdfScrollRef.value.getBoundingClientRect();
      const sectionRect = section.getBoundingClientRect();
      lockPdfScroll(behavior);
      pdfScrollRef.value.scrollTo({
        top: Math.max(0, pdfScrollRef.value.scrollTop + (sectionRect.top - containerRect.top) - 12),
        behavior,
      });
    }

    function focusIssueBBox(issue, behavior = "smooth") {
      const { targets, index } = syncPdfFocusState(issue, false);
      const match = targets[index]?.match || preferredTargetMatch(issue);
      if (!match || !pdfScrollRef.value || !Array.isArray(match.bbox)) return;

      const { shell, page } = pageViewport(match.page);
      if (!shell || !page) {
        scrollToPage(match.page, behavior);
        return;
      }

      const size = currentTask.value?.result?.bbox_debug_summary?.bbox_normalized_size || 1000;
      const [x1, y1, x2, y2] = match.bbox;
      const width = pageDisplayWidth(page);
      const height = pageDisplayHeight(page);
      const containerRect = pdfScrollRef.value.getBoundingClientRect();
      const shellRect = shell.getBoundingClientRect();
      const targetLeft = Math.max(
        0,
        pdfScrollRef.value.scrollLeft +
          (shellRect.left - containerRect.left) +
          (((x1 + x2) / 2) / size) * width -
          pdfScrollRef.value.clientWidth * 0.45
      );
      const targetTop = Math.max(
        0,
        pdfScrollRef.value.scrollTop +
          (shellRect.top - containerRect.top) +
          (((y1 + y2) / 2) / size) * height -
          pdfScrollRef.value.clientHeight * 0.42
      );

      lockPdfScroll(behavior);
      pdfScrollRef.value.scrollTo({
        left: targetLeft,
        top: targetTop,
        behavior,
      });
      pageChangeSource.value = "program";
      currentPageNum.value = match.page;
    }

    function handlePdfScroll() {
      if (!pdfScrollRef.value || scrollSyncLock.value) return;
      const containerTop = pdfScrollRef.value.getBoundingClientRect().top;
      let closestPage = currentPageNum.value;
      let closestDistance = Number.POSITIVE_INFINITY;
      pdfPages.value.forEach((page) => {
        const shell = pageShellRefs.get(page.pageNumber);
        if (!shell) return;
        const distance = Math.abs(shell.getBoundingClientRect().top - containerTop - 12);
        if (distance < closestDistance) {
          closestDistance = distance;
          closestPage = page.pageNumber;
        }
      });
      pageChangeSource.value = "scroll";
      currentPageNum.value = closestPage;
    }

    function prevPage() {
      if (!pageCount.value) return;
      pageChangeSource.value = "program";
      currentPageNum.value = clamp(currentPageNum.value - 1, 1, pageCount.value);
      scrollToPage(currentPageNum.value);
    }

    function nextPage() {
      if (!pageCount.value) return;
      pageChangeSource.value = "program";
      currentPageNum.value = clamp(currentPageNum.value + 1, 1, pageCount.value);
      scrollToPage(currentPageNum.value);
    }

    function zoomIn() {
      zoom.value = clamp(Number((zoom.value + 0.1).toFixed(2)), 0.7, 2.4);
    }

    function zoomOut() {
      zoom.value = clamp(Number((zoom.value - 0.1).toFixed(2)), 0.7, 2.4);
    }

    function paneStyle(name) {
      if (isStackedLayout.value) return {};
      if (!showProcessPanel.value && (name === "left" || name === "middle")) {
        const total = panelSizes.left + panelSizes.middle;
        const share = total > 0 ? (panelSizes[name] / total) * 100 : name === "left" ? 58 : 42;
        return { flexBasis: `${share}%` };
      }
      return { flexBasis: `${panelSizes[name]}%` };
    }

    function toggleProcessPanel() {
      showProcessPanel.value = !showProcessPanel.value;
      stopResize();
    }

    function scrollProcessToBottom(behavior = "auto") {
      if (!processScrollRef.value) return;
      processScrollRef.value.scrollTo({
        top: processScrollRef.value.scrollHeight,
        behavior,
      });
    }

    function stopResize() {
      resizeState.handle = "";
      window.removeEventListener("mousemove", onResizeMove);
      window.removeEventListener("mouseup", stopResize);
    }

    function onResizeMove(event) {
      if (!resizeState.handle || isStackedLayout.value || !workspaceRef.value) return;
      const bounds = workspaceRef.value.getBoundingClientRect();
      const delta = ((event.clientX - resizeState.startX) / bounds.width) * 100;
      if (resizeState.handle === "left") {
        const nextLeft = clamp(resizeState.left + delta, 24, 58);
        panelSizes.left = nextLeft;
        panelSizes.middle = clamp(resizeState.middle - (nextLeft - resizeState.left), 20, 44);
        panelSizes.right = 100 - panelSizes.left - panelSizes.middle;
      } else if (resizeState.handle === "right") {
        const nextMiddle = clamp(resizeState.middle + delta, 22, 42);
        panelSizes.middle = nextMiddle;
        panelSizes.right = clamp(resizeState.right - (nextMiddle - resizeState.middle), 24, 44);
        panelSizes.left = 100 - panelSizes.middle - panelSizes.right;
      }
    }

    function startResize(handle, event) {
      if (isStackedLayout.value) return;
      resizeState.handle = handle;
      resizeState.startX = event.clientX;
      resizeState.left = panelSizes.left;
      resizeState.middle = panelSizes.middle;
      resizeState.right = panelSizes.right;
      window.addEventListener("mousemove", onResizeMove);
      window.addEventListener("mouseup", stopResize);
    }

    function updateLayoutMode() {
      isStackedLayout.value = window.innerWidth <= 980;
    }

    function syncCurrentTaskSummary(task) {
      if (!task) return;
      const summary = {
        id: task.id,
        mode: task.mode,
        pdf_name: task.pdf_name,
        status: task.status,
        progress: task.progress,
        confirmed_issue_count: visibleIssues.value.length,
        issue_count: asArray(task.result?.issues).length,
        created_at: task.created_at,
        completed_at: task.completed_at,
      };
      const nextTasks = tasks.value.slice();
      const index = nextTasks.findIndex((item) => item.id === task.id);
      if (index >= 0) nextTasks[index] = { ...nextTasks[index], ...summary };
      tasks.value = nextTasks;
    }

    function classifyProcessItem(log) {
      const stageText = safeLower(`${log?.stage || ""} ${log?.message || ""} ${log?.data?.phase || ""}`);
      if (log?.agent === "ConfigValidator" || /config validation|preflight/.test(stageText)) {
        return {
          key: "config-validation",
          title: localeText("配置校验", "Config Validation"),
          order: 5,
        };
      }
      if (hasChunkId(log)) {
        const chunkNumber = Number(log?.data?.chunk_id || 0) + 1;
        return {
          key: `chunk-${log.data.chunk_id}`,
          title: `${t("processChunk")} ${chunkNumber}`,
          order: 30 + Number(log.data.chunk_id),
        };
      }
      if (log?.agent === "PDFParser" || /pdf|parse|upload|poll|mineru/.test(stageText)) {
        return { key: "pdf-parsing", title: t("processPdfParsing"), order: 10 };
      }
      if (/chunk|split|divide|excerpt/.test(stageText)) {
        return { key: "chunk-dividing", title: t("processChunkDividing"), order: 20 };
      }
      if (/bbox/.test(stageText)) {
        return { key: "bbox-debug", title: t("processBBoxDebug"), order: 120 };
      }
      if (/vision/.test(stageText)) {
        return { key: "vision-validation", title: t("processVisionValidation"), order: 130 };
      }
      return { key: "pipeline", title: t("processPipeline"), order: 0 };
    }

    function processActorType(agent, stage = "") {
      const normalizedAgent = safeLower(agent);
      const normalizedStage = safeLower(stage);
      if (normalizedAgent === "user" || normalizedStage === "user_query" || normalizedStage === "query") {
        return "user";
      }
      return "bot";
    }

    function processActorLabel(agent) {
      return formatAgent(agent || "System");
    }

    function itemStatus(hasLatest) {
      if (currentTask.value?.status === "failed" && hasLatest) return "failed";
      if (isTaskActive.value && hasLatest) return "running";
      if (currentTask.value?.status === "pending" && !processLogEntries().length) return "pending";
      return "done";
    }

    function statusTextFor(status) {
      if (status === "running") return t("processRunning");
      if (status === "failed") return t("processFailed");
      if (status === "pending") return t("processPending");
      return t("processDone");
    }

    function logMessageStatus(log) {
      const text = safeLower(`${log?.stage || ""} ${log?.data?.status || ""} ${log?.message || ""}`);
      const stage = safeLower(log?.stage || "");
      const explicitStatus = safeLower(log?.data?.status || "");
      if (stage === "config_validation_error") return "failed";
      if (isConfigValidationDoneStage(stage)) return "done";
      if (isConfigValidationStage(stage)) return "running";
      if (hasFailureMarker(text)) return "failed";
      if (/cancelled|canceled|终止|取消/.test(text)) return "failed";
      if (["done", "complete", "completed", "success"].includes(explicitStatus)) return "done";
      if (["start", "running", "progress", "heading"].includes(explicitStatus)) return "running";
      if (/parse_complete|chunk_complete|complete/.test(text)) return "done";
      if (/_output| output|produced|generated|contains|fallback|preserving/.test(text)) return "done";
      if (/llm_request|calling|_input| input/.test(text)) return "running";
      if (/start|running|processing/.test(text)) return "running";
      if (isTaskActive.value && log?.client_id === latestLogId.value) return "running";
      return "done";
    }

    function compactProcessLines(...values) {
      const lines = [];
      const seen = new Set();
      const queue = [];
      values.forEach((value) => {
        if (Array.isArray(value)) {
          queue.push(...value);
          return;
        }
        if (value && typeof value === "object") {
          if (typeof value.summary === "string") queue.push(value.summary);
          if (typeof value.text === "string") queue.push(value.text);
          if (typeof value.analysis === "string") queue.push(value.analysis);
          return;
        }
        queue.push(value);
      });
      queue.forEach((value) => {
        String(value || "")
          .replace(/\r/g, "\n")
          .split(/\n+/)
          .map((line) => line.replace(/^[\s\-*.()0-9]+/, "").trim())
          .filter(Boolean)
          .forEach((line) => {
            const signature = safeLower(line);
            if (!signature || seen.has(signature)) return;
            seen.add(signature);
            lines.push(truncateText(line, 180));
          });
      });
      return lines;
    }

    function classifyProcessChild(log, item) {
      const stageText = safeLower(`${log?.agent || ""} ${log?.stage || ""} ${log?.message || ""} ${log?.data?.phase || ""}`);
      if (String(item?.key || "").startsWith("chunk-")) {
        if (log?.agent === "PlanAgent" || /plan chunk|querylist|plan/.test(stageText)) {
          return { key: `${item.key}:plan`, title: t("processStagePlanChunk"), order: 20 };
        }
        if (log?.agent === "ExploreAgent" || /stage_local|stage_global|stage_final|local check|global check|finalize errorlist|explore/.test(stageText)) {
          if (/stage_local|local check|local_check/.test(stageText)) {
            return { key: `${item.key}:explore-local`, title: t("processStageLocalCheck"), order: 30 };
          }
          if (/stage_global|global check|global_check/.test(stageText)) {
            return { key: `${item.key}:explore-global`, title: t("processStageGlobalCheck"), order: 31 };
          }
          if (/stage_final|finalize errorlist|finalize_errorlist/.test(stageText)) {
            return { key: `${item.key}:explore-final`, title: t("processStageFinalizeErrorList"), order: 32 };
          }
          return { key: `${item.key}:explore`, title: t("processExploreAgent"), order: 33 };
        }
        if (log?.agent === "SearchAgent" || /search/.test(stageText)) {
          return { key: `${item.key}:search`, title: t("processSearchAgent"), order: 35 };
        }
        if (log?.agent === "SummaryAgent" || /summarize findings|summary/.test(stageText)) {
          return { key: `${item.key}:summary`, title: t("processStageSummarizeFindings"), order: 45 };
        }
        if (log?.agent === "RecheckAgent" || /recheck/.test(stageText)) {
          return { key: `${item.key}:recheck`, title: localeText("复核", "Recheck"), order: 47 };
        }
        if (log?.agent === "VisionAgent" || /vision/.test(stageText)) {
          return { key: `${item.key}:vision`, title: t("processStageVisualCheck"), order: 50 };
        }
        if (/bbox/.test(stageText)) {
          return { key: `${item.key}:bbox`, title: t("processBBoxDebug"), order: 60 };
        }
        return { key: `${item.key}:reading`, title: t("processChunkReading"), order: 10 };
      }
      if (item?.key === "pdf-parsing" && log?.agent === "PDFParser") {
        return { key: `${item.key}:parser`, title: t("processPdfParser"), order: 10 };
      }
      return null;
    }

    function processStageTitle(log) {
      const stage = safeLower(log?.stage || "");
      const phase = safeLower(log?.data?.phase || "");
      if (log?.agent === "ConfigValidator") return localeText("配置校验", "Config Validation");
      if (log?.agent === "PlanAgent") return t("processStagePlanChunk");
      if (log?.agent === "ExploreAgent" && /stage_local/.test(stage)) return t("processStageLocalCheck");
      if (log?.agent === "ExploreAgent" && /stage_global/.test(stage)) return t("processStageGlobalCheck");
      if (log?.agent === "ExploreAgent" && /stage_final/.test(stage)) return t("processStageFinalizeErrorList");
      if (log?.agent === "SummaryAgent") return t("processStageSummarizeFindings");
      if (log?.agent === "RecheckAgent" || /recheck/.test(stage)) return localeText("复核", "Recheck");
      if (log?.agent === "VisionAgent") return t("processStageVisualCheck");
      if (/plan chunk/.test(phase)) return t("processStagePlanChunk");
      if (/local_check/.test(stage) || /local check/.test(phase)) return t("processStageLocalCheck");
      if (/global_check/.test(stage) || /global check/.test(phase)) return t("processStageGlobalCheck");
      if (/finalize_errorlist/.test(stage) || /finalize errorlist/.test(phase)) return t("processStageFinalizeErrorList");
      if (/summarize_findings/.test(stage) || /summarize findings/.test(phase)) return t("processStageSummarizeFindings");
      if (/chunk/.test(phase) && /reading/.test(phase)) return t("processChunkReading");
      if (/bbox/.test(stage) || /bbox/.test(phase)) return t("processBBoxDebug");
      if (/vision/.test(stage) || /vision/.test(phase)) return t("processStageVisualCheck");
      return humanizeStage(log?.data?.phase || log?.stage || "") || formatAgent(log?.agent || "System");
    }

    function makeProcessNode(key, title, order = 0) {
      return {
        key,
        title,
        order,
        logs: [],
        lines: [],
        queries: [],
        children: new Map(),
        _lineSignatures: new Set(),
        _querySignatures: new Set(),
      };
    }

    function latestMeaningfulSummary(logs) {
      const generic = new Set([
        safeLower(t("processDone")),
        safeLower(t("processRunning")),
        safeLower(t("processPending")),
        safeLower(t("processFailed")),
        safeLower(localeText("已完成", "Completed")),
        safeLower(localeText("进行中", "In progress")),
      ]);
      for (let index = logs.length - 1; index >= 0; index -= 1) {
        const summary = truncateText(processEntryText(logs[index]), 180);
        if (!summary || generic.has(safeLower(summary))) continue;
        return summary;
      }
      return logs.length ? truncateText(processEntryText(logs[logs.length - 1]), 180) : "";
    }

    function summaryScore(text) {
      const value = safeLower(text);
      if (!value) return -1;
      if (/issues?|问题/.test(value)) return 5;
      if (/queries?|query/.test(value)) return 4;
      if (/chunk ready|准备 chunk|prepared chunks|划分/.test(value)) return 3;
      if (/pdf/.test(value)) return 2;
      if (/vision|视觉|debug|调试/.test(value)) return 1;
      if ([safeLower(localeText("已完成", "Completed")), safeLower(localeText("进行中", "In progress"))].includes(value)) return 0;
      return 2;
    }

    function bestNodeSummary(nodeSummary, childSummaries = []) {
      const candidates = [nodeSummary, ...childSummaries].filter(Boolean);
      if (!candidates.length) return "";
      return candidates
        .slice()
        .sort((left, right) => summaryScore(right) - summaryScore(left))[0];
    }

    function nodeStatus(logs, nodeKey = "") {
      if (!logs.length) {
        return currentTask.value?.status === "pending" ? "pending" : "done";
      }
      const lastLog = logs[logs.length - 1];
      if (currentTask.value?.status === "failed" && logs.some((entry) => logMessageStatus(entry) === "failed")) {
        return "failed";
      }
      const status = logMessageStatus(lastLog);
      if (
        isTaskActive.value &&
        String(nodeKey || "").startsWith("chunk-") &&
        !logs.some((entry) => {
          const stage = safeLower(entry?.stage || "");
          const message = safeLower(entry?.message || "");
          return stage === "chunk_complete" || /completed chunk/.test(message);
        })
      ) {
        return "running";
      }
      if (status === "running") {
        return currentTask.value?.status === "completed" ? "done" : "running";
      }
      return status;
    }

    function buildProcessLine(log, fallbackKey) {
      const text = truncateText(processEntryText(log), 180);
      if (!text) return null;
      const label = processStageTitle(log);
      return {
        key: `${fallbackKey}:${log?.client_id || log?.stage || "line"}`,
        label,
        text,
        time: formatTime(log?.ts),
        signature: `${safeLower(label)}::${safeLower(text)}`,
      };
    }

    function buildProcessQueries(log, fallbackKey) {
      return asArray(log?.data?.query_list).map((query, index) => ({
        key: `${fallbackKey}:${log?.client_id || log?.stage || "query"}:${index}`,
        label: `${t("processQuery")} ${index + 1}`,
        text: truncateText(query, 220),
        signature: safeLower(String(query || "").trim()),
      }));
    }

    function finalizeProcessNode(node, isTopLevel = false) {
      const children = Array.from(node.children.values())
        .sort((left, right) => left.order - right.order)
        .map((child) => finalizeProcessNode(child));
      const summary = bestNodeSummary(
        latestMeaningfulSummary(node.logs),
        children.map((child) => child.summary)
      );
      const status = nodeStatus(node.logs, node.key);
      const lastLog = node.logs[node.logs.length - 1];
      if (expandedSections[node.key] === undefined) {
        expandedSections[node.key] = false;
      }
      return {
        key: node.key,
        title: node.title,
        status,
        statusLabel: statusTextFor(status),
        time: formatTime(lastLog?.ts),
        summary,
        queries: node.queries.map(({ key, label, text }) => ({ key, label, text })),
        lines: node.lines
          .filter((line) => safeLower(line.text) !== safeLower(summary))
          .slice(-4)
          .map(({ key, label, text, time }) => ({ key, label, text, time })),
        children,
      };
    }

    function buildProcessMessages() {
      const messages = [];
      processLogEntries().forEach((log, index) => {
        const itemInfo = classifyProcessItem(log);
        const status = logMessageStatus(log);
        const summary = truncateText(processEntryText(log), 160) || statusTextFor(status);
        const actorType = processActorType(log?.agent, log?.stage);
        const scope = itemInfo.title === t("processPipeline") ? "" : itemInfo.title;
        const points = compactProcessLines(
          log?.data?.summary,
          log?.data?.details,
          log?.message
        )
          .filter((line) => safeLower(line) !== safeLower(summary))
          .slice(0, 3);

        const phaseLabel = humanizeStage(log?.data?.phase || "");
        const stageLabel = humanizeStage(log?.stage || "");
        if (phaseLabel && !points.some((line) => safeLower(line) === safeLower(phaseLabel)) && safeLower(summary) !== safeLower(phaseLabel)) {
          points.unshift(phaseLabel);
        }
        if (
          stageLabel &&
          stageLabel !== phaseLabel &&
          !points.some((line) => safeLower(line) === safeLower(stageLabel)) &&
          safeLower(summary) !== safeLower(stageLabel)
        ) {
          points.push(stageLabel);
        }

        const signature = [actorType, processActorLabel(log?.agent), scope, summary, points.join("|"), status].join("::");
        if (messages[messages.length - 1]?.signature === signature) return;

        messages.push({
          key: log?.client_id || `process-message-${index}`,
          signature,
          actorType,
          actorLabel: processActorLabel(log?.agent),
          scope,
          status,
          statusLabel: statusTextFor(status),
          time: formatTime(log?.ts),
          summary,
          points,
        });
      });
      return messages;
    }

    function buildProcessItems() {
      const logs = processLogEntries();
      const grouped = new Map();
      const ordered = [];
      logs.forEach((log) => {
        const itemInfo = classifyProcessItem(log);
        if (!grouped.has(itemInfo.key)) {
          grouped.set(itemInfo.key, {
            key: itemInfo.key,
            title: itemInfo.title,
            order: itemInfo.order,
            logs: [],
            children: new Map(),
          });
          ordered.push(grouped.get(itemInfo.key));
        }
        const item = grouped.get(itemInfo.key);
        item.logs.push(log);

        const childLabel = processChildLabel(log);
        const childKey = `${item.key}:${safeLower(childLabel)}`;
        if (!item.children.has(childKey)) {
          item.children.set(childKey, {
            key: childKey,
            label: childLabel,
            logs: [],
          });
        }
        item.children.get(childKey).logs.push(log);
      });

      return ordered
        .sort((left, right) => left.order - right.order)
        .map((item) => {
          const lastLog = item.logs[item.logs.length - 1];
          const hasLatest = lastLog?.client_id === latestLogId.value;
          const status = itemStatus(hasLatest);
          if (expandedSections[item.key] === undefined) {
            expandedSections[item.key] = false;
          }

          const children = Array.from(item.children.values()).map((child) => {
            const childLastLog = child.logs[child.logs.length - 1];
            if (expandedSections[child.key] === undefined) {
              expandedSections[child.key] = false;
            }
            return {
              key: child.key,
              label: child.label,
              actorType: processActorType(childLastLog?.agent),
              actorLabel: processActorLabel(childLastLog?.agent),
              preview: truncateText(processEntryText(childLastLog), 72),
              entries: child.logs.map((entry, entryIndex) => ({
                key: `${child.key}:${entryIndex}`,
                time: formatTime(entry.ts),
                actorType: processActorType(entry.agent),
                actorLabel: processActorLabel(entry.agent),
                text: truncateText(processEntryText(entry), 140),
              })),
            };
          });

          return {
            key: item.key,
            title: item.title,
            status,
            statusText: statusTextFor(status),
            actorType: processActorType(lastLog?.agent),
            actorLabel: processActorLabel(lastLog?.agent),
            summary: truncateText(processEntryText(lastLog), 72),
            preview: truncateText(
              item.logs
                .slice(-2)
                .map((entry) => processEntryText(entry))
                .filter(Boolean)
                .join(" · "),
              108
            ),
            children,
          };
        });
    }

    function buildProcessTreeItems() {
      const logs = processLogEntries();
      const grouped = new Map();
      const ordered = [];

      const ensureItem = (info) => {
        if (!grouped.has(info.key)) {
          grouped.set(info.key, makeProcessNode(info.key, info.title, info.order));
          ordered.push(grouped.get(info.key));
        }
        return grouped.get(info.key);
      };

      logs.forEach((log, index) => {
        const itemInfo = classifyProcessItem(log);
        const item = ensureItem(itemInfo);
        item.logs.push(log);

        const childInfo = classifyProcessChild(log, itemInfo);
        const target = childInfo
          ? (() => {
              if (!item.children.has(childInfo.key)) {
                item.children.set(childInfo.key, makeProcessNode(childInfo.key, childInfo.title, childInfo.order));
              }
              const child = item.children.get(childInfo.key);
              child.logs.push(log);
              return child;
            })()
          : item;

        const line = buildProcessLine(log, target.key || item.key || `process-${index}`);
        if (line && !target._lineSignatures.has(line.signature)) {
          target._lineSignatures.add(line.signature);
          target.lines.push(line);
        }

        buildProcessQueries(log, target.key || item.key || `process-${index}`).forEach((query) => {
          if (!query.signature || target._querySignatures.has(query.signature)) return;
          target._querySignatures.add(query.signature);
          target.queries.push(query);
        });
      });

      return ordered
        .sort((left, right) => left.order - right.order)
        .map((item) => finalizeProcessNode(item, true));
    }

    function buildWorkflowStages() {
      const logs = processLogEntries();
      const configLogs = logs.filter((log) => log?.agent === "ConfigValidator");
      const configStarted = configLogs.length > 0;
      const configHasFailed = configLogs.some((log) => hasFailureMarker(log?.stage, log?.message));
      const configDone = configLogs.some((log) => isConfigValidationDoneStage(log?.stage));
      const hasChunks = logs.some((log) => hasChunkId(log));
      const preprocessingDone = pageCount.value > 0 || progressPercent.value >= 30 || currentTask.value?.status === "completed";
      const preprocessingRunning = isTaskActive.value && !hasChunks;
      const findingRunning = isTaskActive.value && hasChunks;
      const findingDone = currentTask.value?.status === "completed" || (!isTaskActive.value && hasChunks);

      return [
        {
          key: "config-validation",
          label: localeText("配置校验", "Config Validation"),
          description: localeText("校验 MinerU、Review Model 与可选配置是否可用。", "Validate MinerU, the Review Model, and optional services before review."),
          status: configHasFailed ? "failed" : configDone ? "done" : configStarted ? "running" : "pending",
        },
        {
          key: "preprocessing",
          label: t("workflowPreprocessing"),
          description: t("workflowPreprocessingDesc"),
          status: preprocessingDone ? "done" : preprocessingRunning ? "running" : "pending",
        },
        {
          key: "finding",
          label: t("workflowFinding"),
          description: t("workflowFindingDesc"),
          status: findingDone ? "done" : findingRunning ? "running" : "pending",
        },
      ];
    }

    function isSectionOpen(key) {
      return Boolean(expandedSections[key]);
    }

    function toggleSection(key) {
      expandedSections[key] = !expandedSections[key];
    }

    async function refreshTask(taskId, options = {}) {
      const { manageRealtime = false, syncList = true } = options;
      try {
        const response = await fetch(`/api/tasks/${taskId}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const previousTaskId = currentTask.value?.id || "";
        const payload = decorateTask(await response.json());
        if (previousTaskId !== payload.id) {
          Object.keys(expandedSections).forEach((key) => {
            delete expandedSections[key];
          });
        }
        currentTask.value = payload;
        currentView.value = "review";
        setHashTaskId(taskId);
        lastViewedTaskId.value = taskId;
        localStorage.setItem(STORAGE_KEYS.lastTaskId, taskId);
        ensureSelectedIssue();
        await nextTick();
        await loadPdf(payload);
        if (syncList) await refreshTasks(false);
        if (manageRealtime) {
          if (["pending", "running", "cancelling"].includes(payload.status)) ensureRealtime(taskId);
          else stopRealtime();
        }
      } catch (error) {
        setAlert(uploadMessage, "error", t("uploadFailedTitle"), error.message);
      }
    }

    function appendLog(logPayload) {
      if (!currentTask.value) return;
      const normalized = normalizeLog(logPayload, asArray(currentTask.value.logs).length);
      const exists = asArray(currentTask.value.logs).some(
        (log) =>
          log.client_id === normalized.client_id ||
          (log.ts === normalized.ts &&
            log.agent === normalized.agent &&
            log.stage === normalized.stage &&
            log.message === normalized.message)
      );
      if (!exists) {
        currentTask.value.logs = sortLogs([...asArray(currentTask.value.logs), normalized]);
      }
    }

    function sendProcessInstruction() {
      if (!processInstructionDraft.value.trim()) return;
    }

    function stopRealtime() {
      if (streamSource.value) streamSource.value.close();
      streamSource.value = null;
      streamTaskId.value = "";
      if (taskPollTimer.value) window.clearInterval(taskPollTimer.value);
      taskPollTimer.value = null;
    }

    function ensureRealtime(taskId) {
      if (streamTaskId.value === taskId && streamSource.value) return;
      stopRealtime();
      const source = new EventSource(`/api/tasks/${taskId}/stream`);
      streamSource.value = source;
      streamTaskId.value = taskId;

      source.addEventListener("log", (event) => {
        try {
          appendLog(JSON.parse(event.data));
        } catch (error) {
          console.error(error);
        }
      });

      source.addEventListener("progress", (event) => {
        try {
          const progress = JSON.parse(event.data);
          if (currentTask.value && currentTask.value.id === taskId) {
            currentTask.value.progress = { ...(currentTask.value.progress || {}), ...progress };
            syncCurrentTaskSummary(currentTask.value);
          }
        } catch (error) {
          console.error(error);
        }
      });

      source.addEventListener("result", (event) => {
        try {
          mergeIncomingResult(taskId, JSON.parse(event.data));
        } catch (error) {
          console.error(error);
        }
      });

      source.addEventListener("complete", async () => {
        await refreshTask(taskId, { manageRealtime: false, syncList: true });
        stopRealtime();
      });

      source.addEventListener("cancelled", async () => {
        await refreshTask(taskId, { manageRealtime: false, syncList: true });
        stopRealtime();
      });

      source.addEventListener("error", async (event) => {
        if (!event?.data) return;
        try {
          const payload = JSON.parse(event.data);
          setAlert(uploadMessage, "error", t("uploadFailedTitle"), payload.message || "");
        } catch (error) {
          console.error(error);
        }
        await refreshTask(taskId, { manageRealtime: false, syncList: true });
        stopRealtime();
      });

      source.onerror = () => {
        if (!currentTask.value || currentTask.value.id !== taskId) {
          stopRealtime();
          return;
        }
        if (!["pending", "running", "cancelling"].includes(currentTask.value.status)) {
          stopRealtime();
        }
      };

      taskPollTimer.value = window.setInterval(async () => {
        if (!currentTask.value || currentTask.value.id !== taskId) {
          stopRealtime();
          return;
        }
        await refreshTask(taskId, { manageRealtime: false, syncList: false });
        syncCurrentTaskSummary(currentTask.value);
        if (!["pending", "running", "cancelling"].includes(currentTask.value.status)) {
          stopRealtime();
          await refreshTasks(false);
        }
      }, 2500);
    }

    async function startReview() {
      clearAlert(uploadMessage);
      if (!selectedFile.value) return;

      const configSaved = await saveConfig({ silent: true });
      if (!configSaved) return;

      isUploading.value = true;
      try {
        const formData = new FormData();
        formData.append("file", selectedFile.value);
        formData.append("mode", mode.value);
        formData.append("report_language", reportLanguage.value);

        const response = await fetch("/api/upload", { method: "POST", body: formData });
        const payload = await response.json();

        if (response.status === 409) {
          await refreshTasks(false);
          setAlert(uploadMessage, "warn", t("uploadConflictTitle"), payload.error || t("singleTaskLimitBody"));
          return;
        }
        if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);

        setAlert(uploadMessage, "success", t("uploadStartedTitle"), t("uploadStartedBody"));
        selectedFile.value = null;
        if (fileInputRef.value) fileInputRef.value.value = "";
        await refreshTasks(false);
        await refreshTask(payload.id || payload.task_id, { manageRealtime: true, syncList: true });
      } catch (error) {
        setAlert(uploadMessage, "error", t("uploadFailedTitle"), error.message);
      } finally {
        isUploading.value = false;
      }
    }

    async function openTask(taskId) {
      clearAlert(uploadMessage);
      await refreshTask(taskId, { manageRealtime: true, syncList: true });
    }

    async function deleteCompletedTask(task) {
      const taskId = task?.id || "";
      if (!taskId || deletingTaskId.value) return;
      if (!window.confirm(t("deleteTaskConfirm"))) return;

      deletingTaskId.value = taskId;
      try {
        const response = await fetch(`/api/tasks/${taskId}`, { method: "DELETE" });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(payload.error || `HTTP ${response.status}`);
        }

        if (currentTask.value?.id === taskId) {
          stopRealtime();
          currentTask.value = null;
          currentView.value = "upload";
          setHashTaskId("");
        }
        if (lastViewedTaskId.value === taskId) {
          lastViewedTaskId.value = "";
          localStorage.removeItem(STORAGE_KEYS.lastTaskId);
        }
        await refreshTasks(false);
      } catch (error) {
        setAlert(uploadMessage, "error", t("deleteTaskFailedTitle"), error.message);
      } finally {
        deletingTaskId.value = "";
      }
    }

    async function cancelTask(task) {
      const taskId = task?.id || currentTask.value?.id || "";
      if (!taskId || cancellingTaskId.value) return;
      if (!["pending", "running", "cancelling"].includes(safeLower(task?.status || currentTask.value?.status || ""))) return;
      if (!window.confirm(t("terminateTaskConfirm"))) return;

      cancellingTaskId.value = taskId;
      try {
        const response = await fetch(`/api/tasks/${taskId}/cancel`, { method: "POST" });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(payload.error || `HTTP ${response.status}`);
        }
        if (currentTask.value?.id === taskId) {
          currentTask.value = decorateTask(payload);
          ensureRealtime(taskId);
        }
        await refreshTasks(false);
      } catch (error) {
        setAlert(uploadMessage, "error", t("terminateTaskFailedTitle"), error.message);
      } finally {
        cancellingTaskId.value = "";
      }
    }

    async function resumeTask(task) {
      const taskId = task?.id || "";
      const status = safeLower(task?.status || "");
      if (!taskId || resumingTaskId.value) return;
      if (!["failed", "cancelled"].includes(status)) return;

      clearAlert(uploadMessage);
      resumingTaskId.value = taskId;
      try {
        const response = await fetch(`/api/tasks/${taskId}/resume`, { method: "POST" });
        const payload = await response.json().catch(() => ({}));
        if (response.status === 409) {
          await refreshTasks(false);
          setAlert(
            uploadMessage,
            "warn",
            localeText("无法继续检测", "Unable to Resume"),
            payload.error || t("singleTaskLimitBody")
          );
          return;
        }
        if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);

        setAlert(
          uploadMessage,
          "success",
          localeText("任务已继续", "Task Resumed"),
          localeText("将从上次进度继续检测。", "The review will continue from the previous progress.")
        );
        await refreshTasks(false);
        await refreshTask(taskId, { manageRealtime: true, syncList: true });
      } catch (error) {
        setAlert(
          uploadMessage,
          "error",
          localeText("继续检测失败", "Resume Failed"),
          error.message
        );
      } finally {
        resumingTaskId.value = "";
      }
    }

    async function resumeLastTask() {
      if (lastViewedTaskId.value) await openTask(lastViewedTaskId.value);
    }

    function goHome() {
      stopRealtime();
      closeDownloadDialog();
      currentTask.value = null;
      currentView.value = "upload";
      setHashTaskId("");
    }

    function downloadReport() {
      if (!currentTask.value?.id || !canExportReport.value) return;
      const link = document.createElement("a");
      link.href = `/api/tasks/${currentTask.value.id}/report/export`;
      link.rel = "noopener";
      document.body.appendChild(link);
      link.click();
      link.remove();
    }

    async function downloadAnnotatedPdf() {
      if (!currentTask.value?.id || !canExportReport.value || isDownloadingAnnotatedPdf.value) return;

      isDownloadingAnnotatedPdf.value = true;
      showDownloadDialog("info", t("downloadPreparingTitle"), t("downloadPreparingBody"));

      try {
        const response = await fetch(`/api/tasks/${currentTask.value.id}/report/export-annotated-pdf`);
        if (!response.ok) {
          throw new Error(await readErrorMessage(response));
        }

        const blob = await response.blob();
        const fallbackName = `${(currentTask.value?.pdf_name || currentTask.value?.id || "draftclaw").replace(/\.pdf$/i, "")}_draftclaw_annotated.pdf`;
        const filename = parseDownloadFilename(response.headers.get("content-disposition"), fallbackName);
        triggerBrowserDownload(blob, filename);

        showDownloadDialog("success", t("downloadReadyTitle"), t("downloadReadyBody"));
        downloadDialogTimer.value = window.setTimeout(() => {
          closeDownloadDialog();
        }, 1400);
      } catch (error) {
        showDownloadDialog("error", t("downloadFailedTitle"), error.message || t("downloadFailedTitle"));
      } finally {
        isDownloadingAnnotatedPdf.value = false;
      }
    }

    async function refreshCurrentTask() {
      if (!currentTask.value?.id) return;
      await refreshTask(currentTask.value.id, { manageRealtime: true, syncList: true });
    }

    function toggleLang() {
      uiLang.value = uiLang.value === "zh" ? "en" : "zh";
      localStorage.setItem(STORAGE_KEYS.uiLang, uiLang.value);
    }

    function openFilePicker() {
      if (hasActiveTask.value) return;
      fileInputRef.value?.click();
    }

    function onDragOver() {
      if (hasActiveTask.value) return;
      isDragover.value = true;
    }

    function onDragLeave() {
      isDragover.value = false;
    }

    function handleFileSelect(event) {
      const [file] = event.target.files || [];
      if (file) selectedFile.value = file;
    }

    function handleDrop(event) {
      isDragover.value = false;
      if (hasActiveTask.value) return;
      const [file] = event.dataTransfer?.files || [];
      if (file) selectedFile.value = file;
    }

    async function selectIssue(issue) {
      selectedIssueId.value = issue.client_id;
    }

    function handleHashChange() {
      const hashTaskId = getHashTaskId();
      if (!hashTaskId) {
        if (currentView.value === "review") {
          stopRealtime();
          currentTask.value = null;
          currentView.value = "upload";
        }
        return;
      }
      if (currentTask.value?.id === hashTaskId) return;
      openTask(hashTaskId);
    }

    function handleWindowKeydown(event) {
      if (event.key === "Escape" && showSettingsPanel.value) {
        closeSettingsPanel();
      }
    }

    watch(reportLanguage, (value) => {
      localStorage.setItem(STORAGE_KEYS.reportLang, value);
    });

    watch(showSettingsPanel, (visible) => {
      document.body.style.overflow = visible ? "hidden" : "";
    });

    watch([selectedType, issueSearch], () => {
      ensureSelectedIssue();
    });

    watch(activeTaskPageCount, (count) => {
      activeTaskPage.value = clamp(activeTaskPage.value, 1, count);
    });

    watch(completedTaskPageCount, (count) => {
      completedTaskPage.value = clamp(completedTaskPage.value, 1, count);
    });

    watch(
      () => selectedIssue.value?.client_id,
      async (value, oldValue) => {
        if (!value) return;
        const issue = visibleIssues.value.find((item) => item.client_id === value);
        if (!issue) return;
        syncPdfFocusState(issue, true);
        const targetPage = issuePage(issue);
        if (targetPage && !pdfReady.value && targetPage !== currentPageNum.value) {
          pageChangeSource.value = "program";
          currentPageNum.value = targetPage;
        }
        if (!pdfReady.value) return;
        await nextTick();
        focusIssueBBox(issue, oldValue ? "smooth" : "auto");
      }
    );

    watch(currentPageNum, (value) => {
      if (!pageCount.value) return;
      const clamped = clamp(Number(value || 1), 1, pageCount.value);
      if (clamped !== value) {
        currentPageNum.value = clamped;
        return;
      }
      if (pageChangeSource.value === "scroll") {
        pageChangeSource.value = "program";
        return;
      }
      if (!scrollSyncLock.value) {
        scrollToPage(clamped);
      }
    });

    watch(zoom, async () => {
      if (!pdfReady.value) return;
      await nextTick();
      if (selectedIssue.value) focusIssueBBox(selectedIssue.value, "auto");
      else scrollToPage(currentPageNum.value, "auto");
    });

    watch(latestLogId, async (value, oldValue) => {
      if (!value || !showProcessPanel.value) return;
      await nextTick();
      scrollProcessToBottom(oldValue ? "smooth" : "auto");
    });

    watch(showProcessPanel, async (visible) => {
      if (!visible) return;
      await nextTick();
      scrollProcessToBottom("auto");
    });

    onMounted(async () => {
      window.addEventListener("hashchange", handleHashChange);
      window.addEventListener("keydown", handleWindowKeydown);
      window.addEventListener("resize", updateLayoutMode);
      await fetchConfig();
      await refreshTasks(true);
      const hashTaskId = getHashTaskId();
      if (hashTaskId) await openTask(hashTaskId);
      taskListTimer.value = window.setInterval(() => {
        refreshTasks(false);
      }, 5000);
    });

    onBeforeUnmount(() => {
      stopRealtime();
      if (taskListTimer.value) window.clearInterval(taskListTimer.value);
      clearDownloadDialogTimer();
      window.removeEventListener("hashchange", handleHashChange);
      window.removeEventListener("keydown", handleWindowKeydown);
      window.removeEventListener("resize", updateLayoutMode);
      document.body.style.overflow = "";
      stopResize();
    });

    return {
      uiLang,
      reportLanguage,
      currentView,
      mode,
      selectedFile,
      isDragover,
      isUploading,
      isSavingConfig,
      deletingTaskId,
      cancellingTaskId,
      resumingTaskId,
      tasksLoading,
      activeTaskPage,
      completedTaskPage,
      currentTask,
      lastViewedTaskId,
      fileInputRef,
      workspaceRef,
      pdfScrollRef,
      processScrollRef,
      pdfLoading,
      pdfError,
      pageCount,
      currentPageNum,
      zoom,
      pdfPages,
      pdfFocusKind,
      showSettingsPanel,
      showProcessPanel,
      isDownloadingAnnotatedPdf,
      resizeState,
      selectedType,
      issueSearch,
      processInstructionDraft,
      configForm,
      uploadMessage,
      configMessage,
      downloadDialog,
      modeCards,
      settingsPanelStatusLabel,
      settingsSummary,
      activeTasks,
      pagedActiveTasks,
      activeTaskPageCount,
      completedTasks,
      pagedCompletedTasks,
      completedTaskPageCount,
      hasActiveTask,
      missingRequirements,
      cannotStartReview,
      visibleIssues,
      rejectedIssueCount,
      issueTypes,
      filteredIssues,
      selectedIssue,
      latestLogId,
      progressPercent,
      progressPhaseLabel,
      isTaskActive,
      canCancelCurrentTask,
      canExportReport,
      pdfReady,
      workflowStages,
      processItems,
      canSendProcessInstruction,
      t,
      alertClass,
      taskStatusLabel,
      issueCountLabel,
      changeTaskPage,
      severityLabel,
      severityClass,
      decisionLabel,
      decisionClass,
      bboxLabel,
      issuePage,
      issueLocationText,
      issueEvidenceText,
      issueReasoningText,
      focusTargetCount,
      focusTargetPosition,
      focusTargetPositionByKind,
      setPdfFocusKind,
      cyclePdfFocus,
      stepPdfFocus,
      localeText,
      formatDateTime,
      saveConfig,
      openSettingsPanel,
      closeSettingsPanel,
      startReview,
      openTask,
      cancelTask,
      resumeTask,
      deleteCompletedTask,
      resumeLastTask,
      goHome,
      downloadReport,
      downloadAnnotatedPdf,
      refreshCurrentTask,
      toggleLang,
      openFilePicker,
      onDragOver,
      onDragLeave,
      handleFileSelect,
      handleDrop,
      prevPage,
      nextPage,
      zoomIn,
      zoomOut,
      setPageShellRef,
      handlePdfScroll,
      pageBoxes,
      boxStyle,
      pageShellStyle,
      paneStyle,
      toggleProcessPanel,
      closeDownloadDialog,
      isSectionOpen,
      toggleSection,
      sendProcessInstruction,
      startResize,
      selectIssue,
    };
  },
}).mount("#app");
