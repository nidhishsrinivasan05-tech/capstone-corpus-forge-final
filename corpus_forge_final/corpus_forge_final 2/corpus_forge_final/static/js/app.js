(function () {
    function onReady(callback) {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", callback);
        } else {
            callback();
        }
    }

    function initApp() {
        const prefersReduced = window.matchMedia &&
            window.matchMedia("(prefers-reduced-motion: reduce)").matches;

        const themeToggle = document.getElementById("theme-toggle");
        const body = document.body;

        function applyTheme(theme) {
            const safeTheme = theme === "black" ? "black" : "white";
            body.setAttribute("data-theme", safeTheme);
            if (themeToggle) {
                themeToggle.textContent = safeTheme === "black" ? "Theme: Black" : "Theme: White";
            }
        }

        applyTheme(localStorage.getItem("cf-theme") || "white");

        if (themeToggle) {
            themeToggle.addEventListener("click", () => {
                const current = body.getAttribute("data-theme") || "white";
                const next = current === "white" ? "black" : "white";
                applyTheme(next);
                localStorage.setItem("cf-theme", next);
            });
        }

        function getToastStack() {
            let stack = document.querySelector(".toast-stack");
            if (!stack) {
                stack = document.createElement("div");
                stack.className = "toast-stack";
                stack.setAttribute("aria-live", "polite");
                stack.setAttribute("aria-atomic", "true");
                document.body.appendChild(stack);
            }
            return stack;
        }

        function showToast(message, type = "success", timeout = 4600) {
            const stack = getToastStack();
            const toast = document.createElement("div");
            toast.className = `toast toast-${type}`;
            toast.setAttribute("role", "alert");

            const dot = document.createElement("span");
            dot.className = "toast-dot";

            const text = document.createElement("span");
            text.textContent = message;

            toast.appendChild(dot);
            toast.appendChild(text);
            stack.appendChild(toast);

            if (!prefersReduced) {
                window.setTimeout(() => hideToast(toast), timeout);
            }

            return toast;
        }

        function hideToast(toast) {
            toast.classList.add("is-hiding");
            toast.addEventListener("animationend", () => toast.remove(), { once: true });
        }

        function setLoadingState(button, isLoading, loadingText) {
            if (!button) return;

            if (isLoading) {
                button.dataset.originalText = button.textContent;
                button.textContent = loadingText || "Processing...";
                button.classList.add("loading");
                button.disabled = true;
            } else {
                button.textContent = button.dataset.originalText || button.textContent;
                button.classList.remove("loading");
                button.disabled = false;
            }
        }

        function setFormLoading(form, isLoading, loadingText) {
            if (!form) return;
            const button = form.querySelector('button[type="submit"], button[type="button"]');
            setLoadingState(button, isLoading, loadingText);

            form.querySelectorAll("input, select, textarea").forEach((element) => {
                element.disabled = isLoading;
            });
        }

        function valueOrZero(value) {
            return value === undefined || value === null ? 0 : value;
        }

        async function parseResponse(response) {
            const text = await response.text();
            if (!text) return {};

            try {
                return JSON.parse(text);
            } catch (error) {
                return { error: text };
            }
        }

        async function fetchWithFeedback(url, options = {}) {
            const loader = showToast("Refreshing dashboard...", "warning", 60000);
            try {
                const response = await fetch(url, options);
                const payload = await parseResponse(response);
                loader.remove();
                if (!response.ok) {
                    throw new Error(payload.error || `Request failed (${response.status})`);
                }
                return payload;
            } catch (error) {
                loader.remove();
                showToast(error.message || "Network error", "error");
                throw error;
            }
        }

        document.querySelectorAll(".toast").forEach((toast) => {
            if (!prefersReduced) {
                window.setTimeout(() => hideToast(toast), 5000);
            }
        });

        document.querySelectorAll(".file-drop input[type='file']").forEach((input) => {
            input.addEventListener("change", () => {
                const fileName = input.files && input.files.length ? input.files[0].name : "Choose a file";
                const label = input.closest(".file-drop");
                const strong = label ? label.querySelector("strong") : null;
                if (strong) {
                    strong.textContent = fileName;
                }
            });
        });

        document.querySelectorAll(".copy-artifact").forEach((button) => {
            button.addEventListener("click", async () => {
                const article = button.closest(".artifact");
                const content = article ? article.querySelector("pre") : null;
                if (!content || !navigator.clipboard) {
                    showToast("Clipboard is not available in this browser.", "warning");
                    return;
                }

                try {
                    await navigator.clipboard.writeText(content.textContent);
                    const original = button.textContent;
                    button.textContent = "Copied";
                    showToast("Artifact copied.", "success", 1600);
                    window.setTimeout(() => {
                        button.textContent = original;
                    }, 1600);
                } catch (error) {
                    showToast("Copy failed.", "error");
                }
            });
        });

        const answerPanel = document.getElementById("answer-panel");
        const assistantPanel = document.getElementById("assistant-chat");
        if (answerPanel) {
            answerPanel.scrollIntoView({
                behavior: prefersReduced ? "auto" : "smooth",
                block: "start",
            });
        } else if (assistantPanel && assistantPanel.querySelector(".assistant-chat-log")) {
            assistantPanel.scrollIntoView({
                behavior: prefersReduced ? "auto" : "smooth",
                block: "start",
            });
        }

        function setMetric(id, value) {
            const element = document.getElementById(id);
            if (element) {
                element.textContent = value;
            }
        }

        async function refreshStats() {
            const refreshButton = document.getElementById("refresh-stats");
            if (refreshButton) {
                refreshButton.disabled = true;
                refreshButton.classList.add("loading");
            }

            try {
                const payload = await fetchWithFeedback("/api/stats");
                const stats = payload.stats || {};
                const usage = payload.usage || {};
                setMetric("stat-documents", valueOrZero(stats.document_count));
                setMetric("stat-words", valueOrZero(stats.indexed_words));
                setMetric("stat-artifacts", valueOrZero(stats.artifact_count));
                setMetric("stat-requests", valueOrZero(usage.request_count));
                setMetric("stat-tokens", `${valueOrZero(usage.token_count)} est. tokens`);
                showToast("Dashboard stats refreshed.", "success", 1600);
            } finally {
                if (refreshButton) {
                    refreshButton.disabled = false;
                    refreshButton.classList.remove("loading");
                }
            }
        }

        const refreshButton = document.getElementById("refresh-stats");
        if (refreshButton) {
            refreshButton.addEventListener("click", refreshStats);
        }

        const sourceSelect = document.getElementById("source-select");
        const sourceLabel = document.getElementById("source-label");
        const uploadForm = document.getElementById("upload-form");
        const repoForm = document.getElementById("repo-form");
        const sourcePill = document.getElementById("source-toggle");

        function setSource(source) {
            if (sourceLabel) {
                sourceLabel.textContent = source === "github" ? "GitHub" : "Local";
            }

            if (!uploadForm || !repoForm) return;

            if (source === "github") {
                uploadForm.classList.remove("active-form");
                repoForm.classList.add("active-form");
                repoForm.style.display = "block";
            } else {
                uploadForm.classList.add("active-form");
                repoForm.classList.remove("active-form");
                repoForm.style.display = "none";
            }
        }

        if (sourceSelect) {
            setSource(sourceSelect.value);
            sourceSelect.addEventListener("change", (event) => {
                setSource(event.target.value);
            });
        }

        if (sourcePill && sourceSelect) {
            const toggleSource = () => {
                const next = sourceSelect.value === "local" ? "github" : "local";
                sourceSelect.value = next;
                sourceSelect.dispatchEvent(new Event("change"));
            };

            sourcePill.addEventListener("click", toggleSource);
            sourcePill.addEventListener("keydown", (event) => {
                if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    toggleSource();
                }
            });
        }

        if (uploadForm) {
            uploadForm.addEventListener("submit", (event) => {
                const fileInput = uploadForm.querySelector('input[type="file"]');
                if (!fileInput || !fileInput.files || !fileInput.files.length) {
                    event.preventDefault();
                    showToast("Choose a file before uploading.", "warning");
                    return;
                }

                const submitButton = uploadForm.querySelector('button[type="submit"]');
                setLoadingState(submitButton, true, "Uploading file...");
            });
        }

        const repoUrlInput = document.getElementById("repo_url");
        const githubTokenInput = document.getElementById("github_token");
        const repoStatus = document.getElementById("repo-status");

        function isValidGithubUrl(url) {
            try {
                const parsed = new URL(url);
                const pathParts = parsed.pathname.split("/").filter(Boolean);
                return parsed.hostname === "github.com" && pathParts.length >= 2;
            } catch (error) {
                return false;
            }
        }

        function setRepoStatus(message, type = "info") {
            if (!repoStatus) return;
            repoStatus.textContent = message;
            repoStatus.style.display = "block";
            repoStatus.className = `repo-status ${type}`;
        }

        if (repoForm) {
            repoForm.addEventListener("submit", async (event) => {
                event.preventDefault();

                const url = repoUrlInput ? repoUrlInput.value.trim() : "";
                const token = githubTokenInput ? githubTokenInput.value.trim() : "";

                if (!url) {
                    showToast("Enter a GitHub repository URL.", "error");
                    if (repoUrlInput) repoUrlInput.focus();
                    return;
                }

                if (!isValidGithubUrl(url)) {
                    showToast("Invalid GitHub URL. Use: https://github.com/owner/repo", "error");
                    if (repoUrlInput) repoUrlInput.focus();
                    return;
                }

                setFormLoading(repoForm, true, "Fetching repository...");
                setRepoStatus("Connecting to GitHub...", "fetching");

                try {
                    const formData = new FormData();
                    formData.append("repo_url", url);
                    if (token) {
                        formData.append("github_token", token);
                    }

                    const response = await fetch(repoForm.action, {
                        method: "POST",
                        body: formData,
                        headers: {
                            "X-Requested-With": "XMLHttpRequest",
                        },
                    });
                    const payload = await parseResponse(response);

                    if (!response.ok || payload.status === "error") {
                        const errorMessage = payload.error || `Request failed (${response.status})`;
                        setRepoStatus(errorMessage, "error");
                        showToast(errorMessage, "error");
                        return;
                    }

                    const count = payload.count || 0;
                    setRepoStatus(`Successfully imported ${count} files.`, "success");
                    showToast(`Imported ${count} files from repository.`, "success");

                    if (repoUrlInput) repoUrlInput.value = "";
                    if (githubTokenInput) githubTokenInput.value = "";

                    window.setTimeout(() => window.location.reload(), 1200);
                } catch (error) {
                    const errorMessage = error.message || "Network error. Check your connection.";
                    setRepoStatus(errorMessage, "error");
                    showToast(errorMessage, "error");
                    console.error("GitHub fetch error:", error);
                } finally {
                    setFormLoading(repoForm, false);
                }
            });
        }

        const assistantForm = document.getElementById("assistant-chat-form");
        if (assistantForm) {
            assistantForm.addEventListener("submit", (event) => {
                const message = assistantForm.querySelector('[name="assistant_message"]');
                if (!message || !message.value.trim()) {
                    event.preventDefault();
                    showToast("Enter a message before chatting.", "warning");
                    if (message) message.focus();
                    return;
                }

                const submitButton = assistantForm.querySelector('button[type="submit"]');
                setLoadingState(submitButton, true, "Asking assistant...");
            });
        }

        document.querySelectorAll(".btn-view-more").forEach((button) => {
            button.addEventListener("click", function () {
                const docRow = this.closest(".doc-row");
                if (!docRow) return;

                const fullPreview = docRow.querySelector(".doc-full-preview");
                const shortPreview = docRow.querySelector(".doc-short");
                const isExpanded = fullPreview ? fullPreview.style.display !== "none" : false;

                if (!fullPreview) return;

                if (isExpanded) {
                    fullPreview.style.display = "none";
                    if (shortPreview) shortPreview.style.display = "";
                    this.textContent = "View more";
                    this.setAttribute("aria-expanded", "false");
                    this.classList.remove("expanded");
                } else {
                    fullPreview.style.display = "block";
                    if (shortPreview) shortPreview.style.display = "none";
                    this.textContent = "Show less";
                    this.setAttribute("aria-expanded", "true");
                    this.classList.add("expanded");
                }
            });
        });

        document.querySelectorAll(".doc-delete-form").forEach((form) => {
            form.addEventListener("submit", function (event) {
                const message = this.dataset.confirm;
                if (message && !window.confirm(message)) {
                    event.preventDefault();
                    return;
                }

                const button = this.querySelector("button");
                setLoadingState(button, true, "Removing...");
            });
        });

        window.CorpusForge = {
            showToast,
            hideToast,
            fetchWithFeedback,
            setLoadingState,
            refreshStats,
            isValidGithubUrl,
        };
    }

    onReady(initApp);
})();
