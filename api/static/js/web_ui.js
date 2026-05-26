const BASE = "";

// 全局状态
let currentBrowserPath = "";
let currentParentPath = null;
let fileBrowserMode = "file";
let selectedFile = null;
let selectedDirs = [];
let selectionCallback = null;

// ===== Tab switching =====
document.querySelectorAll(".nav-item").forEach(item => {
  item.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    item.classList.add("active");
    document.getElementById("tab-" + item.dataset.tab).classList.add("active");
    if (item.dataset.tab === "config") loadConfig();
  });
});

function hlUpdateFileDisplay() {
  const section = document.getElementById("hl-scanned-files-section");
  const listEl = document.getElementById("hl-scanned-files-list");
  if (!hlSelectedFiles.length) { section.style.display = "none"; return; }
  section.style.display = "block";

  const groups = {};
  for (const file of hlSelectedFiles) {
    const dir = file.sourceDir || file.path.substring(0, file.path.lastIndexOf("/")) || "/";
    if (!groups[dir]) groups[dir] = { name: dir.split("/").pop() || dir, files: [] };
    groups[dir].files.push(file);
  }
  const groupNames = Object.keys(groups).sort();
  for (const gid of groupNames) {
    if (!(gid in _hlGroupCollapseState)) _hlGroupCollapseState[gid] = true;
  }
  for (const gid of Object.keys(_hlGroupCollapseState)) {
    if (!groups[gid]) delete _hlGroupCollapseState[gid];
  }
  const allCollapsed = groupNames.every(gid => _hlGroupCollapseState[gid]);
  const allExpanded = groupNames.every(gid => !_hlGroupCollapseState[gid]);

  let html = `<div style="display:flex;gap:8px;padding:6px 12px;border-bottom:1px solid var(--border);">
    <button class="btn btn-outline" style="font-size:12px;padding:4px 10px" onclick="hlCollapseAll()"${allCollapsed ? ' disabled' : ''}>全部收起</button>
    <button class="btn btn-outline" style="font-size:12px;padding:4px 10px" onclick="hlExpandAll()"${allExpanded ? ' disabled' : ''}>全部展开</button>
    <button class="btn btn-outline" style="font-size:12px;padding:4px 10px;color:#e74c3c;border-color:#e74c3c;margin-left:auto" onclick="hlClearFiles()">✕ 清空</button>
  </div>`;
  for (const gid of groupNames) {
    const group = groups[gid];
    const count = group.files.length;
    const isCollapsed = _hlGroupCollapseState[gid];
    html += `<div class="group-header" onclick="hlToggleGroup('${encodeURIComponent(gid)}')">
      <span class="group-toggle${isCollapsed ? ' collapsed' : ''}">▼</span>
      📁 ${escapeHtml(group.name)} <span style="color:var(--text-light);font-size:12px">${count} 个文件</span>
    </div>`;
    html += `<div class="group-files${isCollapsed ? ' collapsed' : ''}" style="max-height:${isCollapsed ? '0' : (count * 42 + 'px')}">`;
    html += group.files.map(file => `
      <div class="scan-item">
        <span>📄</span><span style="flex:1">${escapeHtml(file.name)}</span><span style="color:var(--text-light);font-size:12px">${formatFileSize(file.size)}</span>
      </div>
    `).join("");
    html += `</div>`;
  }
  listEl.innerHTML = html;
}

function hlToggleGroup(encodedGid) {
  const gid = decodeURIComponent(encodedGid);
  _hlGroupCollapseState[gid] = !_hlGroupCollapseState[gid];
  hlUpdateFileDisplay();
}

function hlCollapseAll() {
  for (const gid in _hlGroupCollapseState) _hlGroupCollapseState[gid] = true;
  hlUpdateFileDisplay();
}

function hlExpandAll() {
  for (const gid in _hlGroupCollapseState) _hlGroupCollapseState[gid] = false;
  hlUpdateFileDisplay();
}

function hlClearFiles() {
  hlSelectedFiles = [];
  _hlGroupCollapseState = {};
  window._hlResultGroupState = {};
  _hlLastResultData = null;
  document.getElementById("hl-file-count").textContent = "未选择";
  document.getElementById("hl-scanned-files-section").style.display = "none";
  document.getElementById("hl-result").style.display = "none";
}

async function api(path, opts = {}) {
  const url = BASE + path;
  const headers = { "Content-Type": "application/json", ...opts.headers };
  const savedKey = localStorage.getItem("authKey");
  if (savedKey) {
    headers["Authorization"] = `Bearer ${savedKey}`;
  }
  const res = await fetch(url, { headers, ...opts });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
  return data;
}

function show(el, data, type = "info") {
  el.style.display = "block";
  el.className = "result-box " + type;
  if (typeof data === "string") {
    el.textContent = data;
  } else {
    el.textContent = JSON.stringify(data, null, 2);
  }
}
function hide(el) { el.style.display = "none"; }

