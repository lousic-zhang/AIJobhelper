const importForm = document.getElementById("job-match-import-form");
const importResult = document.getElementById("job-match-import-result");
const taskList = document.getElementById("job-match-task-list");
const taskCount = document.getElementById("job-match-task-count");
const workspace = document.querySelector(".job-match-workspace");
const titleEl = document.getElementById("job-match-title");
const statusEl = document.getElementById("job-match-status");
const metaEl = document.getElementById("job-match-meta");
const resultsEl = document.getElementById("job-match-results");

let tasks = [];
let selectedTaskId = workspace?.dataset.selectedTaskId || "";
let pollTimer = null;

function statusLabel(status) {
    return {
        queued: "排队中",
        running: "执行中",
        succeeded: "已完成",
        failed: "失败",
    }[status] || status;
}

function renderTaskList() {
    if (!taskList) return;
    taskCount.textContent = tasks.length ? `${tasks.length} 个任务` : "";
    if (!tasks.length) {
        taskList.innerHTML = '<div class="empty-block">还没有匹配任务，先粘贴几条岗位详情页 URL。</div>';
        return;
    }
    taskList.innerHTML = tasks.map((task) => `
        <button class="knowledge-base-item ${task._id === selectedTaskId ? "active" : ""}" data-task-id="${task._id}" type="button">
            <strong>${task.source_domain}</strong>
            <span>${statusLabel(task.status)}</span>
            <small class="muted">${task.progress_message || ""}</small>
        </button>
    `).join("");
}

function renderTaskDetail(detail) {
    if (!detail || !detail.task) {
        titleEl.textContent = "请选择一个匹配任务";
        statusEl.textContent = "任务创建后，系统会通过 Browser MCP 依次打开岗位详情页并进行匹配评估。";
        metaEl.innerHTML = "";
        resultsEl.innerHTML = '<div class="empty-block">任务完成后，这里会展示匹配岗位列表。</div>';
        return;
    }

    const task = detail.task;
    titleEl.textContent = `${task.source_domain} 岗位匹配`;
    statusEl.textContent = `状态：${statusLabel(task.status)} | 阶段：${task.current_stage || "-"}${task.error_message ? ` | ${task.error_message}` : ""}`;
    metaEl.innerHTML = `
        <div class="kv"><span>首个来源 URL</span><span>${task.source_url}</span></div>
        <div class="kv"><span>提交 URL 数量</span><span>${(task.source_urls || []).length}</span></div>
        <div class="kv"><span>当前进度</span><span>${task.progress_message || "暂无进度说明"}</span></div>
        <div class="kv"><span>已打开详情页</span><span>${task.total_pages_found}</span></div>
        <div class="kv"><span>识别岗位数</span><span>${task.total_jobs_found}</span></div>
        <div class="kv"><span>匹配结果数</span><span>${task.total_jobs_matched}</span></div>
    `;

    if (!detail.results.length) {
        resultsEl.innerHTML = '<div class="empty-block">任务还没有产出岗位结果。</div>';
        return;
    }

    resultsEl.innerHTML = detail.results.map((item) => `
        <details class="job-result-card">
            <summary>
                <div>
                    <strong>${item.match_rank}. ${item.title}</strong>
                    <div class="muted">${item.company}${item.location ? ` | ${item.location}` : ""}</div>
                </div>
                <div class="job-result-score">${item.match_score}</div>
            </summary>
            <p>${item.match_reason_short || ""}</p>
            <div class="job-result-section">
                <strong>优势</strong>
                <div>${(item.strengths || []).join(" / ") || "暂无"}</div>
            </div>
            <div class="job-result-section">
                <strong>短板</strong>
                <div>${(item.gaps || []).join(" / ") || "暂无"}</div>
            </div>
            <div class="job-result-section">
                <strong>JD 摘要</strong>
                <div>${item.summary_text || "暂无摘要"}</div>
            </div>
            <div class="job-result-section">
                <strong>岗位正文节选</strong>
                <div>${item.jd_text.slice(0, 1000) || "暂无正文"}</div>
            </div>
            <a href="${item.source_url}" target="_blank" rel="noreferrer">查看原始岗位链接</a>
        </details>
    `).join("");
}

async function loadTasks() {
    const response = await fetch("/api/job-matches");
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.detail || "加载任务列表失败");
    }
    tasks = data;
    if (!selectedTaskId && tasks.length) {
        selectedTaskId = tasks[0]._id;
    }
    renderTaskList();
}

async function loadTaskDetail(taskId) {
    if (!taskId) {
        renderTaskDetail(null);
        return;
    }
    const response = await fetch(`/api/job-matches/${taskId}`);
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.detail || "加载任务详情失败");
    }
    renderTaskDetail(data);
    setupPolling(data.task.status);
}

function setupPolling(status) {
    if (pollTimer) {
        window.clearTimeout(pollTimer);
        pollTimer = null;
    }
    if (!selectedTaskId) return;
    if (status === "queued" || status === "running") {
        pollTimer = window.setTimeout(async () => {
            try {
                await loadTasks();
                await loadTaskDetail(selectedTaskId);
            } catch (error) {
                importResult.textContent = error.message;
            }
        }, 3000);
    }
}

if (taskList) {
    taskList.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-task-id]");
        if (!button) return;
        selectedTaskId = button.dataset.taskId;
        renderTaskList();
        await loadTaskDetail(selectedTaskId);
    });
}

if (importForm) {
    importForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const formData = new FormData(importForm);
        const urlsText = String(formData.get("urls") || "");
        const urls = urlsText
            .split(/\r?\n/)
            .map((item) => item.trim())
            .filter(Boolean);

        if (!urls.length) {
            importResult.textContent = "请至少粘贴一条岗位详情页 URL。";
            return;
        }

        importResult.textContent = "正在创建批量评估任务...";
        const response = await fetch("/api/job-matches/import", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({urls}),
        });
        const data = await response.json();
        if (!response.ok) {
            importResult.textContent = data.detail || "创建任务失败";
            return;
        }
        importResult.textContent = `任务已创建，系统将通过 Browser MCP 依次打开这些岗位详情页。任务 ID：${data.task_id}`;
        importForm.reset();
        await loadTasks();
        selectedTaskId = data.task_id;
        renderTaskList();
        await loadTaskDetail(selectedTaskId);
    });
}

async function bootstrap() {
    try {
        await loadTasks();
        if (selectedTaskId) {
            await loadTaskDetail(selectedTaskId);
        } else {
            renderTaskDetail(null);
        }
    } catch (error) {
        importResult.textContent = error.message || "初始化匹配岗位列表失败";
    }
}

bootstrap();
