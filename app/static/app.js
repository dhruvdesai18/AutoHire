function showToast(message, type = "info") {
    let container = document.getElementById("toast-container");
    if (!container) {
        container = document.createElement("div");
        container.id = "toast-container";
        container.className = "toast-container";
        document.body.appendChild(container);
    }

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add("toast-out");
        setTimeout(() => toast.remove(), 200);
    }, 3500);
}

function skeletonLines(widths) {
    return widths.map((w) => `<div class="skeleton-line w-${w}"></div>`).join("");
}