function formatFileSize(bytes) {
  if (!bytes) return "-";
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(2)} ${sizes[i]}`;
}

function escapeHtml(s) {
  if (!s) return "";
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}

// ===== File Browser =====
async function browseDirectory(path = null) {
  try {
    const query = path ? `?path=${encodeURIComponent(path)}` : "";
    const data = await api(`/api/v1/filesystem/browse${query}`);
    currentBrowserPath = data.current_path;
    currentParentPath = data.parent_path;
    document.getElementById("currentPath").value = data.current_path;
    document.getElementById("btnParentDir").style.display = data.parent_path ? "inline-flex" : "none";

    const fileList = document.getElementById("fileList");
    fileList.innerHTML = "";

    if (fileBrowserMode === "directory") {
      const currentDirSelected = selectedDirs.some(d => d.startsWith(data.current_path + "/") || d === data.current_path);
      if (!currentDirSelected) {
        selectedDirs = selectedDirs.filter(d => !d.startsWith(data.current_path));
      }
    }

    data.items.forEach(item => {
      const li = document.createElement("li");
      li.className = "file-item";
      const isSelected = selectedFile && selectedFile.path === item.path;
      const isDirSelected = fileBrowserMode === "directory" && selectedDirs.includes(item.path);
      if (isSelected || isDirSelected) li.classList.add("selected");

      if (item.is_dir && fileBrowserMode === "directory") {
        li.innerHTML = `
          <input type="checkbox" style="width:16px;height:16px;cursor:pointer;flex-shrink:0" ${isDirSelected ? "checked" : ""}>
          <span class="file-icon">📁</span>
          <span class="file-name">${item.name}</span>
          <button class="btn btn-outline" style="font-size:12px;padding:2px 8px;flex-shrink:0">进入</button>
        `;
        const cb = li.querySelector("input[type=checkbox]");
        const enterBtn = li.querySelector("button");
        cb.addEventListener("click", (e) => e.stopPropagation());
        enterBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          browseDirectory(item.path);
        });
        li.addEventListener("click", () => {
          cb.checked = !cb.checked;
          if (cb.checked) {
            if (!selectedDirs.includes(item.path)) selectedDirs.push(item.path);
          } else {
            selectedDirs = selectedDirs.filter(d => d !== item.path);
          }
          li.classList.toggle("selected", cb.checked);
          updateSelectedDirsCount();
        });
      } else {
        li.innerHTML = `
          <span class="file-icon">${item.is_dir ? "📁" : "📄"}</span>
          <span class="file-name">${item.name}</span>
          <span class="file-size">${item.is_dir ? "" : formatFileSize(item.size)}</span>
        `;
        li.addEventListener("click", () => handleFileItemClick(item));
      }
      fileList.appendChild(li);
    });
  } catch (e) {
    console.error("浏览目录失败:", e);
    alert(`浏览目录失败: ${e.message}`);
  }
}

function handleFileItemClick(item) {
  if (item.is_dir) {
    browseDirectory(item.path);
    selectedFile = null;
  } else {
    if (fileBrowserMode === "file") {
      selectedFile = item;
      browseDirectory(currentBrowserPath);
    }
  }
}

function goToParent() {
  browseDirectory(currentParentPath !== null ? currentParentPath : null);
}

function openFileBrowser(mode, title, callback, startPath) {
  fileBrowserMode = mode;
  document.getElementById("fileBrowserTitle").textContent = title;
  document.getElementById("fileBrowserModal").classList.add("active");
  selectedFile = null;
  selectedDirs = [];
  updateSelectedDirsCount();
  browseDirectory(startPath || null);
  selectionCallback = callback;
}

function closeFileBrowser() {
  document.getElementById("fileBrowserModal").classList.remove("active");
  selectionCallback = null;
  selectedFile = null;
  selectedDirs = [];
}

function updateSelectedDirsCount() {
  const el = document.getElementById("selectedDirsCount");
  if (fileBrowserMode === "directory" && selectedDirs.length > 0) {
    el.textContent = `已选择 ${selectedDirs.length} 个目录`;
  } else {
    el.textContent = "";
  }
}

function confirmSelection() {
  if (fileBrowserMode === "file" && selectedFile) {
    if (selectionCallback) selectionCallback(selectedFile);
    closeFileBrowser();
  } else if (fileBrowserMode === "directory" && selectedDirs.length > 0) {
    if (selectionCallback) {
      selectionCallback(selectedDirs);
      closeFileBrowser();
    } else {
      scanMultipleDirectories(selectedDirs);
      closeFileBrowser();
    }
  } else if (fileBrowserMode === "directory") {
    alert("请先勾选要扫描的目录");
  } else if (fileBrowserMode === "folder" && currentBrowserPath) {
    if (selectionCallback) {
      selectionCallback(currentBrowserPath);
    } else {
      scanMultipleDirectories([currentBrowserPath]);
    }
    closeFileBrowser();
  } else {
    alert("请选择文件");
  }
}

// ===== Health & Status =====
async function checkHealth() {
  try {
    await api("/health");
    document.getElementById("statusText").textContent = "在线";
    document.getElementById("statusDot").className = "status-dot online";
  } catch {
    document.getElementById("statusText").textContent = "离线";
    document.getElementById("statusDot").className = "status-dot offline";
  }
}

async function loadRoot() {
  try {
    const data = await api("/");
    const badge = document.getElementById("modeBadge");
    badge.textContent = data.mode || "local";
    if (data.mode === "remote") {
      badge.className = "mode-badge remote";
      document.getElementById("scrapeModeWarning").style.display = "block";
    }
    return data;
  } catch { return {}; }
}

async function loadAbout() {
  const container = document.getElementById("aboutContainer");
  try {
    const data = await api("/api/v1/info");
    const a = data.app || {};
    const c = data.config || {};
    const badge = (v) => v ? '<span class="badge-on">已启用</span>' : '<span class="badge-off">未配置</span>';
    container.innerHTML = `
      <div class="about-grid">
        <div class="about-card">
          <h3>📦 应用信息</h3>
          <div class="about-row"><span class="about-label">名称</span><span class="about-value">${escapeHtml(a.name)}</span></div>
          <div class="about-row"><span class="about-label">版本</span><span class="about-value">${escapeHtml(a.version)}</span></div>
          <div class="about-row"><span class="about-label">模式</span><span class="about-value">${escapeHtml(a.mode)}</span></div>
        </div>
        <div class="about-card">
          <h3>🖥 系统信息</h3>
          <div class="about-row"><span class="about-label">Python</span><span class="about-value">${escapeHtml(a.python)}</span></div>
          <div class="about-row"><span class="about-label">平台</span><span class="about-value">${escapeHtml(a.platform)}</span></div>
        </div>
        <div class="about-card">
          <h3>🔑 密钥配置</h3>
          <div class="about-row"><span class="about-label">TMDb API</span><span class="about-value">${badge(c.tmdb_api_key)}</span></div>
          <div class="about-row"><span class="about-label">BGM API</span><span class="about-value">${badge(c.bgm_api_key)}</span></div>
          <div class="about-row"><span class="about-label">AI API</span><span class="about-value">${badge(c.ai_api_key)}</span></div>
          <div class="about-row"><span class="about-label">AI 模型</span><span class="about-value">${escapeHtml(c.ai_model)}</span></div>
          <div class="about-row"><span class="about-label">Header 认证</span><span class="about-value">${badge(c.auth_key)}</span></div>
          <div class="about-row"><span class="about-label">Web 登录</span><span class="about-value">${badge(c.web_auth)}</span></div>
        </div>
        <div class="about-card">
          <h3>📂 存储配置</h3>
          <div class="about-row"><span class="about-label">媒体库目录</span><span class="about-value" style="font-size:12px;word-break:break-all;max-width:200px;text-align:right">${escapeHtml(c.media_library)}</span></div>
        </div>
      </div>
    `;
  } catch (e) {
    container.innerHTML = `<div class="error">加载失败: ${escapeHtml(e.message)}</div>`;
  }
}

// ===== Auto Write Config =====
function loadAutoWriteConfig() {
  try {
    const enabled = localStorage.getItem("autoWriteEnabled") !== "false";
    const writeNfo = localStorage.getItem("autoWriteNfo") !== "false";
    const writePoster = localStorage.getItem("autoWritePoster") !== "false";
    const writeFanart = localStorage.getItem("autoWriteFanart") !== "false";
    const writeActors = localStorage.getItem("autoWriteActors") === "true";
    document.getElementById("autoWriteToggle").checked = enabled;
    document.getElementById("autoWriteNfo").checked = writeNfo;
    document.getElementById("autoWritePoster").checked = writePoster;
    document.getElementById("autoWriteFanart").checked = writeFanart;
    document.getElementById("autoWriteActors").checked = writeActors;
    document.getElementById("autoWriteOptions").style.display = enabled ? "block" : "none";
  } catch (e) { console.error("加载配置失败:", e); }
}

function saveAutoWriteConfig() {
  try {
    localStorage.setItem("autoWriteEnabled", document.getElementById("autoWriteToggle").checked);
    localStorage.setItem("autoWriteNfo", document.getElementById("autoWriteNfo").checked);
    localStorage.setItem("autoWritePoster", document.getElementById("autoWritePoster").checked);
    localStorage.setItem("autoWriteFanart", document.getElementById("autoWriteFanart").checked);
    localStorage.setItem("autoWriteActors", document.getElementById("autoWriteActors").checked);
  } catch (e) { console.error("保存配置失败:", e); }
}

function onAutoWriteToggle() {
  const enabled = document.getElementById("autoWriteToggle").checked;
  document.getElementById("autoWriteOptions").style.display = enabled ? "block" : "none";
  saveAutoWriteConfig();
}

function getScrapeOptions() {
  const enabled = document.getElementById("autoWriteToggle").checked;
  return {
    download_images: enabled && document.getElementById("autoWritePoster").checked,
    write_nfo: enabled && document.getElementById("autoWriteNfo").checked,
    download_fanart: enabled && document.getElementById("autoWriteFanart").checked,
    download_actor_images: enabled && document.getElementById("autoWriteActors").checked,
  };
}

// ===== Failure Log =====
let lastFailureLogs = [];

function viewFailureLog() {
  const body = document.getElementById("failureLogBody");
  if (lastFailureLogs.length === 0) {
    body.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-light)">没有失败记录</div>';
  } else {
    body.innerHTML = lastFailureLogs.map(item => `
      <div class="failure-log-item">
        <div class="failure-log-filename">${escapeHtml(item.name || item.path || "未知")}</div>
        <div class="failure-log-detail">${escapeHtml(item.detail || item.status || "未知错误")}</div>
      </div>
    `).join("");
  }
  document.getElementById("failureLogModal").classList.add("active");
}

function closeFailureLogModal() {
  document.getElementById("failureLogModal").classList.remove("active");
}

function downloadFailureLog() {
  if (!lastFailureLogs.length) { alert("没有失败记录可下载"); return; }
  const lines = lastFailureLogs.map(item => {
    const name = item.name || item.path || "未知";
    const detail = item.detail || item.status || "未知错误";
    return `[失败] ${name}\n  原因: ${detail}\n`;
  });
  const content = `失败日志 - ${new Date().toLocaleString("zh-CN")}\n${"=".repeat(50)}\n\n${lines.join("\n")}`;
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `scrape-failures-${new Date().toISOString().slice(0, 10)}.log`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function maskKey(key) {
  if (!key || key.length < 8) return key;
  return key.slice(0, 4) + "*".repeat(key.length - 8) + key.slice(-4);
}

// ===== Completion Modal =====
let _completionFailedItems = [];

function showCompletionModal(title, total, success, failed, failedItems) {
  document.getElementById("completionTitle").textContent = title;
  document.getElementById("completionTotal").textContent = total;
  document.getElementById("completionSuccess").textContent = success;
  document.getElementById("completionFailed").textContent = failed;
  const summaryEl = document.getElementById("completionSummary");
  if (failed === 0) {
    summaryEl.textContent = "✅";
    document.getElementById("completionDetails").textContent = "全部操作成功完成！";
  } else if (success === 0) {
    summaryEl.textContent = "❌";
    document.getElementById("completionDetails").textContent = "所有操作均失败，请查看失败日志了解详情";
  } else {
    summaryEl.textContent = "⚠️";
    document.getElementById("completionDetails").textContent = `部分操作失败 (${failed}/${total})，请查看失败日志了解详情`;
  }
  _completionFailedItems = failedItems || [];
  lastFailureLogs = failedItems || [];
  document.getElementById("completionFailureBtnArea").style.display = failed > 0 ? "block" : "none";
  document.getElementById("completionModal").classList.add("active");
}

function closeCompletionModal() {
  document.getElementById("completionModal").classList.remove("active");
}

// ===== Scrape batch scan helpers =====
let scannedScrapeFiles = [];
let _groupCollapseState = {};

async function scanMultipleDirectories(dirList) {
  const targetEl = document.getElementById("sc-batch-input");
  const originalContent = targetEl.innerHTML;
  const allFiles = [];
  let scannedCount = 0;

  for (const dir of dirList) {
    targetEl.innerHTML = `
      <div style="padding:12px;background:#f0f4f8;border-radius:8px">
        <div style="font-weight:600;color:#2c3e50;margin-bottom:8px">正在扫描 (${scannedCount + 1}/${dirList.length})</div>
        <div id="scanProgressInfo" style="font-size:13px;color:#7f8c9b"></div>
      </div>
    `;
    const progressEl = document.getElementById("scanProgressInfo");
    try {
      const response = await fetch(`/api/v1/filesystem/scan/stream?path=${encodeURIComponent(dir)}&recursive=true`, { method: "POST", headers: { "Authorization": "Bearer " + (localStorage.getItem("authKey") || "") } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const data = JSON.parse(line);
            if (data.type === "complete") {
              allFiles.push(...data.media_files.map(f => ({ path: f.path, name: f.name, size: f.size, groupId: f.group_id, sourceDir: dir })));
              if (progressEl) progressEl.textContent = `完成！${dir.split("/").pop()} 中找到 ${data.total_count} 个文件`;
            } else if (data.type === "error") {
              throw new Error(data.message);
            }
          } catch (e) {
            if (e.message !== "Unexpected end of JSON input") throw e;
          }
        }
      }
    } catch (e) {
      console.error(`扫描目录失败: ${dir}`, e);
      if (progressEl) progressEl.textContent = `扫描失败: ${e.message}`;
    }
    scannedCount++;
  }

  setTimeout(() => {
    targetEl.innerHTML = originalContent;
    const existingPaths = new Set(scannedScrapeFiles.map(f => f.path));
    for (const f of allFiles) {
      if (!existingPaths.has(f.path)) {
        scannedScrapeFiles.push(f);
        existingPaths.add(f.path);
      }
    }
    updateScannedFilesDisplay();
    if (allFiles.length === 0) alert("所选目录中未找到任何媒体文件");
  }, 300);
}

function toggleGroup(encodedGid) {
  const gid = decodeURIComponent(encodedGid);
  _groupCollapseState[gid] = !_groupCollapseState[gid];
  updateScannedFilesDisplay();
}

function collapseAllGroups() {
  for (const gid in _groupCollapseState) _groupCollapseState[gid] = true;
  updateScannedFilesDisplay();
}

function expandAllGroups() {
  for (const gid in _groupCollapseState) _groupCollapseState[gid] = false;
  updateScannedFilesDisplay();
}

function removeGroup(encodedGid) {
  const gid = decodeURIComponent(encodedGid);
  scannedScrapeFiles = scannedScrapeFiles.filter(f => (f.sourceDir || f.groupId || "__ungrouped__") !== gid);
  delete _groupCollapseState[gid];
  updateScannedFilesDisplay();
}

function updateScannedFilesDisplay() {
  const section = document.getElementById("sc-scanned-files-section");
  const batchInput = document.getElementById("sc-batch-input");
  const listEl = document.getElementById("sc-scanned-files-list");
  const countEl = document.getElementById("sc-scanned-count");
  const clearBtn = document.getElementById("sc-clear-btn");

  if (scannedScrapeFiles.length > 0) {
    section.style.display = "block";
    batchInput.style.display = "none";
    clearBtn.style.display = "inline-flex";
    countEl.textContent = `已选择 ${scannedScrapeFiles.length} 个文件`;

    const groups = {};
    for (const file of scannedScrapeFiles) {
      const gid = file.sourceDir || file.groupId || "__ungrouped__";
      if (!groups[gid]) groups[gid] = { name: gid === "__ungrouped__" ? "其他" : gid.split("/").pop() || gid, files: [] };
      groups[gid].files.push(file);
    }
    const groupNames = Object.keys(groups).sort();
    for (const gid of groupNames) {
      if (!(gid in _groupCollapseState)) _groupCollapseState[gid] = true;
    }
    for (const gid of Object.keys(_groupCollapseState)) {
      if (!groups[gid]) delete _groupCollapseState[gid];
    }
    const allCollapsed = groupNames.every(gid => _groupCollapseState[gid]);
    const allExpanded = groupNames.every(gid => !_groupCollapseState[gid]);

    let html = `<div style="display:flex;gap:8px;padding:6px 12px;border-bottom:1px solid var(--border);">
      <button class="btn btn-outline" style="font-size:12px;padding:4px 10px" onclick="collapseAllGroups()"${allCollapsed ? ' disabled' : ''}>全部收起</button>
      <button class="btn btn-outline" style="font-size:12px;padding:4px 10px" onclick="expandAllGroups()"${allExpanded ? ' disabled' : ''}>全部展开</button>
    </div>`;

    for (const gid of groupNames) {
      const group = groups[gid];
      const count = group.files.length;
      const isCollapsed = _groupCollapseState[gid];
      html += `<div class="group-header">
        <span style="flex:1;display:flex;align-items:center;gap:8px;" onclick="toggleGroup('${encodeURIComponent(gid)}')">
          <span class="group-toggle${isCollapsed ? ' collapsed' : ''}">▼</span>
          📁 ${group.name} <span style="color:var(--text-light);font-size:12px">${count} 个文件</span>
        </span>
        <button class="btn btn-outline" style="font-size:11px;padding:2px 8px;color:#e74c3c;border-color:#e74c3c" onclick="event.stopPropagation();removeGroup('${encodeURIComponent(gid)}')">✕</button>
      </div>`;
      html += `<div class="group-files${isCollapsed ? ' collapsed' : ''}" style="max-height:${isCollapsed ? '0' : (count * 42 + 'px')}">`;
      html += group.files.map(file => `
        <div class="scan-item">
          <span>📄</span><span style="flex:1">${escapeHtml(file.name)}</span><span style="color:var(--text-light);font-size:12px">${formatFileSize(file.size)}</span>
        </div>
      `).join("");
      html += `</div>`;
    }
    listEl.innerHTML = html;
  } else {
    section.style.display = "none";
    batchInput.style.display = "block";
    clearBtn.style.display = "none";
  }
}

// ===== Hardlink Tab =====
let hlSelectedFiles = [];
let _hlAbortController = null;
let _hlBatchResults = [];
let _hlGroupCollapseState = {};

async function hlSelectFolder() {
  openFileBrowser("directory", "选择要扫描的文件夹（可多选）", async (dirs) => {
    const dirList = Array.isArray(dirs) ? dirs : [dirs];
    if (!dirList.length) return;
    const btn = document.querySelector("button[onclick='hlSelectFolder()']");
    if (btn) btn.disabled = true;
    document.getElementById("hl-file-count").innerHTML = `<span class="spinner"></span>正在扫描...`;
    const allFiles = [];
    let scannedCount = 0;
    for (const dir of dirList) {
      document.getElementById("hl-file-count").innerHTML = `<span class="spinner"></span>正在扫描 (${++scannedCount}/${dirList.length}): ${dir.split("/").pop()}`;
      try {
        const response = await fetch(`/api/v1/filesystem/scan/stream?path=${encodeURIComponent(dir)}&recursive=true`, { method: "POST", headers: { "Authorization": "Bearer " + (localStorage.getItem("authKey") || "") } });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";
          for (const line of lines) {
            if (!line.trim()) continue;
            try {
              const data = JSON.parse(line);
              if (data.type === "complete") {
                allFiles.push(...data.media_files.map(f => ({ path: f.path, name: f.name, size: f.size, sourceDir: dir })));
              } else if (data.type === "error") {
                throw new Error(data.message);
              }
            } catch (e) {
              if (e.message !== "Unexpected end of JSON input") throw e;
            }
          }
        }
      } catch (e) {
        console.error(`扫描失败: ${dir}`, e);
      }
    }
    if (btn) btn.disabled = false;
    if (!allFiles.length) { document.getElementById("hl-file-count").textContent = "未找到媒体文件"; return; }
    hlSelectedFiles = allFiles;
    document.getElementById("hl-file-count").textContent = `已选择 ${allFiles.length} 个文件（来自 ${dirList.length} 个目录）`;
    document.getElementById("hl-result").style.display = "none";
    hlUpdateFileDisplay();
  });
}

function hlSelectTargetDir() {
  const target = document.getElementById("hl-target").value.trim();
  openFileBrowser("folder", "选择目标媒体库目录", (dirPath) => {
    const path = Array.isArray(dirPath) ? dirPath[0] : dirPath;
    if (path) document.getElementById("hl-target").value = path;
  }, target || null);
}

function getThresholdBytes() {
  const val = parseFloat(document.getElementById("hl-threshold").value) || 0;
  const unit = document.getElementById("hl-threshold-unit").value;
  const factors = { KB: 1000, MB: 1000000, GB: 1000000000 };
  return Math.round(val * (factors[unit] || 1000000));
}

async function hlPreview() {
  if (!hlSelectedFiles.length) { alert("请先选择文件"); return; }
  const summary = document.getElementById("hl-summary");
  const detail = document.getElementById("hl-result-detail");
  const el = document.getElementById("hl-result");
  el.style.display = "none";
  const previewBtn = document.getElementById("hl-preview-btn");
  if (previewBtn) previewBtn.disabled = true;
  summary.innerHTML = `<div class="loading-row"><span class="spinner"></span>🔍 预览分析中... 共 ${hlSelectedFiles.length} 个文件</div>`;
  const keepOrig = document.getElementById("hl-keep-original").checked;
  try {
    const data = await api("/api/v1/media/organize", {
      method: "POST",
      body: JSON.stringify({
        files: hlSelectedFiles.map(f => ({path: f.path, name: f.name})),
        target_root: document.getElementById("hl-target").value.trim(),
        mode: document.getElementById("hl-mode").value,
        threshold: getThresholdBytes(),
        movie_template: keepOrig ? "{title} ({year})/{original_name}" : (document.getElementById("hl-movie-template").value.trim() || undefined),
        tv_template: keepOrig ? "{title}/Season {season:02d}/{original_name}" : (document.getElementById("hl-tv-template").value.trim() || undefined),
        skip_linked: document.getElementById("hl-skip-linked").checked,
        fallback_to_copy: document.getElementById("hl-fallback-copy").checked,
        dry_run: true,
      }),
    });
    if (previewBtn) previewBtn.disabled = false;
    renderHlResult(data, summary, detail, document.getElementById("hl-mode").value, true, document.getElementById("hl-target").value.trim());
    el.style.display = "block";
  } catch (e) {
    if (previewBtn) previewBtn.disabled = false;
    summary.innerHTML = `<div class="error">请求失败: ${escapeHtml(e.message)}</div>`;
    el.style.display = "block";
  }
}

async function hlExecute() {
  if (!hlSelectedFiles.length) { alert("请先选择文件"); return; }
  const target = document.getElementById("hl-target").value.trim();
  const mode = document.getElementById("hl-mode").value;
  if (!confirm(`确定要 ${mode === "hardlink" ? "硬链接" : mode === "copy" ? "复制" : "移动"} ${hlSelectedFiles.length} 个文件到 ${target} 吗？`)) return;

  const summary = document.getElementById("hl-summary");
  const detail = document.getElementById("hl-result-detail");
  const el = document.getElementById("hl-result");
  el.style.display = "none";
  const execBtn = document.getElementById("hl-execute-btn");
  const previewBtn = document.getElementById("hl-preview-btn");
  if (execBtn) execBtn.disabled = true;
  if (previewBtn) previewBtn.disabled = true;
  summary.innerHTML = `<div class="loading-row"><span class="spinner"></span>⏳ 执行中...</div>`;
  const keepOrig = document.getElementById("hl-keep-original").checked;

  try {
    const data = await api("/api/v1/media/organize", {
      method: "POST",
      body: JSON.stringify({
        files: hlSelectedFiles.map(f => ({path: f.path, name: f.name})),
        target_root: target,
        mode: mode,
        threshold: getThresholdBytes(),
        movie_template: keepOrig ? "{title} ({year})/{original_name}" : (document.getElementById("hl-movie-template").value.trim() || undefined),
        tv_template: keepOrig ? "{title}/Season {season:02d}/{original_name}" : (document.getElementById("hl-tv-template").value.trim() || undefined),
        skip_linked: document.getElementById("hl-skip-linked").checked,
        fallback_to_copy: document.getElementById("hl-fallback-copy").checked,
        dry_run: false,
      }),
    });
    renderHlResult(data, summary, detail, mode, false, target);
    el.style.display = "block";
    const failCount = data.failed || 0;
    const skipCount = data.skipped || 0;
    const successCount = data.success || 0;
    const total = data.total || 0;
    const failedItems = (data.results || [])
      .filter(r => !r.success)
      .map(r => ({ name: r.src_name || r.src, detail: r.error || "未知错误" }));
    showCompletionModal("硬链接完成", total, successCount, failCount + skipCount, failedItems);
  } catch (e) {
    summary.innerHTML = `<div class="error">请求失败: ${escapeHtml(e.message)}</div>`;
    el.style.display = "block";
  } finally {
    if (execBtn) execBtn.disabled = false;
    if (previewBtn) previewBtn.disabled = false;
  }
}

function getModeLabel(mode) {
  return mode === "hardlink" ? "🔗硬链接" : mode === "copy" ? "📋复制" : mode === "move" ? "📦移动" : mode === "preview" ? "预览" : mode === "already_exists" ? "⏭已存在" : mode === "linked_skipped" ? "⏭已跳过" : mode || "";
}

function renderHlResult(data, summaryEl, detailEl, mode, isPreview, targetRoot) {
  const success = data.success || 0;
  const failed = data.failed || 0;
  const skipped = data.skipped || 0;
  const total = data.total || 0;
  const modeLabel = isPreview ? "🔍 预览模式" : "▶ 执行模式 - " + getModeLabel(mode);
  let summaryHtml = `
    <div style="display:flex;gap:24px;flex-wrap:wrap">
      <div><strong>${modeLabel}</strong></div>
      <div><strong>总计:</strong> ${total}</div>
      <div style="color:#27ae60"><strong>✅ 成功:</strong> ${success}</div>
      <div style="color:#e67e22"><strong>⏭ 跳过:</strong> ${skipped}</div>
      <div style="color:#e74c3c"><strong>❌ 失败:</strong> ${failed}</div>
    </div>
  `;
  if (data.token_usage) {
    const tu = data.token_usage;
    summaryHtml += `
      <div style="display:flex;gap:24px;flex-wrap:wrap;margin-top:8px;padding-top:8px;border-top:1px solid var(--border);color:#8e44ad;font-size:12px">
        <div>🤖 AI 调用 ${tu.calls} 次</div>
        <div>Token: 输入 ${tu.prompt_tokens} · 输出 ${tu.completion_tokens} · 总计 ${tu.total_tokens}</div>
        <div>费用: ~¥${tu.cost_cache_miss.toFixed(4)}（缓存未命中）/ ¥${tu.cost_cache_hit.toFixed(4)}（缓存命中）</div>
      </div>`;
  }
  summaryEl.innerHTML = summaryHtml;
  if (!data.results || !data.results.length) {
    detailEl.innerHTML = '<div style="padding:16px;color:var(--text-light)">无结果</div>';
    return;
  }
  const prefix = targetRoot ? targetRoot.replace(/\/+$/, "") + "/" : "";
  const groups = {};
  for (const r of data.results) {
    const key = r.title || "其他";
    if (!groups[key]) groups[key] = { title: key, files: [] };
    groups[key].files.push(r);
  }
  const groupNames = Object.keys(groups).sort();
  if (!window._hlResultGroupState) window._hlResultGroupState = {};
  for (const gid of groupNames) {
    if (!(gid in window._hlResultGroupState)) window._hlResultGroupState[gid] = false;
  }
  const allCollapsed = groupNames.every(gid => window._hlResultGroupState[gid]);
  const allExpanded = groupNames.every(gid => !window._hlResultGroupState[gid]);
  let html = `<div style="display:flex;gap:8px;padding:6px 12px;border-bottom:1px solid var(--border);">
    <button class="btn btn-outline" style="font-size:12px;padding:4px 10px" onclick="hlResultCollapseAll()"${allCollapsed ? ' disabled' : ''}>全部收起</button>
    <button class="btn btn-outline" style="font-size:12px;padding:4px 10px" onclick="hlResultExpandAll()"${allExpanded ? ' disabled' : ''}>全部展开</button>
  </div>`;
  for (const gid of groupNames) {
    const group = groups[gid];
    const count = group.files.length;
    const successCount = group.files.filter(r => r.success).length;
    const isCollapsed = window._hlResultGroupState[gid];
    html += `<div class="hl-result-group-header" onclick="hlResultToggleGroup('${encodeURIComponent(gid)}')">
      <span class="hl-result-group-toggle${isCollapsed ? ' collapsed' : ''}">▼</span>
      📁 ${escapeHtml(group.title)} <span style="color:var(--text-light);font-size:12px">${count} 个文件 · ✅ ${successCount}</span>
    </div>`;
    html += `<div class="group-files${isCollapsed ? ' collapsed' : ''}" style="max-height:${isCollapsed ? '0' : (count * 48 + 'px')}">`;
    for (const r of group.files) {
      const statusIcon = r.success ? (isPreview ? "🔍" : "✅") : "❌";
      const relDst = r.dst && r.dst.startsWith(prefix) ? r.dst.slice(prefix.length) : r.dst;
      const episodeInfo = r.season != null && r.episode != null ? `S${String(r.season).padStart(2,"0")}E${String(r.episode).padStart(2,"0")}` : "";
      html += `<div class="hl-result-item">
        <span class="hl-result-item-src" title="${escapeHtml(r.src_name)}">${episodeInfo ? `<span style="color:var(--primary);font-weight:500;margin-right:4px">${episodeInfo}</span>` : ""}${escapeHtml(r.src_name)}</span>
        <span class="hl-result-item-arrow">→</span>
        <span class="hl-result-item-dst" title="${escapeHtml(r.dst)}">${escapeHtml(relDst || "-")}</span>
        <span class="hl-result-item-status" title="${r.success ? "成功" : escapeHtml(r.error || "失败")}">${statusIcon}</span>
      </div>`;
    }
    html += `</div>`;
  }
  detailEl.innerHTML = html;
  _hlLastResultData = data;
  _hlLastSummaryEl = summaryEl;
  _hlLastDetailEl = detailEl;
  _hlLastMode = mode;
  _hlLastIsPreview = isPreview;
  _hlLastTargetRoot = targetRoot;
}

function hlResultToggleGroup(encodedGid) {
  const gid = decodeURIComponent(encodedGid);
  window._hlResultGroupState[gid] = !window._hlResultGroupState[gid];
  renderHlResultFromCurrent();
}

function hlResultCollapseAll() {
  for (const gid in window._hlResultGroupState) window._hlResultGroupState[gid] = true;
  renderHlResultFromCurrent();
}

function hlResultExpandAll() {
  for (const gid in window._hlResultGroupState) window._hlResultGroupState[gid] = false;
  renderHlResultFromCurrent();
}

let _hlLastResultData = null;
let _hlLastSummaryEl = null;
let _hlLastDetailEl = null;
let _hlLastMode = null;
let _hlLastIsPreview = false;
let _hlLastTargetRoot = null;

function renderHlResultFromCurrent() {
  if (_hlLastResultData) {
    renderHlResult(_hlLastResultData, _hlLastSummaryEl, _hlLastDetailEl, _hlLastMode, _hlLastIsPreview, _hlLastTargetRoot);
  }
}

// ===== Rename Tab =====
let rnSelectedFiles = [];
let _rnGroupCollapseState = {};

function rnOpenFileBrowser() {
  openFileBrowser("file", "选择要重命名的文件", (files) => {
    rnSelectedFiles = Array.isArray(files) ? files : [files];
    updateRnFileDisplay();
    document.getElementById("rn-preview-box").style.display = "none";
    document.getElementById("rn-result").style.display = "none";
  });
}

async function rnSelectFolder() {
  openFileBrowser("folder", "选择文件夹（扫描其中媒体文件）", async (dirs) => {
    const dirList = Array.isArray(dirs) ? dirs : [dirs];
    if (!dirList.length) return;
    document.getElementById("rn-file-count").textContent = "正在扫描...";
    try {
      const response = await fetch(`/api/v1/filesystem/scan/stream?path=${encodeURIComponent(dirList[0])}&recursive=true`, { method: "POST", headers: { "Authorization": "Bearer " + (localStorage.getItem("authKey") || "") } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const allFiles = [];
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const data = JSON.parse(line);
            if (data.type === "complete") {
              allFiles.push(...data.media_files.map(f => ({ path: f.path, name: f.name, size: f.size })));
            } else if (data.type === "error") {
              throw new Error(data.message);
            }
          } catch (e) {
            if (e.message !== "Unexpected end of JSON input") throw e;
          }
        }
      }
      if (!allFiles.length) { document.getElementById("rn-file-count").textContent = "未找到媒体文件"; return; }
      rnSelectedFiles = allFiles;
      updateRnFileDisplay();
      document.getElementById("rn-preview-box").style.display = "none";
      document.getElementById("rn-result").style.display = "none";
    } catch (e) {
      document.getElementById("rn-file-count").textContent = `扫描失败: ${e.message}`;
    }
  });
}

function updateRnFileDisplay() {
  const section = document.getElementById("rn-selected-files-section");
  const listEl = document.getElementById("rn-selected-files-list");
  document.getElementById("rn-file-count").textContent = `已选择 ${rnSelectedFiles.length} 个文件`;
  if (!rnSelectedFiles.length) { section.style.display = "none"; return; }
  section.style.display = "block";

  const groups = {};
  for (const file of rnSelectedFiles) {
    const dir = file.path ? file.path.substring(0, file.path.lastIndexOf("/")) || "/" : "/";
    if (!groups[dir]) groups[dir] = { name: dir.split("/").pop() || dir, files: [] };
    groups[dir].files.push(file);
  }
  const groupNames = Object.keys(groups).sort();
  for (const gid of groupNames) {
    if (!(gid in _rnGroupCollapseState)) _rnGroupCollapseState[gid] = true;
  }
  for (const gid of Object.keys(_rnGroupCollapseState)) {
    if (!groups[gid]) delete _rnGroupCollapseState[gid];
  }
  const allCollapsed = groupNames.every(gid => _rnGroupCollapseState[gid]);
  const allExpanded = groupNames.every(gid => !_rnGroupCollapseState[gid]);

  let html = `<div style="display:flex;gap:8px;padding:6px 12px;border-bottom:1px solid var(--border);">
    <button class="btn btn-outline" style="font-size:12px;padding:4px 10px" onclick="rnCollapseAll()"${allCollapsed ? ' disabled' : ''}>全部收起</button>
    <button class="btn btn-outline" style="font-size:12px;padding:4px 10px" onclick="rnExpandAll()"${allExpanded ? ' disabled' : ''}>全部展开</button>
  </div>`;
  for (const gid of groupNames) {
    const group = groups[gid];
    const count = group.files.length;
    const isCollapsed = _rnGroupCollapseState[gid];
    html += `<div class="group-header" onclick="rnToggleGroup('${encodeURIComponent(gid)}')">
      <span class="group-toggle${isCollapsed ? ' collapsed' : ''}">▼</span>
      📁 ${escapeHtml(group.name)} <span style="color:var(--text-light);font-size:12px">${count} 个文件</span>
    </div>`;
    html += `<div class="group-files${isCollapsed ? ' collapsed' : ''}" style="max-height:${isCollapsed ? '0' : (count * 42 + 'px')}">`;
    html += group.files.map(file => `
      <div class="scan-item">
        <span>📄</span><span style="flex:1">${escapeHtml(file.name)}</span><span style="color:var(--text-light);font-size:12px">${formatFileSize(file.size)}</span>
      </div>
    `).join("");
    html += `</div>`;
  }
  listEl.innerHTML = html;
}

function rnToggleGroup(encodedGid) {
  const gid = decodeURIComponent(encodedGid);
  _rnGroupCollapseState[gid] = !_rnGroupCollapseState[gid];
  updateRnFileDisplay();
}

function rnCollapseAll() {
  for (const gid in _rnGroupCollapseState) _rnGroupCollapseState[gid] = true;
  updateRnFileDisplay();
}

function rnExpandAll() {
  for (const gid in _rnGroupCollapseState) _rnGroupCollapseState[gid] = false;
  updateRnFileDisplay();
}

function rnClearFiles() {
  rnSelectedFiles = [];
  _rnGroupCollapseState = {};
  document.getElementById("rn-file-count").textContent = "未选择";
  document.getElementById("rn-selected-files-section").style.display = "none";
  document.getElementById("rn-preview-box").style.display = "none";
  document.getElementById("rn-result").style.display = "none";
}

async function rnPreview() {
  if (!rnSelectedFiles.length) { alert("请先选择文件"); return; }
  const box = document.getElementById("rn-preview-box");
  box.style.display = "block";
  box.className = "result-box info";
  box.innerHTML = "正在识别...";

  try {
    const data = await api("/api/v1/media/preview-rename", {
      method: "POST",
      body: JSON.stringify({ files: rnSelectedFiles.map(f => ({path: f.path, name: f.name})) }),
    });
    if (data.results && data.results.length) {
      let html = '<div style="font-weight:600;margin-bottom:8px">预览结果</div>';
      data.results.forEach(r => {
        const ok = r.suggested ? "✅" : "❌";
        html += `<div style="padding:6px 0;border-bottom:1px solid #eef0f7">${ok} ${escapeHtml(r.original)} → ${escapeHtml(r.suggested || "无法识别")}</div>`;
      });
      box.innerHTML = html;
      box.className = "result-box success";
    } else {
      box.innerHTML = "无结果";
    }
  } catch (e) {
    box.innerHTML = `识别失败: ${escapeHtml(e.message)}`;
    box.className = "result-box error";
  }
}

async function rnExecute() {
  if (!rnSelectedFiles.length) { alert("请先选择文件"); return; }
  if (!confirm(`确定要重命名 ${rnSelectedFiles.length} 个文件吗？`)) return;

  const summary = document.getElementById("rn-summary");
  const tbody = document.getElementById("rn-result-body");
  const el = document.getElementById("rn-result");
  el.style.display = "none";
  summary.innerHTML = `<div>⏳ 执行中...</div>`;

  try {
    const data = await api("/api/v1/media/rename", {
      method: "POST",
      body: JSON.stringify({
        files: rnSelectedFiles.map(f => ({path: f.path, name: f.name})),
        dry_run: false,
      }),
    });
    const total = data.total || 0;
    const successCount = data.success_count || 0;
    const failedCount = data.failed_count || 0;
    summary.innerHTML = `
      <div style="display:flex;gap:24px;flex-wrap:wrap">
        <div><strong>总计:</strong> ${total}</div>
        <div style="color:#27ae60"><strong>✅ 成功:</strong> ${successCount}</div>
        <div style="color:#e74c3c"><strong>❌ 失败:</strong> ${failedCount}</div>
      </div>
    `;
    if (data.results && data.results.length) {
      tbody.innerHTML = data.results.map(r => {
        const icon = r.success ? "✅" : "❌";
        return `<tr>
          <td style="padding:8px 12px">${escapeHtml(r.original_name || r.original_path)}</td>
          <td style="padding:8px 12px">${escapeHtml(r.new_name || "-")}</td>
          <td style="padding:8px 12px;text-align:center">${icon} ${r.success ? "成功" : escapeHtml(r.error || "失败")}</td>
        </tr>`;
      }).join("");
    }
    el.style.display = "block";
    const failedItems = (data.results || [])
      .filter(r => !r.success)
      .map(r => ({ name: r.original_name || r.original_path, detail: r.error || "未知错误" }));
    showCompletionModal("重命名完成", total, successCount, failedCount, failedItems);
  } catch (e) {
    summary.innerHTML = `<div class="error">请求失败: ${escapeHtml(e.message)}</div>`;
    el.style.display = "block";
  }
}

// ===== Scrape Tab (sub-tabs: batch + manual) =====
let _scAbortController = null;
let _scBatchResults = [];

function switchScrapeSubTab(name) {
  document.querySelectorAll(".sub-tab").forEach(t => t.classList.toggle("active", t.dataset.subtab === name));
  document.querySelectorAll(".sub-tab-content").forEach(c => c.classList.toggle("active", c.id === "subtab-" + name));
}

document.getElementById("sc-select-dir-btn").addEventListener("click", () => {
  openFileBrowser("directory", "选择目录扫描媒体文件", null);
});

document.getElementById("sc-clear-btn").addEventListener("click", () => {
  if (_scAbortController) _scAbortController.abort();
  scannedScrapeFiles = [];
  updateScannedFilesDisplay();
  const resultEl = document.getElementById("sc-batch-result");
  resultEl.style.display = "none";
  resultEl.innerHTML = "";
});

async function scBatchExecute() {
  const el = document.getElementById("sc-batch-result");
  el.style.display = "block";
  el.className = "result-box info";
  el.innerHTML = '<div style="margin-bottom:8px;font-weight:600">正在刮削...</div><div id="scProgress" style="color:#7f8c9b;font-size:13px"></div><div class="progress-bar"><div class="progress-bar-fill" id="scProgressBarFill"></div></div><div id="scTime" style="color:#7f8c9b;font-size:12px"></div><div id="scLogs" style="margin-top:12px;font-size:13px;line-height:1.6;display:none"></div><div id="scActions" style="margin-top:12px;display:none"></div><div id="scTokenUsage" style="margin-top:8px;font-size:12px"></div>';
  document.getElementById("sc-server-log-panel").style.display = "block";
  startServerLog("sc-server-log-container");

  const progressEl = document.getElementById("scProgress");
  const logsEl = document.getElementById("scLogs");
  const timeEl = document.getElementById("scTime");
  const tokenUsageEl = document.getElementById("scTokenUsage");

  document.getElementById("sc-batch-btn").style.display = "none";
  document.getElementById("sc-stop-btn").style.display = "inline-flex";

  _scAbortController = new AbortController();
  const opts = getScrapeOptions();
  const autoWriteEnabled = document.getElementById("autoWriteToggle").checked;
  let successCount = 0, failedCount = 0, completedCount = 0, total = 0;
  let failedItems = [];
  _scBatchResults = [];
  const _startTime = Date.now();
  timeEl.textContent = "⏱ 用时: 0s";
  const _timerInterval = setInterval(() => {
    const sec = Math.round((Date.now() - _startTime) / 1000);
    timeEl.textContent = `⏱ 用时: ${sec < 60 ? sec + "s" : Math.floor(sec / 60) + "m " + (sec % 60) + "s"}`;
  }, 1000);

  try {
    let files;
    if (scannedScrapeFiles.length > 0) {
      files = scannedScrapeFiles.map(f => ({ path: f.path, name: f.name, group_id: f.groupId }));
    } else {
      const input = document.getElementById("sc-batch-textarea").value.trim();
      if (!input) { show(el, "请输入文件列表 JSON", "error"); return; }
      files = JSON.parse(input);
    }
    if (!Array.isArray(files) || files.length === 0) throw new Error("需要非空数组");

    const response = await fetch("/api/v1/media/scrape/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": "Bearer " + (localStorage.getItem("authKey") || "") },
      body: JSON.stringify({
        files,
        source: "tmdb",
        download_images: opts.download_images || opts.download_fanart,
        write_nfo: opts.write_nfo
      }),
      signal: _scAbortController.signal
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const data = JSON.parse(line);
          if (data.type === "progress") {
            progressEl.textContent = data.message;
          } else if (data.type === "result") {
            total = data.total;
            completedCount++;
            _scBatchResults.push(data.data);
            const pct = total > 0 ? Math.round(completedCount / total * 100) : 0;
            progressEl.textContent = `进度: ${completedCount}/${total} (${pct}%)`;
            document.getElementById("scProgressBarFill").style.width = pct + "%";
            if (data.success) { successCount++; } else { failedCount++; failedItems.push({ name: data.data.original_name || data.data.original_path?.split("/").pop() || "未知", path: data.data.original_path || "", status: (data.data.errors || [data.data.status || ""]).join("; "), detail: (data.data.errors || [data.data.status || ""]).join("; ") }); }
          } else if (data.type === "complete") {
            clearInterval(_timerInterval);
            const elapsed = Math.round((Date.now() - _startTime) / 1000);
            const timeStr = elapsed < 60 ? `${elapsed}s` : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`;
            let summary = `✅ 完成！总计: ${total}, 成功: ${successCount}, 失败: ${failedCount} (⏱ ${timeStr})`;
            let completionDetail = "";
            if (!autoWriteEnabled) { summary += " ⚠️ 未开启文件下载"; completionDetail = "⚠️ 自动写入刮削数据开关已关闭，未写入 NFO 和下载图片"; }
            progressEl.textContent = summary;
            logsEl.style.display = "block";

            const seriesGroups = {};
            _scBatchResults.forEach(r => {
              const key = r.recognized_title || "未识别";
              if (!seriesGroups[key]) seriesGroups[key] = [];
              seriesGroups[key].push(r);
            });
            const seriesKeys = Object.keys(seriesGroups).sort();
            seriesKeys.forEach(seriesName => {
              const items = seriesGroups[seriesName];
              const sSuccess = items.filter(i => i.success).length;
              const allGood = sSuccess === items.length;
              const header = document.createElement("div");
              header.className = "manual-log-group-header";
              const toggle = document.createElement("span");
              toggle.className = "group-toggle collapsed";
              toggle.textContent = "▶";
              header.appendChild(toggle);
              header.appendChild(document.createTextNode(`${allGood ? "✅" : "⚠️"} ${escapeHtml(seriesName)}`));
              const count = document.createElement("span");
              count.style.cssText = "color:var(--text-light);font-size:12px;margin-left:auto";
              count.textContent = `${sSuccess}/${items.length}`;
              header.appendChild(count);
              const body = document.createElement("div");
              body.className = "manual-log-group-body collapsed";
              items.forEach(r => {
                const icon = r.success ? "✅" : "❌";
                const fname = r.original_name || (r.original_path || "").split("/").pop() || "未知";
                let detail = "";
                if (r.success) { const nf = (r.nfo_written || []).length; const im = (r.images_downloaded || []).length; detail = ` (${nf} NFO, ${im} 图片)`; if (!autoWriteEnabled) detail = " (未开启文件下载)"; } else { detail = `: ${(r.errors || [r.status]).join("; ")}`; }
                const item = document.createElement("div");
                item.className = "manual-log-item";
                item.textContent = `${icon} ${escapeHtml(fname)}${detail}`;
                body.appendChild(item);
              });
              logsEl.appendChild(header);
              logsEl.appendChild(body);
              header.addEventListener("click", () => { body.classList.toggle("collapsed"); toggle.classList.toggle("collapsed"); });
            });

            const actionsEl = document.getElementById("scActions");
            actionsEl.style.display = "flex";
            actionsEl.style.gap = "8px";
            actionsEl.style.flexWrap = "wrap";
            actionsEl.innerHTML = `<button class="btn btn-outline" onclick="viewBatchLogs()">📋 查看完整日志</button><button class="btn btn-outline" onclick="downloadBatchLogs()">📥 下载日志</button>`;

            if (data.token_usage) {
              const tu = data.token_usage;
              tokenUsageEl.textContent = `🤖 Token: 输入 ${tu.prompt_tokens} · 输出 ${tu.completion_tokens} · 总计 ${tu.total_tokens} (${tu.calls} 次调用) · 约 ¥${tu.cost_cache_miss.toFixed(4)} (缓存未命中) / ¥${tu.cost_cache_hit.toFixed(4)} (缓存命中)`;
              tokenUsageEl.style.color = "#8e44ad";
            }

            el.className = "result-box " + (failedCount === 0 ? "success" : successCount === 0 ? "error" : "warning");
            showCompletionModal("批量刮削完成", total, successCount, failedCount, failedItems);
            if (completionDetail) document.getElementById("completionDetails").textContent = completionDetail;
          }
        } catch (e) {
          if (e.message !== "Unexpected end of JSON input") console.error("解析响应失败:", e);
        }
      }
    }
  } catch (e) {
    if (e.name === "AbortError") {
      clearInterval(_timerInterval);
      progressEl.textContent = `已停止 (已完成 ${completedCount} 个)`;
      el.className = "result-box warning";
    } else {
      show(el, `刮削失败: ${e.message}`, "error");
    }
  } finally {
    _scAbortController = null;
    document.getElementById("sc-batch-btn").style.display = "inline-flex";
    document.getElementById("sc-stop-btn").style.display = "none";
    stopServerLog();
  }
}

