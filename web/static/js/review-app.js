// Recon Keyboard-First Review App Engine
(function() {
  let demoData = null;
  let activeIndex = 0;
  let activeCandidateIndex = 0;
  let decisionsHistory = [];
  let decisionTimestamps = [];
  let rejectTarget = null;
  let lastFocusedElement = null;

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, ch => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    })[ch]);
  }

  async function loadDemo() {
    try {
      const res = await fetch("/api/demo");
      if (!res.ok) throw new Error("Failed to load demo data");
      demoData = await res.json();
      decisionsHistory = demoData.decisions || [];
      renderAll();
    } catch (err) {
      console.error(err);
      const center = document.getElementById("worklist-container");
      if (center) {
        center.innerHTML = `<div class="card"><p style="color:var(--danger)">Error loading demo data: ${esc(err.message)}</p></div>`;
      }
    }
  }

  function getActiveStatement() {
    if (!demoData || !demoData.statement || demoData.statement.length === 0) return null;
    return demoData.statement[activeIndex];
  }

  function undoneDecisionIds() {
    const undone = new Set();
    decisionsHistory.forEach(dec => {
      if (dec.action === "undo" && dec.target_decision_id != null) {
        undone.add(dec.target_decision_id);
      }
    });
    return undone;
  }

  function getStatementDecision(stmtId) {
    // Find the latest still-active decision for this statement line.
    // Undo rows are markers, not decisions; rows they target are void.
    const undone = undoneDecisionIds();
    for (let i = decisionsHistory.length - 1; i >= 0; i--) {
      const dec = decisionsHistory[i];
      if (dec.stmt_line_id !== stmtId) continue;
      if (dec.action === "undo") continue;
      if (dec.id != null && undone.has(dec.id)) continue;
      return dec;
    }
    return null;
  }

  function renderMetrics() {
    const total = demoData ? demoData.statement.length : 0;
    let accepted = 0;
    let rejected = 0;
    let unmatched = 0;

    let completed = 0;
    if (demoData && demoData.statement) {
      demoData.statement.forEach(stmt => {
        const decision = getStatementDecision(stmt.id);
        if (!decision) return;
        completed++;
        if (decision.action === "accept") accepted++;
        else if (decision.action === "reject") rejected++;
        else if (decision.action === "unmatch") unmatched++;
      });
    }

    const pct = total > 0 ? Math.round((completed / total) * 100) : 0;

    const progressFill = document.getElementById("app-progress-fill");
    const progressText = document.getElementById("app-progress-text");
    const countAccepted = document.getElementById("stat-accepted");
    const countRejected = document.getElementById("stat-rejected");
    const countUnmatched = document.getElementById("stat-unmatched");
    const paceElem = document.getElementById("stat-pace");
    const etaElem = document.getElementById("stat-eta");
    const stmtCountElem = document.getElementById("stmt-count");
    const ledgerCountElem = document.getElementById("ledger-count");

    if (progressFill) progressFill.style.width = `${pct}%`;
    if (progressText) progressText.textContent = `${completed}/${total} (${pct}%)`;
    if (countAccepted) countAccepted.textContent = accepted;
    if (countRejected) countRejected.textContent = rejected;
    if (countUnmatched) countUnmatched.textContent = unmatched;
    if (stmtCountElem) stmtCountElem.textContent = `${total} Rows`;
    if (ledgerCountElem) {
      const ledgerTotal = demoData && demoData.ledger ? demoData.ledger.length : 0;
      ledgerCountElem.textContent = `${ledgerTotal} Rows`;
    }

    // Rolling decisions per minute
    const now = Date.now();
    decisionTimestamps = decisionTimestamps.filter(t => now - t <= 60000);
    const pace = decisionTimestamps.length; // decisions in past minute

    const remainingRows = Math.max(0, total - completed);
    let etaText = "Done";
    if (remainingRows > 0) {
      // No fabricated pace: only estimate once we have measured decisions.
      etaText = pace > 0 ? `~${(remainingRows / pace).toFixed(1)}m left` : "—";
    }

    if (paceElem) paceElem.textContent = `${pace} /min`;
    if (etaElem) etaElem.textContent = etaText;
  }

  function renderStatementList() {
    const container = document.getElementById("statement-list");
    if (!container || !demoData) return;

    container.innerHTML = "";
    demoData.statement.forEach((stmt, idx) => {
      const decision = getStatementDecision(stmt.id);
      const div = document.createElement("div");
      let statusClass = "";
      if (decision) {
        statusClass = ` decided-${decision.action}`;
      }
      div.className = `stmt-item${idx === activeIndex ? " active" : ""}${statusClass}`;
      div.dataset.index = idx;

      const paise = stmt.amount_paise || 0;
      const rupees = (paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 });
      const dirClass = stmt.direction === "debit" ? "debit" : "credit";

      const topCand = stmt.candidates && stmt.candidates[0];
      let bandBadge = "";
      if (topCand) {
        if (topCand.band === "auto_suggest") {
          bandBadge = `<span class="badge badge-auto" style="font-size:0.65rem;">Auto ${esc(topCand.score)}%</span>`;
        } else if (topCand.band === "review") {
          bandBadge = `<span class="badge badge-review" style="font-size:0.65rem;">Review ${esc(topCand.score)}%</span>`;
        }
      } else {
        bandBadge = `<span class="badge badge-unmatched" style="font-size:0.65rem;">Unmatched</span>`;
      }

      div.innerHTML = `
        <div class="stmt-item-header">
          <span class="stmt-amount ${esc(dirClass)}">₹${esc(rupees)}</span>
          <span class="stmt-date">${esc(stmt.date_iso || "")}</span>
        </div>
        <div class="stmt-narration">${esc(stmt.text_norm || "")}</div>
        <div style="margin-top:0.35rem; display:flex; justify-content:space-between; align-items:center;">
          <span style="font-family:var(--font-mono); font-size:0.7rem; color:var(--slate-500);">${esc(stmt.id)}</span>
          ${bandBadge}
        </div>
      `;

      div.addEventListener("click", () => {
        activeIndex = idx;
        activeCandidateIndex = 0;
        renderAll();
      });

      container.appendChild(div);
    });

    // Keep active row visible in scroll viewport
    const activeEl = container.querySelector(".stmt-item.active");
    if (activeEl) {
      activeEl.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }

  function renderWorklist() {
    const container = document.getElementById("worklist-container");
    if (!container || !demoData) return;

    const stmt = getActiveStatement();
    if (!stmt) {
      container.innerHTML = `<div class="card"><p>No statement line selected.</p></div>`;
      return;
    }

    const decision = getStatementDecision(stmt.id);
    const paise = stmt.amount_paise || 0;
    const rupees = (paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 });
    const dirClass = stmt.direction === "debit" ? "debit" : "credit";

    let decisionNotice = "";
    if (decision) {
      const actColor = decision.action === "accept" ? "var(--success)" : decision.action === "reject" ? "var(--danger)" : "var(--slate-600)";
      decisionNotice = `
        <div style="background:#fff; border:2px solid ${actColor}; border-radius:var(--radius); padding:0.75rem 1rem; display:flex; justify-content:space-between; align-items:center;">
          <div>
            <strong>Decided:</strong> <span style="text-transform:uppercase; font-weight:700; color:${actColor}">${esc(decision.action)}</span>
            ${decision.reason ? ` · <span style="color:var(--slate-600);">${esc(decision.reason)}</span>` : ""}
          </div>
          <button class="btn btn-outline btn-sm" id="btn-undo-decision"><span class="kbd">Ctrl+Z</span> Undo</button>
        </div>
      `;
    }

    const candidates = stmt.candidates || [];
    let candidatesHtml = "";

    if (candidates.length === 0) {
      candidatesHtml = `
        <div class="card" style="text-align:center; padding:2.5rem 1.5rem;">
          <div style="font-size:2rem; margin-bottom:0.5rem; color:var(--slate-400);">∅</div>
          <h4 style="font-size:1.05rem; margin-bottom:0.4rem;">No Candidate Matches</h4>
          <p style="font-size:0.88rem; color:var(--slate-600); margin-bottom:1.25rem;">
            No ledger entries matched direction, date window (±30d), and amount tolerance.
          </p>
          <button class="btn btn-primary" id="btn-mark-unmatched"><span class="kbd">U</span> Mark as Unmatched</button>
        </div>
      `;
    } else {
      candidatesHtml = candidates.map((cand, idx) => {
        const isSelected = idx === activeCandidateIndex;
        const isAuto = cand.band === "auto_suggest";
        const scoreClass = isAuto ? "auto" : cand.band === "review" ? "review" : "unmatched";
        const comp = cand.comp || {};

        const ledgerItems = cand.ledger_line_ids.map(lid => {
          const lObj = demoData.ledger.find(l => l.id === lid);
          if (!lObj) return `<span>${esc(lid)}</span>`;
          const lRupees = ((lObj.amount_paise || 0) / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 });
          return `
            <div style="background:#fff; border:1px solid var(--slate-200); padding:0.5rem 0.75rem; border-radius:4px; margin-top:0.35rem; display:flex; justify-content:space-between;">
              <div><strong>${esc(lObj.id)}</strong>: ${esc(lObj.text_norm || "")}</div>
              <div style="font-family:var(--font-mono); font-weight:600;">₹${esc(lRupees)} (${esc(lObj.date_iso)})</div>
            </div>
          `;
        }).join("");

        return `
          <div class="candidate-card${isAuto ? " auto-band" : ""}${isSelected ? " selected" : ""}" data-cand-idx="${idx}">
            <div class="score-banner">
              <div class="score-display">
                <span class="score-number ${scoreClass}">${esc(cand.score)}</span>
                <span style="font-size:0.85rem; color:var(--slate-500); font-family:var(--font-mono);">/ 100</span>
                <span class="badge badge-${scoreClass === "auto" ? "auto" : "review"}">
                  ${isAuto ? "★ Auto-Suggest" : "Review"}
                </span>
                <span class="badge" style="background:var(--slate-200); color:var(--slate-800);">Tier ${esc(cand.tier)}</span>
              </div>
              <div style="font-size:0.8rem; color:var(--slate-500);">
                Candidate ${idx + 1} of ${candidates.length} <span class="kbd">Tab</span>
              </div>
            </div>

            <div class="reason-box">
              <strong>Match explanation:</strong> ${esc(cand.reason || "Score calculated based on amount, date, and reference.")}
            </div>

            <div class="candidate-components">
              <div class="comp-item">
                <span style="color:var(--slate-500);">Amount (45)</span>
                <strong>${Number(comp.amount ?? 0).toFixed(1)} pts</strong>
              </div>
              <div class="comp-item">
                <span style="color:var(--slate-500);">Date (25)</span>
                <strong>${Number(comp.date ?? 0).toFixed(1)} pts</strong>
              </div>
              <div class="comp-item">
                <span style="color:var(--slate-500);">Ref (20)</span>
                <strong>${Number(comp.reference ?? 0).toFixed(1)} pts</strong>
              </div>
              <div class="comp-item">
                <span style="color:var(--slate-500);">Narration (10)</span>
                <strong>${Number(comp.narration ?? 0).toFixed(1)} pts</strong>
              </div>
            </div>

            <div style="margin: 0.75rem 0;">
              <span style="font-size:0.75rem; text-transform:uppercase; font-weight:700; color:var(--slate-500);">
                Matched Ledger Entry (${cand.ledger_line_ids.length} line${cand.ledger_line_ids.length > 1 ? "s" : ""})
              </span>
              ${ledgerItems}
            </div>

            <div class="candidate-actions">
              <button class="btn btn-success btn-sm btn-action-accept" data-cand-idx="${idx}">
                <span class="kbd">Enter</span> Accept Match
              </button>
              <button class="btn btn-outline btn-sm btn-action-reject" data-cand-idx="${idx}">
                <span class="kbd">R</span> Reject
              </button>
              <button class="btn btn-outline btn-sm btn-action-unmatched">
                <span class="kbd">U</span> Mark Unmatched
              </button>
            </div>
          </div>
        `;
      }).join("");
    }

    container.innerHTML = `
      ${decisionNotice}
      <div class="card" style="border-left:4px solid var(--accent);">
        <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:0.5rem;">
          <span style="font-family:var(--font-mono); font-size:0.8rem; color:var(--slate-500);">Statement Line: ${esc(stmt.id)}</span>
          <span style="font-family:var(--font-mono); font-weight:700; font-size:1.25rem;" class="${esc(dirClass)}">₹${esc(rupees)}</span>
        </div>
        <div style="font-size:0.95rem; font-weight:500; margin-bottom:0.5rem;">${esc(stmt.text_norm || "")}</div>
        <div style="display:flex; gap:1.5rem; font-size:0.8rem; color:var(--slate-500); font-family:var(--font-mono);">
          <span>Date: ${esc(stmt.date_iso)}</span>
          <span>Direction: ${esc(stmt.direction)}</span>
          <span>Ref: ${esc(stmt.ref_token || "None")}</span>
        </div>
      </div>

      <div style="display:flex; justify-content:space-between; align-items:center; margin-top:0.25rem;">
        <h4 style="font-size:0.9rem; font-weight:700; text-transform:uppercase; letter-spacing:0.04em; color:var(--slate-700);">
          Candidate Proposals (${candidates.length})
        </h4>
        <span style="font-size:0.8rem; color:var(--slate-500);">
          Navigate lines: <span class="kbd">J</span> / <span class="kbd">K</span>
        </span>
      </div>

      ${candidatesHtml}
    `;

    // Bind event handlers
    const acceptBtns = container.querySelectorAll(".btn-action-accept");
    acceptBtns.forEach(btn => {
      btn.addEventListener("click", () => {
        const cIdx = parseInt(btn.dataset.candIdx, 10);
        acceptCandidate(cIdx);
      });
    });

    const rejectBtns = container.querySelectorAll(".btn-action-reject");
    rejectBtns.forEach(btn => {
      btn.addEventListener("click", () => {
        const cIdx = parseInt(btn.dataset.candIdx, 10);
        openRejectModal(cIdx);
      });
    });

    const unmatchBtn = container.querySelector("#btn-mark-unmatched") || container.querySelector(".btn-action-unmatched");
    if (unmatchBtn) {
      unmatchBtn.addEventListener("click", () => markUnmatched());
    }

    const undoBtn = container.querySelector("#btn-undo-decision");
    if (undoBtn) {
      undoBtn.addEventListener("click", () => undoLastDecision());
    }
  }

  function renderLedgerList() {
    const container = document.getElementById("ledger-list");
    if (!container || !demoData) return;

    const stmt = getActiveStatement();
    const cand = stmt && stmt.candidates && stmt.candidates[activeCandidateIndex];
    const highlightedLedgers = new Set(cand ? cand.ledger_line_ids : []);

    container.innerHTML = "";
    demoData.ledger.forEach(line => {
      const isHighlighted = highlightedLedgers.has(line.id);
      const div = document.createElement("div");
      div.className = `stmt-item${isHighlighted ? " active" : ""}`;
      if (isHighlighted) {
        div.style.borderColor = "var(--accent)";
        div.style.background = "var(--accent-soft)";
      }

      const paise = line.amount_paise || 0;
      const rupees = (paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 });
      const dirClass = line.direction === "debit" ? "debit" : "credit";

      div.innerHTML = `
        <div class="stmt-item-header">
          <span class="stmt-amount ${esc(dirClass)}">₹${esc(rupees)}</span>
          <span class="stmt-date">${esc(line.date_iso || "")}</span>
        </div>
        <div class="stmt-narration">${esc(line.text_norm || "")}</div>
        <div style="margin-top:0.35rem; display:flex; justify-content:space-between; align-items:center;">
          <span style="font-family:var(--font-mono); font-size:0.7rem; color:var(--slate-500);">${esc(line.id)}</span>
          ${isHighlighted ? '<span class="badge badge-auto" style="font-size:0.65rem;">Active Target</span>' : ""}
        </div>
      `;
      container.appendChild(div);
    });

    const activeL = container.querySelector(".stmt-item.active");
    if (activeL) {
      activeL.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }

  function renderAll() {
    renderMetrics();
    renderStatementList();
    renderWorklist();
    renderLedgerList();
  }

  async function postDecision(payload) {
    try {
      const res = await fetch("/api/demo/decisions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const err = await res.json();
        alert(err.detail || "Error saving decision");
        return;
      }
      const data = await res.json();
      decisionsHistory.push(data);
      decisionTimestamps.push(Date.now());
      advanceToNext();
    } catch (err) {
      console.error(err);
      alert("Network error saving decision");
    }
  }

  function advanceToNext() {
    if (activeIndex < demoData.statement.length - 1) {
      activeIndex++;
      activeCandidateIndex = 0;
    }
    renderAll();
  }

  function acceptCandidate(candIdx) {
    const stmt = getActiveStatement();
    if (!stmt || !stmt.candidates || !stmt.candidates[candIdx]) return;
    const cand = stmt.candidates[candIdx];
    postDecision({
      stmt_line_id: stmt.id,
      ledger_line_ids: cand.ledger_line_ids,
      action: "accept",
      candidate_key: `${stmt.id}:${cand.ledger_line_ids.join("+")}`
    });
  }

  function markUnmatched() {
    const stmt = getActiveStatement();
    if (!stmt) return;
    postDecision({
      stmt_line_id: stmt.id,
      ledger_line_ids: [],
      action: "unmatch"
    });
  }

  function focusablesIn(modal) {
    return Array.from(
      modal.querySelectorAll("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])")
    ).filter(el => !el.disabled && el.offsetParent !== null);
  }

  function openModal(modal) {
    lastFocusedElement = document.activeElement;
    modal.classList.add("open");
    const focusables = focusablesIn(modal);
    if (focusables.length) focusables[0].focus();
  }

  function closeModal(modal) {
    modal.classList.remove("open");
    if (lastFocusedElement && typeof lastFocusedElement.focus === "function") {
      lastFocusedElement.focus();
    }
    lastFocusedElement = null;
  }

  // Returns true if the Tab press was consumed by the trap.
  function trapFocus(e, modal) {
    if (e.key !== "Tab") return false;
    const focusables = focusablesIn(modal);
    if (!focusables.length) return false;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
      return true;
    }
    if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
      return true;
    }
    return false;
  }

  function openRejectModal(candIdx) {
    rejectTarget = candIdx;
    const modal = document.getElementById("reject-modal");
    if (modal) openModal(modal);
  }

  function closeRejectModal() {
    const modal = document.getElementById("reject-modal");
    if (modal && modal.classList.contains("open")) {
      closeModal(modal);
    } else if (modal) {
      modal.classList.remove("open");
    }
    rejectTarget = null;
  }

  function submitReject(reason) {
    const stmt = getActiveStatement();
    if (!stmt || rejectTarget === null || !stmt.candidates || !stmt.candidates[rejectTarget]) {
      closeRejectModal();
      return;
    }
    const cand = stmt.candidates[rejectTarget];
    closeRejectModal();
    postDecision({
      stmt_line_id: stmt.id,
      ledger_line_ids: cand.ledger_line_ids,
      action: "reject",
      reason: reason,
      candidate_key: `${stmt.id}:${cand.ledger_line_ids.join("+")}`
    });
  }

  async function undoLastDecision() {
    // Undo the latest still-active decision (skipping undo rows and
    // decisions already undone by a prior undo).
    const undone = undoneDecisionIds();
    let target = null;
    for (let i = decisionsHistory.length - 1; i >= 0; i--) {
      const dec = decisionsHistory[i];
      if (dec.action === "undo") continue;
      if (dec.id != null && undone.has(dec.id)) continue;
      target = dec;
      break;
    }
    if (!target) return;

    try {
      const res = await fetch("/api/demo/decisions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          stmt_line_id: target.stmt_line_id,
          ledger_line_ids: target.ledger_line_ids || [],
          action: "undo",
          target_decision_id: target.id
        })
      });
      if (res.ok) {
        decisionsHistory.push(await res.json()); // keep the undo row so history stays append-only
        renderAll();
      }
    } catch (err) {
      console.error(err);
    }
  }

  // Keyboard navigation & shortcuts
  function handleKeyDown(e) {
    // If a modal is open, only modal shortcuts apply.
    const rejectModal = document.getElementById("reject-modal");
    if (rejectModal && rejectModal.classList.contains("open")) {
      if (trapFocus(e, rejectModal)) return;
      if (e.key === "Escape") {
        closeRejectModal();
      } else if (e.key >= "1" && e.key <= "5") {
        const reasons = ["wrong amount", "wrong party", "wrong period", "duplicate", "other"];
        submitReject(reasons[parseInt(e.key, 10) - 1]);
      }
      return;
    }

    const shortcutsModal = document.getElementById("shortcuts-modal");
    if (shortcutsModal && shortcutsModal.classList.contains("open")) {
      if (trapFocus(e, shortcutsModal)) return;
      if (e.key === "Escape" || e.key === "?") {
        closeModal(shortcutsModal);
      }
      return;
    }

    // Ignore if typing in input
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;

    // Undo: Ctrl+Z or Cmd+Z
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
      e.preventDefault();
      undoLastDecision();
      return;
    }

    // Leave browser/OS combos alone (Ctrl+R, Ctrl+J, Alt+<letter>, ...)
    if (e.ctrlKey || e.metaKey || e.altKey) return;

    // Normalize so Caps Lock (uppercase J/K) still works.
    const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;

    if (key === "j" || key === "ArrowDown") {
      e.preventDefault();
      if (demoData && activeIndex < demoData.statement.length - 1) {
        activeIndex++;
        activeCandidateIndex = 0;
        renderAll();
      }
    } else if (key === "k" || key === "ArrowUp") {
      e.preventDefault();
      if (activeIndex > 0) {
        activeIndex--;
        activeCandidateIndex = 0;
        renderAll();
      }
    } else if (key === "Tab") {
      e.preventDefault();
      const stmt = getActiveStatement();
      if (stmt && stmt.candidates && stmt.candidates.length > 0) {
        if (e.shiftKey) {
          activeCandidateIndex = (activeCandidateIndex - 1 + stmt.candidates.length) % stmt.candidates.length;
        } else {
          activeCandidateIndex = (activeCandidateIndex + 1) % stmt.candidates.length;
        }
        renderWorklist();
        renderLedgerList();
      }
    } else if (key === "Enter") {
      e.preventDefault();
      acceptCandidate(activeCandidateIndex);
    } else if (key === "r") {
      e.preventDefault();
      openRejectModal(activeCandidateIndex);
    } else if (key === "u") {
      e.preventDefault();
      markUnmatched();
    } else if (key === "?") {
      e.preventDefault();
      const modal = document.getElementById("shortcuts-modal");
      if (modal) {
        if (modal.classList.contains("open")) closeModal(modal);
        else openModal(modal);
      }
    }
  }

  function initApp() {
    window.addEventListener("keydown", handleKeyDown);

    const btnReset = document.getElementById("btn-reset-demo");
    if (btnReset) {
      btnReset.addEventListener("click", async () => {
        if (confirm("Reset demo session decisions?")) {
          await fetch("/api/demo/reset", { method: "POST" });
          decisionsHistory = [];
          decisionTimestamps = [];
          activeIndex = 0;
          activeCandidateIndex = 0;
          loadDemo();
        }
      });
    }

    // Bind reject modal buttons
    const rejectBtns = document.querySelectorAll(".reject-reason-btn");
    rejectBtns.forEach(btn => {
      btn.addEventListener("click", () => {
        const reason = btn.dataset.reason;
        if (reason) submitReject(reason);
      });
    });

    const closeReject = document.getElementById("btn-close-reject");
    if (closeReject) closeReject.addEventListener("click", closeRejectModal);

    const closeShortcuts = document.getElementById("btn-close-shortcuts");
    if (closeShortcuts) {
      closeShortcuts.addEventListener("click", () => {
        const modal = document.getElementById("shortcuts-modal");
        if (modal) closeModal(modal);
      });
    }

    const openShortcuts = document.getElementById("btn-open-shortcuts");
    if (openShortcuts) {
      openShortcuts.addEventListener("click", () => {
        const modal = document.getElementById("shortcuts-modal");
        if (modal) openModal(modal);
      });
    }

    loadDemo();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initApp);
  } else {
    initApp();
  }
})();
