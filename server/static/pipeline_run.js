(function () {
  const PLAY_ICON =
    '<svg class="pipeline-icon" viewBox="0 0 24 24" aria-hidden="true">' +
    '<path fill="currentColor" d="M8 5v14l11-7z"/></svg>';
  const PAUSE_ICON =
    '<svg class="pipeline-icon" viewBox="0 0 24 24" aria-hidden="true">' +
    '<path fill="currentColor" d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>';

  function setButtonRunning(btn, running) {
    btn.dataset.running = running ? "1" : "0";
    btn.classList.toggle("pipeline-btn-running", running);
    btn.innerHTML = running ? PAUSE_ICON : PLAY_ICON;
    btn.title = running ? "Cancelar pipeline" : "Executar pipeline";
    btn.setAttribute("aria-label", btn.title);
  }

  function syncButtonsFromStatus(detail) {
    const stores = new Set((detail && detail.stores_processing) || []);
    document.querySelectorAll(".pipeline-run-btn").forEach(function (btn) {
      const storeDbId = Number(btn.dataset.storeId);
      setButtonRunning(btn, stores.has(storeDbId));
    });
  }

  function refreshStatusSoon() {
    if (typeof window.refreshPipelineStatus === "function") {
      window.refreshPipelineStatus();
      setTimeout(window.refreshPipelineStatus, 400);
      setTimeout(window.refreshPipelineStatus, 1200);
    }
  }

  function closeAllMenus() {
    document.querySelectorAll(".pipeline-date-menu").forEach(function (menu) {
      menu.hidden = true;
    });
  }

  function errorDetail(payload, fallback) {
    if (Array.isArray(payload.detail)) {
      return payload.detail.map(function (item) {
        return item.msg || String(item);
      }).join(", ");
    }
    return payload.detail || fallback;
  }

  async function fetchRawDates(storeDbId) {
    const response = await fetch("/api/pipeline/stores/" + storeDbId + "/raw-dates");
    if (!response.ok) {
      const payload = await response.json().catch(function () {
        return {};
      });
      throw new Error(errorDetail(payload, "Não foi possível listar datas importadas"));
    }
    return response.json();
  }

  async function startPipeline(storeDbId, date) {
    const response = await fetch("/api/pipeline/stores/" + storeDbId + "/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date: date }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(function () {
        return {};
      });
      throw new Error(errorDetail(payload, "Falha ao iniciar pipeline"));
    }
    return response.json();
  }

  async function cancelPipeline(storeDbId) {
    const response = await fetch("/api/pipeline/stores/" + storeDbId + "/cancel", {
      method: "POST",
    });
    if (!response.ok) {
      const payload = await response.json().catch(function () {
        return {};
      });
      throw new Error(errorDetail(payload, "Falha ao cancelar pipeline"));
    }
  }

  function showDateMenu(btn, dates) {
    closeAllMenus();
    let menu = btn.parentElement.querySelector(".pipeline-date-menu");
    if (!menu) {
      menu = document.createElement("div");
      menu.className = "pipeline-date-menu";
      menu.hidden = true;
      btn.parentElement.appendChild(menu);
    }
    menu.innerHTML = "";
    dates.forEach(function (item) {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "pipeline-date-option";
      option.dataset.date = item.id;
      option.textContent = item.label;
      menu.appendChild(option);
    });
    menu.hidden = false;
  }

  document.querySelectorAll(".pipeline-run-btn").forEach(function (btn) {
    setButtonRunning(btn, btn.dataset.running === "1");
  });

  document.addEventListener("click", function (event) {
    const btn = event.target.closest(".pipeline-run-btn");
    if (btn) {
      event.preventDefault();
      event.stopPropagation();
      const storeDbId = Number(btn.dataset.storeId);
      if (btn.dataset.running === "1") {
        btn.disabled = true;
        cancelPipeline(storeDbId)
          .then(function () {
            refreshStatusSoon();
          })
          .catch(function (error) {
            alert(error.message);
          })
          .finally(function () {
            btn.disabled = false;
          });
        return;
      }

      btn.disabled = true;
      fetchRawDates(storeDbId)
        .then(function (payload) {
          const dates = payload.dates || [];
          if (dates.length === 0) {
            const hint = payload.raw_path || "data/raw/…";
            throw new Error(
              "Nenhuma data importada encontrada em " + hint + ". " +
              "Baixe os vídeos antes de executar o pipeline."
            );
          }
          if (dates.length === 1) {
            return startPipeline(storeDbId, dates[0].id).then(function (payload) {
              document.dispatchEvent(
                new CustomEvent("pipeline-started", {
                  detail: {
                    storeDbId: storeDbId,
                    date: payload.date,
                    runId: payload.run_id,
                    logPath: payload.log_path,
                  },
                })
              );
              refreshStatusSoon();
            });
          }
          showDateMenu(btn, dates);
        })
        .catch(function (error) {
          alert(error.message);
        })
        .finally(function () {
          btn.disabled = false;
        });
      return;
    }

    const option = event.target.closest(".pipeline-date-option");
    if (option) {
      event.preventDefault();
      event.stopPropagation();
      const menu = option.closest(".pipeline-date-menu");
      const wrap = menu && menu.parentElement;
      const runBtn = wrap && wrap.querySelector(".pipeline-run-btn");
      if (!runBtn) {
        return;
      }
      const storeDbId = Number(runBtn.dataset.storeId);
      const date = option.dataset.date;
      closeAllMenus();
      runBtn.disabled = true;
      startPipeline(storeDbId, date)
        .then(function (payload) {
          document.dispatchEvent(
            new CustomEvent("pipeline-started", {
              detail: {
                storeDbId: storeDbId,
                date: payload.date,
                runId: payload.run_id,
                logPath: payload.log_path,
              },
            })
          );
          refreshStatusSoon();
        })
        .catch(function (error) {
          alert(error.message);
        })
        .finally(function () {
          runBtn.disabled = false;
        });
      return;
    }

    if (!event.target.closest(".pipeline-run-wrap")) {
      closeAllMenus();
    }
  });

  document.addEventListener("pipeline-status-update", function (event) {
    syncButtonsFromStatus(event.detail || {});
  });
})();