function scBatchStop() {
  if (_scAbortController) _scAbortController.abort();
}

function viewBatchLogs() {
  if (!_scBatchResults.length) return;
  const body = document.getElementById("failureLogBody");
  body.innerHTML = _scBatchResults.map(r => {
    const icon = r.success ? "✅" : "❌";
    const fname = r.original_name || (r.original_path || "").split("/").pop() || "未知";
    const path = r.original_path || "";
    const title = r.recognized_title || "未识别";
    const status = r.status || "";
    const nfoFiles = r.nfo_written || [];
    const imgFiles = r.images_downloaded || [];
    const errors = r.errors || [];
    const actors = r.actors_count || 0;
    const dirs = r.directors || [];
    let parts = [`<div class="failure-log-filename">${icon} ${escapeHtml(fname)}</div>`];
    if (path) parts.push(`<div style="color:#7f8c9b;font-size:11px;font-family:monospace">${escapeHtml(path)}</div>`);
    parts.push(`<div style="margin-top:4px"><span style="color:var(--primary)">标题:</span> ${escapeHtml(title)}${status ? ` <span style="color:var(--text-light)">|</span> <span style="color:var(--text-light)">状态:</span> ${escapeHtml(status)}` : ''}</div>`);
    if (nfoFiles.length) parts.push(`<div style="font-size:11px;color:var(--success);margin-top:2px">📄 NFO (${nfoFiles.length}): ${escapeHtml(nfoFiles.join(", "))}</div>`);
    if (imgFiles.length) parts.push(`<div style="font-size:11px;color:var(--primary);margin-top:1px">🖼 图片 (${imgFiles.length}): ${escapeHtml(imgFiles.join(", "))}</div>`);
    if (actors) parts.push(`<div style="font-size:11px;color:#8e44ad;margin-top:1px">🎭 演员: ${actors}人</div>`);
    if (dirs.length) parts.push(`<div style="font-size:11px;color:#e67e22;margin-top:1px">🎬 导演: ${escapeHtml(dirs.join(", "))}</div>`);
    if (errors.length) parts.push(`<div style="font-size:11px;color:var(--danger);margin-top:1px">⚠️ 错误: ${escapeHtml(errors.join("; "))}</div>`);
    return `<div class="failure-log-item">${parts.join("")}</div>`;
  }).join("");
  document.querySelector("#failureLogModal .modal-title").textContent = "📋 完整刮削日志";
  document.getElementById("failureLogModal").classList.add("active");
}

