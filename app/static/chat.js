const chatForm = document.getElementById("chat-form");
const chatLog = document.getElementById("chat-log");
const uploadForm = document.getElementById("resume-upload-form");
const uploadResult = document.getElementById("resume-upload-result");
const sessionList = document.getElementById("chat-session-list");
const newChatBtn = document.getElementById("new-chat-btn");

let currentChatId = chatForm?.querySelector('[name="chat_id"]')?.value || "";

function appendBubble(role, text) {
    if (!chatLog) return;
    const div = document.createElement("div");
    div.className = `chat-bubble ${role}`;
    div.textContent = text;
    chatLog.appendChild(div);
    chatLog.scrollTop = chatLog.scrollHeight;
}

function clearChatLog() {
    if (!chatLog) return;
    chatLog.innerHTML = "";
}

function setCurrentChatId(chatId) {
    currentChatId = chatId;
    if (chatForm) {
        chatForm.querySelector('[name="chat_id"]').value = chatId;
    }
    if (uploadForm) {
        uploadForm.querySelector('[name="chat_id"]').value = chatId;
    }
    document.querySelectorAll(".chat-session-item").forEach((item) => {
        item.classList.toggle("active", item.dataset.chatId === chatId);
    });
}

async function loadChatSessions() {
    const response = await fetch("/api/chat-sessions");
    const sessions = await response.json();
    if (!response.ok) {
        throw new Error(sessions.detail || "Failed to load chat sessions.");
    }
    renderChatSessions(sessions);
    if (!currentChatId && sessions.length > 0) {
        setCurrentChatId(sessions[0]._id || sessions[0].id);
    }
    return sessions;
}

function buildSessionItem(session) {
    const chatId = session._id || session.id;
    const wrapper = document.createElement("div");
    wrapper.className = `chat-session-item ${chatId === currentChatId ? "active" : ""}`;
    wrapper.dataset.chatId = chatId;

    const mainButton = document.createElement("button");
    mainButton.className = "chat-session-main";
    mainButton.type = "button";
    mainButton.dataset.chatId = chatId;
    mainButton.innerHTML = `<span>${session.title || "New chat"}</span>`;
    mainButton.addEventListener("click", async () => {
        setCurrentChatId(chatId);
        await loadChatMessages(chatId);
    });

    const actions = document.createElement("div");
    actions.className = "chat-session-actions";

    const renameButton = document.createElement("button");
    renameButton.className = "chat-session-action rename";
    renameButton.type = "button";
    renameButton.textContent = "重命名";
    renameButton.addEventListener("click", async () => {
        const nextTitle = window.prompt("请输入新的聊天标题", session.title || "New chat");
        if (nextTitle === null) return;
        await renameChat(chatId, nextTitle);
    });

    const deleteButton = document.createElement("button");
    deleteButton.className = "chat-session-action delete";
    deleteButton.type = "button";
    deleteButton.textContent = "删除";
    deleteButton.addEventListener("click", async () => {
        const confirmed = window.confirm("确认删除这个聊天吗？删除后聊天记录会一并清空。");
        if (!confirmed) return;
        await deleteChat(chatId);
    });

    actions.appendChild(renameButton);
    actions.appendChild(deleteButton);
    wrapper.appendChild(mainButton);
    wrapper.appendChild(actions);
    return wrapper;
}

function renderChatSessions(sessions) {
    if (!sessionList) return;
    sessionList.innerHTML = "";
    sessions.forEach((session) => {
        sessionList.appendChild(buildSessionItem(session));
    });
}

async function loadChatMessages(chatId) {
    if (!chatId) return;
    clearChatLog();
    const response = await fetch(`/api/chat-sessions/${chatId}/messages`);
    const messages = await response.json();
    if (!response.ok) {
        appendBubble("assistant", messages.detail || "Failed to load chat history.");
        return;
    }
    messages.forEach((message) => {
        appendBubble(message.role === "assistant" ? "assistant" : "user", message.content);
    });
}

async function createNewChat() {
    const response = await fetch("/api/chat-sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: "" }),
    });
    const session = await response.json();
    if (!response.ok) {
        appendBubble("assistant", session.detail || "Failed to create chat.");
        return;
    }
    await loadChatSessions();
    setCurrentChatId(session._id || session.id);
    clearChatLog();
}

async function renameChat(chatId, title) {
    const response = await fetch(`/api/chat-sessions/${chatId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
    });
    const result = await response.json();
    if (!response.ok) {
        appendBubble("assistant", result.detail || "Failed to rename chat.");
        return;
    }
    await loadChatSessions();
    setCurrentChatId(chatId);
}

async function deleteChat(chatId) {
    const response = await fetch(`/api/chat-sessions/${chatId}`, {
        method: "DELETE",
    });
    const result = await response.json();
    if (!response.ok) {
        appendBubble("assistant", result.detail || "Failed to delete chat.");
        return;
    }
    const sessions = await loadChatSessions();
    if (currentChatId === chatId) {
        if (sessions.length > 0) {
            const nextChatId = sessions[0]._id || sessions[0].id;
            setCurrentChatId(nextChatId);
            await loadChatMessages(nextChatId);
        } else {
            currentChatId = "";
            clearChatLog();
            await createNewChat();
        }
    }
}

if (newChatBtn) {
    newChatBtn.addEventListener("click", async () => {
        await createNewChat();
    });
}

if (chatForm) {
    chatForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const formData = new FormData(chatForm);
        const payload = {
            chat_id: formData.get("chat_id"),
            message: formData.get("message"),
        };

        if (!payload.message) {
            return;
        }

        appendBubble("user", payload.message);
        chatForm.reset();
        chatForm.querySelector('[name="chat_id"]').value = payload.chat_id;

        try {
            const response = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const result = await response.json();
            if (!response.ok) {
                appendBubble("assistant", result.detail || "Chat request failed. Please try again.");
                return;
            }
            appendBubble("assistant", result.reply || "No response yet.");
            await loadChatSessions();
            setCurrentChatId(payload.chat_id);
        } catch (error) {
            appendBubble("assistant", "Chat service is temporarily unavailable. Please try again in a moment.");
        }
    });
}

if (uploadForm) {
    uploadForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const formData = new FormData(uploadForm);
        uploadResult.textContent = "Uploading and parsing your resume...";
        try {
            const response = await fetch("/api/upload/resume", {
                method: "POST",
                body: formData,
            });
            const result = await response.json();
            if (!response.ok) {
                uploadResult.textContent = result.detail || "Upload failed.";
                return;
            }
            uploadResult.textContent = result.message;
            appendBubble("assistant", result.message);
            await loadChatSessions();
        } catch (error) {
            uploadResult.textContent = "Upload service is temporarily unavailable. Please try again later.";
        }
    });
}

document.querySelectorAll(".example-btn").forEach((button) => {
    button.addEventListener("click", () => {
        if (!chatForm) return;
        const textarea = chatForm.querySelector('[name="message"]');
        textarea.value = button.dataset.text || "";
        textarea.focus();
    });
});

async function bootstrapChatPage() {
    try {
        const sessions = await loadChatSessions();
        if (sessions.length > 0) {
            const chatId = currentChatId || sessions[0]._id || sessions[0].id;
            setCurrentChatId(chatId);
            await loadChatMessages(chatId);
        }
    } catch (error) {
        appendBubble("assistant", "Failed to initialize chat sessions.");
    }
}

bootstrapChatPage();
