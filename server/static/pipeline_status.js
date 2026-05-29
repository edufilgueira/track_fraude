(function () {
  const POLL_MS = 4000;

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

  async function refresh() {
    try {
      const response = await fetch("/api/pipeline/status");
      if (!response.ok) {
        return;
      }
      const data = await response.json();
      const groups = new Set(data.groups_processing || []);
      const stores = new Set(data.stores_processing || []);
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
    } catch (error) {
      console.debug("pipeline status poll failed", error);
    }
  }

  if (document.querySelector(".status-cell")) {
    refresh();
    setInterval(refresh, POLL_MS);
  }
})();