function downloadBatchLogs() {
  if (!_scBatchResults.length) return;
  const lines = _scBatchResults.map(r => {
    const icon = r.success ? "[成功]" : "[失败]";
    const fname = r.original_name || (r.original_path || "").split("/").pop() || "未知";
    const path = r.original_path || "";
    const title = r.recognized_title || "未识别";
    const status = r.status || "";
    const nfoFiles = r.nfo_written || [];
    const imgFiles = r.images_downloaded || [];
    const errors = r.errors || [];
    const actors = r.actors_count || 0;
    const dirs = r.directors || [];
    let arr = [`${icon} ${fname}`];
    if (path) arr.push(`  路径: ${path}`);
    arr.push(`  标题: ${title}`);
    if (status) arr.push(`  状态: ${status}`);
    if (nfoFiles.length) arr.push(`  NFO (${nfoFiles.length}): ${nfoFiles.join(", ")}`);
    if (imgFiles.length) arr.push(`  图片 (${imgFiles.length}): ${imgFiles.join(", ")}`);
    if (actors) arr.push(`  演员: ${actors}人`);
    if (dirs.length) arr.push(`  导演: ${dirs.join(", ")}`);
    if (errors.length) arr.push(`  错误: ${errors.join("; ")}`);
    return arr.join("\n");
  });
  const content = `刮削日志 - ${new Date().toLocaleString("zh-CN")}\n${"=".repeat(50)}\n\n${lines.join("\n")}`;
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `scrape-log-${new Date().toISOString().slice(0, 10)}.log`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function scToggleServerLog() {
  const container = document.getElementById("sc-server-log-container");
  const arrow = document.getElementById("sc-server-log-arrow");
  if (!container) return;
  const isHidden = container.style.display === "none";
  container.style.display = isHidden ? "block" : "none";
  if (arrow) arrow.textContent = isHidden ? "▾" : "▶";
  if (isHidden) startServerLog("sc-server-log-container");
}

// ===== Manual Scrape (sub-tab) =====
let scManualSelectedFiles = [];
let _scManualSearchResults = [];
let scManualSelectedMatch = null;
let _scManualGroupCollapseState = {};

function scManualSelectFile() {
  openFileBrowser("file", "选择一个媒体文件", (file) => {
    if (!file) return;
    scManualSelectedFiles = [file];
    document.getElementById("sc-manual-file-count").textContent = `已选择 1 个文件: ${file.name}`;
    document.getElementById("sc-manual-progress-area").style.display = "none";
    scManualUpdateFileDisplay();
  });
}

async function scManualSelectFolder() {
  const countEl = document.getElementById("sc-manual-file-count");
  countEl.textContent = "扫描中...";
  openFileBrowser("folder", "选择一个文件夹（扫描其中媒体文件）", async (dirs) => {
    const dirList = Array.isArray(dirs) ? dirs : [dirs];
    if (!dirList.length) { countEl.textContent = "未选择"; return; }
    countEl.textContent = `正在扫描 ${dirList[0].split("/").pop()}...`;
    const allFiles = [];
    try {
      const response = await fetch(`/api/v1/filesystem/scan/stream?path=${encodeURIComponent(dirList[0])}&recursive=true`, { method: "POST", headers: { "Authorization": "Bearer " + (localStorage.getItem("authKey") || "") } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const data = JSON.parse(line);
            if (data.type === "complete") {
              allFiles.push(...data.media_files.map(f => ({ path: f.path, name: f.name, size: f.size })));
            } else if (data.type === "error") {
              throw new Error(data.message);
            }
          } catch (e) {
            if (e.message !== "Unexpected end of JSON input") throw e;
          }
        }
      }
    } catch (e) {
      countEl.textContent = `扫描失败: ${e.message}`;
      return;
    }
    if (!allFiles.length) { countEl.textContent = "未找到媒体文件"; return; }
    scManualSelectedFiles = allFiles;
    countEl.textContent = `已选择 ${allFiles.length} 个文件（来自 ${dirList[0].split("/").pop()}）`;
    document.getElementById("sc-manual-progress-area").style.display = "none";
    scManualUpdateFileDisplay();
  });
}

