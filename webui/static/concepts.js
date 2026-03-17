/**
 * Learning Agent — Concepts Tab Interactivity
 * Handles: search, topic filter, status filter, sortable columns, delete with modal.
 * Zero dependencies — vanilla JS.
 */
(function () {
  "use strict";

  // ── State ──────────────────────────────────────────────────────────
  const STORAGE_KEY = "learning_concepts_state";
  let concepts = window.__CONCEPTS || [];
  let topics = window.__TOPICS || [];
  let state = loadState();
  let deleteTarget = null;   // {id, title} of concept pending deletion
  let deleteInFlight = false;

  function defaultState() {
    return {
      search: "",
      topicId: "",
      status: "all",
      sortField: "next_review_at",
      sortDir: "asc",
    };
  }

  function loadState() {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      return raw ? Object.assign(defaultState(), JSON.parse(raw)) : defaultState();
    } catch { return defaultState(); }
  }

  function saveState() {
    try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch {}
  }

  // ── Helpers ────────────────────────────────────────────────────────

  function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
              .replace(/"/g, "&quot;");
  }

  function nowIso() {
    const d = new Date();
    const pad = n => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  function formatRelative(dateStr) {
    if (!dateStr) return "—";
    // Normalise space-separated DB format to ISO T-format (required for Safari)
    const d = new Date(dateStr.replace(" ", "T"));
    if (isNaN(d)) return dateStr;
    const now = new Date();
    const diffMs = d - now;
    const diffDays = Math.round(diffMs / 86400000);
    if (diffDays < 0) {
      const over = Math.abs(diffDays);
      return over === 0 ? "Today" : `Overdue ${over}d`;
    }
    if (diffDays === 0) return "Today";
    if (diffDays === 1) return "Tomorrow";
    if (diffDays <= 30) return `in ${diffDays}d`;
    const months = Math.round(diffDays / 30);
    return `in ~${months}mo`;
  }

  // For past-only dates (e.g. last reviewed): "3d ago", "today", "never"
  function formatAgo(dateStr) {
    if (!dateStr) return "—";
    const d = new Date(dateStr.replace(" ", "T"));
    if (isNaN(d)) return dateStr;
    const now = new Date();
    const diffDays = Math.round((now - d) / 86400000);
    if (diffDays <= 0) return "Today";
    if (diffDays === 1) return "Yesterday";
    if (diffDays <= 30) return `${diffDays}d ago`;
    const months = Math.round(diffDays / 30);
    return `~${months}mo ago`;
  }

  function scoreBarHtml(score) {
    score = Math.max(0, Math.min(100, parseInt(score) || 0));
    let cls = "low";
    if (score >= 75) cls = "mastered";
    else if (score >= 50) cls = "filled";
    else if (score >= 25) cls = "mid";
    return `<span class="mastery-bar" title="Score: ${score}/100"><span class="score-fill ${cls}" style="width:${score}%"></span><span class="score-label">${score}</span></span>`;
  }

  // ── Filtering ──────────────────────────────────────────────────────

  function filterConcepts() {
    const q = state.search.toLowerCase();
    const topicId = state.topicId ? parseInt(state.topicId) : null;
    const now = nowIso();

    return concepts.filter(c => {
      // Text search — title, topic names, and remark
      if (q) {
        const inTitle  = (c.title || "").toLowerCase().includes(q);
        const inTopics = (c.topics || []).some(t => (t.title || "").toLowerCase().includes(q));
        const inRemark = (c.latest_remark || "").toLowerCase().includes(q);
        if (!inTitle && !inTopics && !inRemark) return false;
      }

      // Topic filter (by ID — no substring false matches)
      if (topicId) {
        const hasT = (c.topics || []).some(t => t.id === topicId);
        if (!hasT) return false;
      }

      // Status filter
      if (state.status === "due") {
        if (!c.next_review_at || c.next_review_at > now) return false;
      } else if (state.status === "upcoming") {
        if (!c.next_review_at || c.next_review_at <= now) return false;
      } else if (state.status === "never") {
        if (c.review_count !== 0) return false;
      }

      return true;
    });
  }

  // ── Sorting ────────────────────────────────────────────────────────

  function sortConcepts(list) {
    const field = state.sortField;
    const dir = state.sortDir === "asc" ? 1 : -1;

    return list.slice().sort((a, b) => {
      let va = a[field];
      let vb = b[field];

      // Nulls always last regardless of direction
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;

      // String comparison for title
      if (field === "title") {
        return dir * va.localeCompare(vb, undefined, { sensitivity: "base" });
      }

      // Numeric/string comparison for other fields
      if (va < vb) return -1 * dir;
      if (va > vb) return 1 * dir;
      return 0;
    });
  }

  // ── Rendering ──────────────────────────────────────────────────────

  function renderTable() {
    const filtered = filterConcepts();
    const sorted = sortConcepts(filtered);
    const tbody = document.getElementById("concepts-body");
    const emptyEl = document.getElementById("concepts-empty");
    const countEl = document.getElementById("concepts-count");

    if (countEl) {
      const total = concepts.length;
      if (filtered.length === total) {
        countEl.textContent = `(${total})`;
      } else {
        countEl.textContent = `(${filtered.length} of ${total})`;
      }
    }

    if (sorted.length === 0) {
      tbody.innerHTML = "";
      if (concepts.length === 0) {
        emptyEl.textContent = "No concepts yet — start a learning session in Discord to add your first one.";
      } else if (state.status === "never") {
        emptyEl.textContent = "No new concepts — all have been reviewed at least once.";
      } else {
        emptyEl.textContent = "No concepts match your current filters.";
      }
      emptyEl.style.display = "";
      return;
    }
    emptyEl.style.display = "none";

    const now = nowIso();
    let html = "";
    for (const c of sorted) {
      // Topic tags — include data-topic-id for in-place filter
      let tags = "";
      if (c.topics && c.topics.length > 0) {
        tags = c.topics.map(t =>
          `<a href="/topic/${t.id}" class="tag tag-filter" data-topic-id="${t.id}">${escapeHtml(t.title)}</a>`
        ).join("");
      } else {
        tags = '<span style="color:var(--text2)">untagged</span>';
      }

      // Due badge
      const isDue = !!(c.next_review_at && c.next_review_at <= now);
      const due = isDue ? ' <span class="badge due">DUE</span>' : "";

      // Remark preview (truncated)
      const remark = c.latest_remark
        ? escapeHtml(c.latest_remark.length > 60 ? c.latest_remark.slice(0, 60) + "…" : c.latest_remark)
        : "";

      // Interval: hide for never-reviewed concepts
      const intervalCell = c.review_count > 0 ? `${c.interval_days || 1}d` : "—";

      html += `<tr data-id="${c.id}"${isDue ? ' data-due="true"' : ''}>
        <td><a href="/concept/${c.id}">#${c.id}</a></td>
        <td class="td-title"><a href="/concept/${c.id}" title="${escapeHtml(c.title)}">${escapeHtml(c.title)}</a>${remark ? `<div class="concept-remark-preview">${remark}</div>` : ""}</td>
        <td>${tags}</td>
        <td>${scoreBarHtml(c.mastery_level)}</td>
        <td>${intervalCell}</td>
        <td>${c.review_count || 0}</td>
        <td title="${c.next_review_at || ''}">${formatRelative(c.next_review_at)}${due}</td>
        <td title="${c.last_reviewed_at || ''}">${formatAgo(c.last_reviewed_at)}</td>
        <td><button class="btn-delete" data-id="${c.id}" data-title="${escapeHtml(c.title)}" data-reviews="${c.review_count || 0}" title="Delete concept"><svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M5.5 5.5A.5.5 0 0 1 6 6v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5zm2.5 0a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5zm3 .5a.5.5 0 0 0-1 0v6a.5.5 0 0 0 1 0V6z"/><path fill-rule="evenodd" d="M14.5 3a1 1 0 0 1-1 1H13v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4h-.5a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1H5.5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1h2a1 1 0 0 1 1 1v1zM4.118 4L4 4.059V13a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V4.059L11.882 4H4.118zM2.5 3V2h11v1h-11z"/></svg></button></td>
      </tr>`;
    }
    tbody.innerHTML = html;

    // Attach delete handlers
    tbody.querySelectorAll(".btn-delete").forEach(btn => {
      btn.addEventListener("click", e => {
        e.preventDefault();
        e.stopPropagation();
        openDeleteModal(
          parseInt(btn.dataset.id),
          btn.dataset.title,
          parseInt(btn.dataset.reviews) || 0
        );
      });
    });
  }

  function updateSortIndicators() {
    document.querySelectorAll("#concepts-table th.sortable").forEach(th => {
      th.classList.remove("sort-asc", "sort-desc");
      if (th.dataset.sort === state.sortField) {
        th.classList.add(state.sortDir === "asc" ? "sort-asc" : "sort-desc");
      }
    });
  }

  // ── Delete Modal ───────────────────────────────────────────────────

  function openDeleteModal(id, title, reviewCount) {
    deleteTarget = { id, title };
    const modal = document.getElementById("delete-modal");
    const msg = document.getElementById("delete-modal-msg");

    let warning = `Are you sure you want to delete <strong>${escapeHtml(title)}</strong>?`;
    if (reviewCount > 0) {
      warning += `<br><span style="color:var(--text2);font-size:13px">This will permanently remove ${reviewCount} review${reviewCount > 1 ? "s" : ""} and all remarks.</span>`;
    } else {
      warning += `<br><span style="color:var(--text2);font-size:13px">This action cannot be undone.</span>`;
    }
    msg.innerHTML = warning;

    modal.style.display = "";
    const confirmBtn = document.getElementById("delete-confirm");
    confirmBtn.disabled = false;
    confirmBtn.textContent = "Delete";

    // Trap focus
    setTimeout(() => document.getElementById("delete-cancel").focus(), 50);
  }

  function closeDeleteModal() {
    document.getElementById("delete-modal").style.display = "none";
    deleteTarget = null;
  }

  async function executeDelete() {
    if (!deleteTarget || deleteInFlight) return;
    deleteInFlight = true;

    const confirmBtn = document.getElementById("delete-confirm");
    confirmBtn.disabled = true;
    confirmBtn.textContent = "Deleting…";

    try {
      const res = await fetch(`/api/concept/${deleteTarget.id}/delete`, {
        method: "POST",
        headers: { "X-Requested-With": "fetch" },
      });
      const data = await res.json();

      if (data.ok) {
        // Remove from local data
        concepts = concepts.filter(c => c.id !== deleteTarget.id);
        showToast(`Deleted "${deleteTarget.title}"`, "success");
        closeDeleteModal();
        renderTable();
      } else {
        showToast(data.error || "Delete failed", "error");
        closeDeleteModal();
      }
    } catch (err) {
      showToast("Network error: " + err.message, "error");
      closeDeleteModal();
    } finally {
      deleteInFlight = false;
    }
  }

  // ── Toast Notifications ────────────────────────────────────────────

  function showToast(message, type) {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    // Trigger animation
    requestAnimationFrame(() => toast.classList.add("show"));

    const duration = type === "error" ? 6000 : 3000;
    setTimeout(() => {
      toast.classList.remove("show");
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }

  // ── Init ───────────────────────────────────────────────────────────

  function init() {
    // Populate topic filter dropdown
    const topicSelect = document.getElementById("concept-topic-filter");
    if (topicSelect) {
      topics.forEach(t => {
        const opt = document.createElement("option");
        opt.value = t.id;
        opt.textContent = t.title;
        topicSelect.appendChild(opt);
      });
      topicSelect.value = state.topicId || "";
      topicSelect.addEventListener("change", () => {
        state.topicId = topicSelect.value;
        saveState();
        renderTable();
      });
    }

    // Search input + clear button
    const searchInput = document.getElementById("concept-search");
    const clearBtn = document.getElementById("search-clear");

    function updateClearBtn() {
      if (clearBtn) clearBtn.style.display = searchInput.value ? "block" : "none";
    }

    if (searchInput) {
      searchInput.value = state.search || "";
      updateClearBtn();
      let debounce = null;
      searchInput.addEventListener("input", () => {
        updateClearBtn();
        clearTimeout(debounce);
        debounce = setTimeout(() => {
          state.search = searchInput.value.trim();
          saveState();
          renderTable();
        }, 150);
      });
      searchInput.addEventListener("keydown", e => {
        if (e.key === "Escape") {
          searchInput.value = "";
          updateClearBtn();
          state.search = "";
          saveState();
          renderTable();
        }
      });
    }
    if (clearBtn) {
      clearBtn.addEventListener("click", () => {
        searchInput.value = "";
        updateClearBtn();
        state.search = "";
        saveState();
        renderTable();
        searchInput.focus();
      });
    }

    // Status filter buttons
    const statusGroup = document.getElementById("status-filter");
    if (statusGroup) {
      // Restore active state
      statusGroup.querySelectorAll(".filter-btn").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.status === state.status);
        btn.addEventListener("click", () => {
          statusGroup.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
          btn.classList.add("active");
          state.status = btn.dataset.status;
          saveState();
          renderTable();
        });
      });
    }

    // Sortable column headers
    const SORT_DEFAULTS = {
      mastery_level: "desc", review_count: "desc",
      interval_days: "desc", last_reviewed_at: "desc",
      title: "asc", id: "asc", next_review_at: "asc",
    };
    document.querySelectorAll("#concepts-table th.sortable").forEach(th => {
      th.addEventListener("click", () => {
        const field = th.dataset.sort;
        if (state.sortField === field) {
          state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
        } else {
          state.sortField = field;
          state.sortDir = SORT_DEFAULTS[field] ?? "asc";
        }
        saveState();
        updateSortIndicators();
        renderTable();
      });
    });

    // Topic tag in-place filter (event delegation on static table element)
    const conceptsTable = document.getElementById("concepts-table");
    if (conceptsTable) {
      conceptsTable.addEventListener("click", e => {
        const tag = e.target.closest(".tag-filter");
        if (!tag) return;
        // Allow Ctrl/Meta/middle-click to navigate normally
        if (e.ctrlKey || e.metaKey || e.button === 1) return;
        e.preventDefault();
        const id = tag.dataset.topicId;
        // Toggle off if same topic already active
        state.topicId = (state.topicId === id) ? "" : id;
        const dropdown = document.getElementById("concept-topic-filter");
        if (dropdown) dropdown.value = state.topicId;
        saveState();
        renderTable();
      });
    }

    // Delete modal events
    const modal = document.getElementById("delete-modal");
    const cancelBtn = document.getElementById("delete-cancel");
    const confirmBtn = document.getElementById("delete-confirm");

    if (cancelBtn) cancelBtn.addEventListener("click", closeDeleteModal);
    if (confirmBtn) confirmBtn.addEventListener("click", executeDelete);

    // Backdrop click closes modal
    if (modal) {
      modal.addEventListener("click", e => {
        if (e.target === modal) closeDeleteModal();
      });
    }

    // Escape closes modal
    document.addEventListener("keydown", e => {
      if (e.key === "Escape" && modal && modal.style.display !== "none") {
        closeDeleteModal();
      }
    });

    // Tab key trapping inside modal
    if (modal) {
      modal.addEventListener("keydown", e => {
        if (e.key !== "Tab") return;
        const focusable = modal.querySelectorAll("button:not([disabled])");
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      });
    }

    // Initial render
    updateSortIndicators();
    renderTable();
  }

  // Run on DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
