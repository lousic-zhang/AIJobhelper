const layout = document.querySelector(".knowledge-layout");
const baseList = document.getElementById("knowledge-base-list");
const createForm = document.getElementById("knowledge-create-form");
const createResult = document.getElementById("knowledge-create-result");
const ingestForm = document.getElementById("knowledge-ingest-form");
const ingestResult = document.getElementById("knowledge-ingest-result");
const chatForm = document.getElementById("knowledge-chat-form");
const chatLog = document.getElementById("knowledge-chat-log");
const titleEl = document.getElementById("knowledge-title");
const statusEl = document.getElementById("knowledge-status");

let selectedKnowledgeBaseId = layout?.dataset.selectedKnowledgeBaseId || "";
let knowledgeBases = [];

function appendBubble(role, content) {
    if (!chatLog) return;
    const div = document.createElement("div");
    div.className = `chat-bubble ${role}`;
    div.textContent = content;
    chatLog.appendChild(div);
    chatLog.scrollTop = chatLog.scrollHeight;
}

function clearChatLog() {
    if (!chatLog) return;
    chatLog.innerHTML = "";
}

function renderKnowledgeBaseList() {
    if (!baseList) return;
    if (!knowledgeBases.length) {
        baseList.innerHTML = '<div class="empty-block">还没有知识库，先创建一个岗位知识库。</div>';
        return;
    }
    baseList.innerHTML = knowledgeBases.map((item) => `
        <button class="knowledge-base-item ${item._id === selectedKnowledgeBaseId ? "active" : ""}" data-id="${item._id}" type="button">
            <strong>${item.name}</strong>
            <span>${item.status}</span>
        </button>
    `).join("");
}

function updateSelectedMeta() {
    const selected = knowledgeBases.find((item) => item._id === selectedKnowledgeBaseId);
    if (!selected) {
        titleEl.textContent = "请选择一个知识库";
        statusEl.textContent = "创建后即可导入岗位链接。";
        return;
    }
    titleEl.textContent = selected.name;
    statusEl.textContent = `当前状态：${selected.status}${selected.last_source_url ? ` ｜ 最近来源：${selected.last_source_url}` : ""}`;
}

async function loadKnowledgeBases() {
    const response = await fetch("/api/knowledge-bases");
    if (!response.ok) {
        throw new Error("加载知识库列表失败");
    }
    knowledgeBases = await response.json();
    if (!selectedKnowledgeBaseId && knowledgeBases.length) {
        selectedKnowledgeBaseId = knowledgeBases[0]._id;
    }
    renderKnowledgeBaseList();
    updateSelectedMeta();
}

async function loadMessages() {
    clearChatLog();
    if (!selectedKnowledgeBaseId) return;
    const response = await fetch(`/api/knowledge-bases/${selectedKnowledgeBaseId}/messages`);
    if (!response.ok) {
        appendBubble("assistant", "加载知识库历史失败。");
        return;
    }
    const messages = await response.json();
    messages.forEach((message) => appendBubble(message.role === "assistant" ? "assistant" : "user", message.content));
}

if (createForm) {
    createForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const formData = new FormData(createForm);
        const payload = {name: formData.get("name")};
        createResult.textContent = "正在创建知识库...";
        const response = await fetch("/api/knowledge-bases", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
        });
        const result = await response.json();
        if (!response.ok) {
            createResult.textContent = result.detail || "创建失败";
            return;
        }
        createResult.textContent = `已创建：${result.name}`;
        selectedKnowledgeBaseId = result._id;
        createForm.reset();
        await loadKnowledgeBases();
        await loadMessages();
    });
}

if (baseList) {
    baseList.addEventListener("click", async (event) => {
        const button = event.target.closest(".knowledge-base-item");
        if (!button) return;
        selectedKnowledgeBaseId = button.dataset.id;
        renderKnowledgeBaseList();
        updateSelectedMeta();
        await loadMessages();
    });
}

if (ingestForm) {
    ingestForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!selectedKnowledgeBaseId) {
            ingestResult.textContent = "请先创建或选择一个知识库。";
            return;
        }
        const formData = new FormData(ingestForm);
        ingestResult.textContent = "正在导入链接...";
        const response = await fetch(`/api/knowledge-bases/${selectedKnowledgeBaseId}/ingest-url`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({url: formData.get("url")}),
        });
        const result = await response.json();
        if (!response.ok) {
            ingestResult.textContent = result.detail || "导入失败";
            return;
        }
        ingestResult.textContent = result.message || "导入成功";
        ingestForm.reset();
        await loadKnowledgeBases();
        appendBubble("assistant", result.message || "当前知识库已更新。");
    });
}

if (chatForm) {
    chatForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!selectedKnowledgeBaseId) {
            appendBubble("assistant", "请先创建或选择一个知识库。");
            return;
        }
        const formData = new FormData(chatForm);
        const message = String(formData.get("message") || "").trim();
        if (!message) return;
        appendBubble("user", message);
        chatForm.reset();

        try {
            const response = await fetch(`/api/knowledge-bases/${selectedKnowledgeBaseId}/chat`, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({message}),
            });
            const result = await response.json();
            if (!response.ok) {
                appendBubble("assistant", result.detail || "知识库聊天失败。");
                return;
            }
            appendBubble("assistant", result.reply);
            await loadKnowledgeBases();
        } catch (error) {
            appendBubble("assistant", `知识库聊天失败：${error.message}`);
        }
    });
}

loadKnowledgeBases().then(loadMessages).catch((error) => {
    if (createResult) {
        createResult.textContent = error.message || "初始化知识库页面失败";
    }
});