function scManualUpdateFileDisplay() {
  const section = document.getElementById("sc-manual-files-section");
  const listEl = document.getElementById("sc-manual-files-list");
  if (!scManualSelectedFiles.length) { section.style.display = "none"; return; }
  section.style.display = "block";

  const groups = {};
  for (const file of scManualSelectedFiles) {
    const dir = file.path ? file.path.substring(0, file.path.lastIndexOf("/")) || "/" : "/";
    if (!groups[dir]) groups[dir] = { name: dir.split("/").pop() || dir, files: [] };
    groups[dir].files.push(file);
  }
  const groupNames = Object.keys(groups).sort();
  for (const gid of groupNames) {
    if (!(gid in _scManualGroupCollapseState)) _scManualGroupCollapseState[gid] = true;
  }
  for (const gid of Object.keys(_scManualGroupCollapseState)) {
    if (!groups[gid]) delete _scManualGroupCollapseState[gid];
  }
  const allCollapsed = groupNames.every(gid => _scManualGroupCollapseState[gid]);
  const allExpanded = groupNames.every(gid => !_scManualGroupCollapseState[gid]);

  let html = `<div style="display:flex;gap:8px;padding:6px 12px;border-bottom:1px solid var(--border);">
    <button class="btn btn-outline" style="font-size:12px;padding:4px 10px" onclick="scManualCollapseAll()"${allCollapsed ? ' disabled' : ''}>全部收起</button>
    <button class="btn btn-outline" style="font-size:12px;padding:4px 10px" onclick="scManualExpandAll()"${allExpanded ? ' disabled' : ''}>全部展开</button>
  </div>`;
  for (const gid of groupNames) {
    const group = groups[gid];
    const count = group.files.length;
    const isCollapsed = _scManualGroupCollapseState[gid];
    html += `<div class="group-header" onclick="scManualToggleGroup('${encodeURIComponent(gid)}')">
      <span class="group-toggle${isCollapsed ? ' collapsed' : ''}">▼</span>
      📁 ${escapeHtml(group.name)} <span style="color:var(--text-light);font-size:12px">${count} 个文件</span>
    </div>`;
    html += `<div class="group-files${isCollapsed ? ' collapsed' : ''}" style="max-height:${isCollapsed ? '0' : (count * 42 + 'px')}">`;
    html += group.files.map(file => `
      <div class="scan-item">
        <span>📄</span><span style="flex:1">${escapeHtml(file.name)}</span><span style="color:var(--text-light);font-size:12px">${formatFileSize(file.size)}</span>
      </div>
    `).join("");
    html += `</div>`;
  }
  listEl.innerHTML = html;
}

