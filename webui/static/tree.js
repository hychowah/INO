/**
 * Learning Agent — Topic Tree Interactivity
 * Handles: expand/collapse, search/filter, keyboard nav, state persistence.
 * Zero dependencies — vanilla JS.
 */
(function () {
  "use strict";

  // ── State ──────────────────────────────────────────────────────────
  const STORAGE_KEY = "learning_tree_expanded";

  function loadExpanded() {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      return raw ? new Set(JSON.parse(raw)) : null;
    } catch { return null; }
  }

  function saveExpanded() {
    const ids = [];
    document.querySelectorAll(".tree-node.expanded").forEach(n => {
      if (n.dataset.id) ids.push(n.dataset.id);
    });
    try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(ids)); } catch {}
  }

  // ── Expand / Collapse ─────────────────────────────────────────────

  function toggleNode(node) {
    if (!node.querySelector(":scope > .tree-node-children")) return;
    node.classList.toggle("expanded");
    node.classList.toggle("collapsed");
    saveExpanded();
  }

  function expandAll() {
    document.querySelectorAll(".tree-node.collapsed").forEach(n => {
      if (n.querySelector(":scope > .tree-node-children")) {
        n.classList.remove("collapsed");
        n.classList.add("expanded");
      }
    });
    saveExpanded();
  }

  function collapseAll() {
    document.querySelectorAll(".tree-node.expanded").forEach(n => {
      n.classList.remove("expanded");
      n.classList.add("collapsed");
    });
    saveExpanded();
  }

  // Apply saved expand state on load
  function restoreExpandState() {
    const saved = loadExpanded();
    if (!saved) {
      // Default: expand root nodes only
      document.querySelectorAll(".topic-tree > .tree-node").forEach(n => {
        if (n.querySelector(":scope > .tree-node-children")) {
          n.classList.remove("collapsed");
          n.classList.add("expanded");
        }
      });
      return;
    }
    document.querySelectorAll(".tree-node").forEach(n => {
      if (!n.querySelector(":scope > .tree-node-children")) return;
      if (saved.has(n.dataset.id)) {
        n.classList.remove("collapsed");
        n.classList.add("expanded");
      } else {
        n.classList.remove("expanded");
        n.classList.add("collapsed");
      }
    });
  }

  // ── Search / Filter ───────────────────────────────────────────────

  function filterTree(query) {
    const nodes = document.querySelectorAll(".tree-node");
    const counter = document.getElementById("tree-match-count");

    if (!query) {
      // Clear filter
      nodes.forEach(n => {
        n.classList.remove("search-hidden", "search-match", "search-ancestor");
      });
      if (counter) counter.textContent = "";
      return;
    }

    const q = query.toLowerCase();
    let matchCount = 0;

    // Pass 1: mark matches
    nodes.forEach(n => {
      const title = (n.dataset.title || "").toLowerCase();
      const isMatch = title.includes(q);
      n.classList.toggle("search-match", isMatch);
      n.classList.remove("search-hidden", "search-ancestor");
      if (isMatch) matchCount++;
    });

    // Pass 2: mark ancestors of matches
    document.querySelectorAll(".tree-node.search-match").forEach(n => {
      let parent = n.parentElement;
      while (parent) {
        if (parent.classList && parent.classList.contains("tree-node")) {
          parent.classList.add("search-ancestor");
        }
        parent = parent.parentElement;
      }
    });

    // Pass 3: hide non-matching, non-ancestor nodes
    nodes.forEach(n => {
      if (!n.classList.contains("search-match") && !n.classList.contains("search-ancestor")) {
        n.classList.add("search-hidden");
      }
    });

    if (counter) {
      counter.textContent = matchCount > 0 ? `${matchCount} match${matchCount > 1 ? "es" : ""}` : "no matches";
    }
  }

  // ── Init ───────────────────────────────────────────────────────────

  function init() {
    // Chevron click → toggle
    document.querySelectorAll(".tree-node .chevron").forEach(ch => {
      ch.addEventListener("click", e => {
        e.stopPropagation();
        const node = ch.closest(".tree-node");
        if (node) toggleNode(node);
      });
    });

    // Expand All / Collapse All buttons
    const btnExpand = document.getElementById("tree-expand-all");
    const btnCollapse = document.getElementById("tree-collapse-all");
    if (btnExpand) btnExpand.addEventListener("click", expandAll);
    if (btnCollapse) btnCollapse.addEventListener("click", collapseAll);

    // Search input
    const searchInput = document.getElementById("tree-search");
    if (searchInput) {
      let debounce = null;
      searchInput.addEventListener("input", () => {
        clearTimeout(debounce);
        debounce = setTimeout(() => filterTree(searchInput.value.trim()), 150);
      });
      // Escape clears search
      searchInput.addEventListener("keydown", e => {
        if (e.key === "Escape") {
          searchInput.value = "";
          filterTree("");
        }
      });
    }

    // Restore expand/collapse state
    restoreExpandState();
  }

  // Run on DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
