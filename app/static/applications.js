const applicationForm = document.getElementById("application-form");
const applicationFormResult = document.getElementById("application-form-result");

if (applicationForm) {
    applicationForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const formData = new FormData(applicationForm);
        const payload = Object.fromEntries(formData.entries());
        applicationFormResult.textContent = "正在新增记录...";
        const response = await fetch("/api/applications", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
        });
        const result = await response.json();
        if (!response.ok) {
            applicationFormResult.textContent = result.detail || "新增失败";
            return;
        }
        applicationFormResult.textContent = `已新增：${result.company} / ${result.position}`;
        window.location.reload();
    });
}

document.querySelectorAll(".inline-status-form").forEach((form) => {
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const applicationId = form.dataset.id;
        const formData = new FormData(form);
        const payload = Object.fromEntries(formData.entries());
        const response = await fetch(`/api/applications/${applicationId}/status`, {
            method: "PATCH",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
        });
        if (response.ok) {
            window.location.reload();
            return;
        }
        const result = await response.json();
        alert(result.detail || "更新失败");
    });
});