function scManualToggleGroup(encodedGid) {
  const gid = decodeURIComponent(encodedGid);
  _scManualGroupCollapseState[gid] = !_scManualGroupCollapseState[gid];
  scManualUpdateFileDisplay();
}

function scManualCollapseAll() {
  for (const gid in _scManualGroupCollapseState) _scManualGroupCollapseState[gid] = true;
  scManualUpdateFileDisplay();
}

function scManualExpandAll() {
  for (const gid in _scManualGroupCollapseState) _scManualGroupCollapseState[gid] = false;
  scManualUpdateFileDisplay();
}

function scManualClearFiles() {
  scManualSelectedFiles = [];
  scManualSelectedMatch = null;
  _scManualGroupCollapseState = {};
  document.getElementById("sc-manual-file-count").textContent = "未选择";
  document.getElementById("sc-manual-files-section").style.display = "none";
  document.getElementById("sc-manual-search-result").style.display = "none";
  document.getElementById("sc-manual-progress-area").style.display = "none";
  document.getElementById("sc-manual-logs").innerHTML = "";
  document.getElementById("sc-manual-logs").style.display = "none";
  document.getElementById("sc-manual-progress").textContent = "";
  document.getElementById("sc-manual-time").textContent = "";
  document.getElementById("sc-manual-bar-fill").style.width = "0%";
  document.getElementById("sc-manual-actions").style.display = "none";
  document.getElementById("sc-manual-search-count").textContent = "";
  document.getElementById("sc-manual-title").value = "";
  document.getElementById("sc-manual-year").value = "";
  document.getElementById("sc-manual-tmdb-id").value = "";
  document.getElementById("sc-manual-season-number").value = "";
  document.getElementById("sc-manual-collection-id").value = "";
  document.getElementById("sc-manual-tv-id").value = "";
}

