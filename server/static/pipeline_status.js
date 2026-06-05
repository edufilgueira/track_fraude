(function () {
  const POLL_MS_ACTIVE = 2000;
  const POLL_MS_IDLE = 5000;
  const POLL_MS_HIDDEN = 15000;

  let pollTimer = null;
  let lastHadRunning = false;

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function processingBadge(phase) {
    const hint = phase ? " · " + escapeHtml(phase) : "";
    return (
      '<span class="badge badge-processing" title="Pipeline em execução">' +
      '<span class="status-dot pulse" aria-hidden="true"></span>' +
      "Processando" +
      hint +
      "</span>"
    );
  }

  function activeBadge(label) {
    return '<span class="badge badge-active">' + escapeHtml(label) + "</span>";
  }

  function scheduleNextPoll(hasRunning) {
    if (pollTimer !== null) {
      clearTimeout(pollTimer);
    }
    let delay = hasRunning ? POLL_MS_ACTIVE : POLL_MS_IDLE;
    if (document.hidden) {
      delay = Math.max(delay, POLL_MS_HIDDEN);
    }
    pollTimer = setTimeout(refresh, delay);
  }

  async function refresh() {
    pollTimer = null;
    if (!document.querySelector(".status-cell")) {
      return null;
    }

    try {
      const response = await fetch("/api/pipeline/status", {
        signal: AbortSignal.timeout(10000),
      });
      if (!response.ok) {
        scheduleNextPoll(lastHadRunning);
        return null;
      }
      const data = await response.json();
      const groups = new Set(data.groups_processing || []);
      const stores = new Set(data.stores_processing || []);
      const hasRunning = stores.size > 0 || groups.size > 0;
      lastHadRunning = hasRunning;

      const runByStore = {};
      const runByGroup = {};
      (data.running || []).forEach(function (run) {
        runByStore[run.store_db_id] = run;
        if (run.group_db_id != null) {
          runByGroup[run.group_db_id] = run;
        }
      });

      document.querySelectorAll("[data-group-id].status-cell").forEach(function (cell) {
        if (cell.dataset.inactive === "1") {
          return;
        }
        const id = Number(cell.dataset.groupId);
        if (groups.has(id)) {
          const run = runByGroup[id];
          cell.innerHTML = processingBadge(run ? run.current_phase : "");
        } else {
          cell.innerHTML = activeBadge("Ativo");
        }
      });

      document.querySelectorAll("[data-store-id].status-cell").forEach(function (cell) {
        if (cell.dataset.inactive === "1") {
          return;
        }
        const id = Number(cell.dataset.storeId);
        if (stores.has(id)) {
          const run = runByStore[id];
          cell.innerHTML = processingBadge(run ? run.current_phase : "");
        } else {
          cell.innerHTML = activeBadge("Ativa");
        }
      });

      document.dispatchEvent(
        new CustomEvent("pipeline-status-update", {
          detail: {
            stores_processing: data.stores_processing || [],
            running: data.running || [],
          },
        })
      );

      scheduleNextPoll(hasRunning);
      return data;
    } catch (error) {
      if (error.name !== "TimeoutError" && error.name !== "AbortError") {
        console.debug("pipeline status poll failed", error);
      }
      scheduleNextPoll(lastHadRunning);
      return null;
    }
  }

  window.refreshPipelineStatus = function () {
    if (pollTimer !== null) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
    return refresh();
  };

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) {
      window.refreshPipelineStatus();
    }
  });

  if (document.querySelector(".status-cell")) {
    refresh();
  }
})();