function scManualOnTypeChange() {
  const type = document.getElementById("sc-manual-type").value;
  document.getElementById("sc-manual-season-fields").style.display = type === "season" ? "block" : "none";
  document.getElementById("sc-manual-collection-fields").style.display = type === "collection" ? "block" : "none";
  document.getElementById("sc-manual-tv-id-field").style.display = type === "season" ? "block" : "none";
}

async function scManualSearch() {
  const title = document.getElementById("sc-manual-title").value.trim();
  const tmdbId = document.getElementById("sc-manual-tmdb-id").value.trim();
  const year = document.getElementById("sc-manual-year").value.trim();
  const type = document.getElementById("sc-manual-type").value;
  const seasonNumber = document.getElementById("sc-manual-season-number").value.trim();
  const collectionId = document.getElementById("sc-manual-collection-id").value.trim();

  if (!title && !tmdbId && !collectionId) { alert("请输入媒体名称或 TMDb ID"); return; }

  const resultEl = document.getElementById("sc-manual-search-result");
  const listEl = document.getElementById("sc-manual-search-list");
  const countEl = document.getElementById("sc-manual-search-count");
  resultEl.style.display = "block";
  listEl.innerHTML = '<div style="text-align:center;padding:32px;color:var(--text-light)">🔍 搜索中...</div>';

  try {
    const body = {};
    if (tmdbId) body.tmdb_id = parseInt(tmdbId);
    if (title) body.title = title;
    if (year) body.year = parseInt(year);
    body.type = type;
    if (seasonNumber) body.season_number = parseInt(seasonNumber);
    if (collectionId) { body.tmdb_id = parseInt(collectionId); body.type = "collection"; }

    const res = await fetch("/api/v1/media/tmdb-search", {
      method: "POST",
      headers: {"Content-Type": "application/json", "Authorization": "Bearer " + (localStorage.getItem("authKey") || "") },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!data.results || !data.results.length) {
      listEl.innerHTML = '<div style="text-align:center;padding:32px;color:#e67e22">未找到匹配结果，请调整搜索条件</div>';
      countEl.textContent = "";
      return;
    }
    countEl.textContent = `共 ${data.results.length} 条结果`;
    _scManualSearchResults = data.results;
    listEl.innerHTML = data.results.map(r => {
      const badgeInfo = { cls: "movie", icon: "🎬", text: "电影" };
      if (r.type === "tv" && (!r.media_category || r.media_category !== "season")) { badgeInfo.cls = "tv"; badgeInfo.icon = "📺"; badgeInfo.text = "剧集"; }
      else if (r.type === "season" || r.media_category === "season") { badgeInfo.cls = "season"; badgeInfo.icon = "📅"; badgeInfo.text = "季"; }
      else if (r.type === "collection" || r.media_category === "collection") { badgeInfo.cls = "collection"; badgeInfo.icon = "📚"; badgeInfo.text = "合集"; }
      else if (r.media_category === "documentary") { badgeInfo.cls = "documentary"; badgeInfo.icon = "🎞️"; badgeInfo.text = "纪录片"; }
      else if (r.media_category === "music_video") { badgeInfo.cls = "music_video"; badgeInfo.icon = "🎵"; badgeInfo.text = "音乐视频"; }
      else if (r.media_category === "variety") { badgeInfo.cls = "variety"; badgeInfo.icon = "🎭"; badgeInfo.text = "综艺"; }
      else if (r.media_category === "short") { badgeInfo.cls = "short"; badgeInfo.icon = "🎬"; badgeInfo.text = "短片"; }
      const posterHtml = r.poster ? `<img class="search-result-poster" src="/api/v1/media/image?path=${encodeURIComponent(r.poster)}&size=w92" alt="" onerror="this.style.display='none'">` : `<div class="search-result-poster-placeholder">🎬</div>`;
      const ratingHtml = r.rating ? `<span class="search-result-rating">⭐ ${Number(r.rating).toFixed(1)}</span>` : "";
      const yearHtml = r.year ? `<span class="search-result-year">${r.year}</span>` : "";
      const overviewHtml = r.overview ? `<div class="search-result-overview">${escapeHtml(r.overview)}</div>` : "";
      return `<div class="search-result-card">
        ${posterHtml}
        <div class="search-result-info">
          <div class="search-result-title">
            <span class="search-result-title-text" title="${escapeHtml(r.title)}">${escapeHtml(r.title)}</span>
            <span class="search-result-badge ${badgeInfo.cls}">${badgeInfo.icon} ${badgeInfo.text}</span>
            ${yearHtml}${ratingHtml}
          </div>
          ${overviewHtml}
        </div>
        <div class="search-result-action">
          <button class="btn btn-sm btn-primary" onclick="scManualSelectMatch(${r.id}, '${escapeHtml(r.title)}', '${r.year || ''}', '${r.type}', '${r.media_category || ''}', ${r.season_number !== undefined && r.season_number !== null ? r.season_number : null})">选择</button>
        </div>
      </div>`;
    }).join("");
  } catch (e) {
    listEl.innerHTML = `<div style="text-align:center;padding:32px;color:#e74c3c">搜索失败: ${escapeHtml(e.message)}</div>`;
    countEl.textContent = "";
  }
}

function scManualSelectMatch(id, title, year, type, mediaCategory, seasonNumber) {
  scManualSelectedMatch = { id, title, year, type, mediaCategory, seasonNumber };
  const files = scManualSelectedFiles;
  if (!files.length) { alert("请先选择要刮削的文件"); return; }
  const result = _scManualSearchResults.find(r => r.id === id) || {};
  const poster = result.poster || "";
  const rating = result.rating || "";
  const overview = result.overview || "";

  const listEl = document.getElementById("sc-manual-search-list");
  const countEl = document.getElementById("sc-manual-search-count");
  const posterHtml = poster ? `<img class="search-result-poster" src="/api/v1/media/image?path=${encodeURIComponent(poster)}&size=w92" alt="" onerror="this.style.display='none'">` : `<div class="search-result-poster-placeholder">🎬</div>`;
  const ratingHtml = rating ? `<span class="search-result-rating">⭐ ${Number(rating).toFixed(1)}</span>` : "";
  const yearHtml = year ? `<span class="search-result-year">${year}</span>` : "";
  const overviewHtml = overview ? `<div class="search-result-overview">${escapeHtml(overview)}</div>` : "";
  listEl.innerHTML = `<div class="search-result-card" style="opacity:0.85">
    ${posterHtml}
    <div class="search-result-info">
      <div class="search-result-title">
        <span class="search-result-title-text" title="${escapeHtml(title)}">${escapeHtml(title)}</span>
        <span class="search-result-badge ${type === 'tv' ? 'tv' : 'movie'}">${type === 'tv' ? '📺 剧集' : '🎬 电影'}</span>
        ${yearHtml}${ratingHtml}
        <span style="color:var(--success);margin-left:8px;font-size:13px">✅ 已选择</span>
      </div>
      ${overviewHtml}
    </div>
  </div>`;
  countEl.textContent = `已选择: ${escapeHtml(title)}`;
  scShowManualProgress(files, id, title, year, type, mediaCategory, seasonNumber);
}

async function scShowManualProgress(files, tmdbId, title, year, type, mediaCategory, seasonNumber) {
  const progressArea = document.getElementById("sc-manual-progress-area");
  const logEl = document.getElementById("sc-manual-logs");
  const progressEl = document.getElementById("sc-manual-progress");
  const timeEl = document.getElementById("sc-manual-time");
  const barFill = document.getElementById("sc-manual-bar-fill");
  const actionsEl = document.getElementById("sc-manual-actions");

  progressArea.style.display = "block";
  progressArea.className = "result-box info";
  logEl.style.display = "none";
  actionsEl.style.display = "none";
  progressEl.textContent = `正在刮削 ${files.length} 个文件...`;
  barFill.style.width = "0%";
  logEl.innerHTML = "";
  document.getElementById("sc-server-log-panel").style.display = "block";
  startServerLog("sc-server-log-container");

  const _startTime = Date.now();
  timeEl.textContent = "⏱ 用时: 0s";
  const _timerInterval = setInterval(() => {
    const sec = Math.round((Date.now() - _startTime) / 1000);
    timeEl.textContent = `⏱ 用时: ${sec < 60 ? sec + "s" : Math.floor(sec / 60) + "m " + (sec % 60) + "s"}`;
  }, 1000);

  const opts = getScrapeOptions();
  let total = 0, completedCount = 0, successCount = 0, failedCount = 0;
  _scBatchResults = [];

  try {
    const res = await fetch("/api/v1/media/manual-scrape/stream", {
      method: "POST",
      headers: {"Content-Type": "application/json", "Authorization": "Bearer " + (localStorage.getItem("authKey") || "") },
      body: JSON.stringify({
        files: files.map(f => ({path: f.path, name: f.name})),
        source: "tmdb",
        tmdb_id: tmdbId,
        title: title,
        year: year || null,
        media_type: type,
        download_images: true,
        write_nfo: true,
        download_actor_images: opts.download_actor_images,
        media_category: mediaCategory || null,
        season_number: seasonNumber || null,
      }),
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const data = JSON.parse(line);
          if (data.type === "result") {
            total = data.total;
            completedCount++;
            _scBatchResults.push(data.data);
            const pct = total > 0 ? Math.round(completedCount / total * 100) : 0;
            progressEl.textContent = `进度: ${completedCount}/${total} (${pct}%)`;
            barFill.style.width = pct + "%";
            if (data.success) { successCount++; } else { failedCount++; }
          } else if (data.type === "progress") {
            progressEl.textContent = data.message;
          } else if (data.type === "complete") {
            clearInterval(_timerInterval);
            const elapsed = Math.round((Date.now() - _startTime) / 1000);
            const timeStr = elapsed < 60 ? `${elapsed}s` : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`;
            barFill.style.width = "100%";
            progressEl.textContent = `✅ 完成！总计: ${total}, 成功: ${successCount}, 失败: ${failedCount} (⏱ ${timeStr})`;
            logEl.style.display = "block";

            const seriesGroups = {};
            _scBatchResults.forEach(r => {
              const key = r.recognized_title || "未识别";
              if (!seriesGroups[key]) seriesGroups[key] = [];
              seriesGroups[key].push(r);
            });
            const seriesKeys = Object.keys(seriesGroups).sort();
            seriesKeys.forEach(seriesName => {
              const items = seriesGroups[seriesName];
              const sSuccess = items.filter(i => i.success).length;
              const allGood = sSuccess === items.length;
              const header = document.createElement("div");
              header.className = "manual-log-group-header";
              const toggle = document.createElement("span");
              toggle.className = "group-toggle collapsed";
              toggle.textContent = "▶";
              header.appendChild(toggle);
              header.appendChild(document.createTextNode(`${allGood ? "✅" : "⚠️"} ${escapeHtml(seriesName)}`));
              const count = document.createElement("span");
              count.style.cssText = "color:var(--text-light);font-size:12px;margin-left:auto";
              count.textContent = `${sSuccess}/${items.length}`;
              header.appendChild(count);
              const body = document.createElement("div");
              body.className = "manual-log-group-body collapsed";
              items.forEach(r => {
                const icon = r.success ? "✅" : "❌";
                const fname = r.original_name || (r.original_path || "").split("/").pop() || "未知";
                let detail = "";
                if (r.success) {
                  const nf = (r.nfo_written || []).length;
                  const im = (r.images_downloaded || []).length;
                  detail = ` (${nf} NFO, ${im} 图片)`;
                  if (!document.getElementById("autoWriteToggle").checked) detail = " (未开启文件下载)";
                } else {
                  detail = `: ${(r.errors || [r.status]).join("; ")}`;
                }
                const item = document.createElement("div");
                item.className = "manual-log-item";
                item.textContent = `${icon} ${escapeHtml(fname)}${detail}`;
                body.appendChild(item);
              });
              logEl.appendChild(header);
              logEl.appendChild(body);
              header.addEventListener("click", () => { body.classList.toggle("collapsed"); toggle.classList.toggle("collapsed"); });
            });

            actionsEl.style.display = "flex";
            actionsEl.style.gap = "8px";
            actionsEl.style.flexWrap = "wrap";
            actionsEl.innerHTML = `<button class="btn btn-outline" onclick="viewBatchLogs()">📋 查看完整日志</button><button class="btn btn-outline" onclick="downloadBatchLogs()">📥 下载日志</button>`;

            progressArea.className = "result-box " + (failedCount === 0 ? "success" : successCount === 0 ? "error" : "warning");
            stopServerLog();
          }
        } catch (e) {}
      }
    }
  } catch (e) {
    clearInterval(_timerInterval);
    progressEl.textContent = `❌ 请求失败: ${escapeHtml(e.message)}`;
    progressArea.className = "result-box error";
    stopServerLog();
  }
}

// ===== Config =====
function togglePasswordVisibility(inputId, btn) {
  const input = document.getElementById(inputId);
  if (input.type === "password") {
    input.type = "text";
    btn.textContent = "🙈";
    if (!input.value && input.dataset.actualKey) input.value = input.dataset.actualKey;
  } else {
    input.type = "password";
    btn.textContent = "👁";
    if (input.dataset.actualKey && input.value === input.dataset.actualKey) { input.value = ""; input.placeholder = maskKey(input.dataset.actualKey); }
  }
}

async function loadConfig() {
  const el = document.getElementById("configDisplay");
  try {
    const data = await api("/api/v1/config");
    const lines = [
      `运行模式: ${data.mode}`,
      `TMDb API Key: ${data.tmdb_api_key_set ? "✅ 已配置" : "❌ 未配置"}`,
      `Bangumi API Key: ${data.bgm_api_key_set ? "✅ 已配置" : "❌ 未配置"}`,
      `AI Key (剧名推断): ${data.ai_api_key_set ? "✅ 已配置" : "❌ 未配置"}`,
      `AI API 地址: ${data.ai_base_url || "默认"}`,
      `AI 模型: ${data.ai_model || "默认"}`,
      `Token 上限: ${data.ai_max_tokens || 200}`,
    ];
    el.style.display = "block";
    el.className = "result-box info";
    el.innerHTML = lines.map(l => `<div style="line-height:1.8">${escapeHtml(l)}</div>`).join("");
    if (data.ai_base_url) document.getElementById("configAiUrl").value = data.ai_base_url;
    if (data.ai_model) document.getElementById("configAiModel").value = data.ai_model;
    if (data.ai_max_tokens) document.getElementById("configAiMaxTokens").value = data.ai_max_tokens;
    if (data.tmdb_api_key_set) { const inp = document.getElementById("configTmdb"); inp.value = ""; inp.placeholder = maskKey(data.tmdb_api_key); inp.dataset.masked = "true"; inp.dataset.actualKey = data.tmdb_api_key; }
    if (data.bgm_api_key_set) { const inp = document.getElementById("configBgm"); inp.value = ""; inp.placeholder = maskKey(data.bgm_api_key); inp.dataset.masked = "true"; inp.dataset.actualKey = data.bgm_api_key; }
    if (data.ai_api_key_set) { const inp = document.getElementById("configAiKey"); inp.value = ""; inp.placeholder = maskKey(data.ai_api_key); inp.dataset.masked = "true"; inp.dataset.actualKey = data.ai_api_key; }
  } catch (e) { show(el, e.message, "error"); }
}

async function updateConfig() {
  const el = document.getElementById("configResult");
  const tmdb = getKeyValue("configTmdb");
  const bgm = getKeyValue("configBgm");
  const aiKey = getKeyValue("configAiKey");
  const aiUrl = document.getElementById("configAiUrl").value.trim();
  const aiModel = document.getElementById("configAiModel").value.trim();
  const aiMaxTokens = document.getElementById("configAiMaxTokens").value.trim();
  if (!tmdb && !bgm && !aiKey && !aiUrl && !aiModel && !aiMaxTokens) { show(el, "没有需要更新的配置", "info"); return; }
  const body = {};
  if (tmdb) body.tmdb_api_key = tmdb;
  if (bgm) body.bgm_api_key = bgm;
  if (aiKey) body.ai_api_key = aiKey;
  if (aiUrl) body.ai_base_url = aiUrl;
  if (aiModel) body.ai_model = aiModel;
  if (aiMaxTokens) body.ai_max_tokens = parseInt(aiMaxTokens, 10);
  try {
    const data = await api("/api/v1/config", { method: "PUT", body: JSON.stringify(body) });
    show(el, data, "success");
    loadConfig();
  } catch (e) { show(el, e.message, "error"); }
}

function getKeyValue(inputId) {
  const inp = document.getElementById(inputId);
  const val = inp.value.trim();
  if (inp.dataset.masked === "true" && !val) return null;
  if (!val) return null;
  return val;
}

async function clearCache() {
  const el = document.getElementById("configResult");
  try {
    const data = await api("/api/v1/config/clear-cache", { method: "POST" });
    show(el, data, "success");
  } catch (e) { show(el, e.message, "error"); }
}

// ===== Server Log =====
let _serverLogSource = null;
let _serverLogBuffer = [];
let _serverLogContainerId = null;

function startServerLog(containerId) {
  stopServerLog();
  _serverLogContainerId = containerId;
  _serverLogBuffer = [];
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = '<div style="color:#888">等待服务端日志...</div>';
  container.style.display = "block";
  _serverLogSource = new EventSource(BASE + "/api/v1/media/logs/stream");
  _serverLogSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      const logs = data.logs || [];
      if (logs.length !== _serverLogBuffer.length) { _serverLogBuffer = logs; renderServerLog(); }
    } catch (e) {}
  };
  _serverLogSource.onerror = () => {};
}

function stopServerLog() {
  if (_serverLogSource) { _serverLogSource.close(); _serverLogSource = null; }
}

function renderServerLog() {
  if (!_serverLogContainerId) return;
  const container = document.getElementById(_serverLogContainerId);
  if (!container) return;
  container.innerHTML = _serverLogBuffer.slice(-30).map(l => escapeHtml(l)).join("\n");
  container.scrollTop = container.scrollHeight;
}

// Init
checkHealth();
loadAutoWriteConfig();
loadRoot();
loadAbout();