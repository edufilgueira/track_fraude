(function () {
  const POLL_MS = 1000;
  const TAIL_AFTER_FINISH_MS = 8000;

  const consoles = {};
  let pollTimer = null;

  function getConsoleRow(storeDbId) {
    return document.querySelector(
      '.pipeline-console-row[data-store-id="' + storeDbId + '"]'
    );
  }

  function ensureState(storeDbId) {
    if (!consoles[storeDbId]) {
      consoles[storeDbId] = {
        offset: 0,
        open: false,
        pinnedBottom: true,
        finishedAt: null,
      };
    }
    return consoles[storeDbId];
  }

  function consoleElements(storeDbId) {
    const row = getConsoleRow(storeDbId);
    if (!row) {
      return null;
    }
    return {
      row: row,
      body: row.querySelector(".pipeline-console-body"),
      meta: row.querySelector(".pipeline-console-meta"),
      title: row.querySelector(".pipeline-console-title"),
    };
  }

  function openConsole(storeDbId, meta) {
    const state = ensureState(storeDbId);
    const els = consoleElements(storeDbId);
    if (!els) {
      return;
    }
    state.open = true;
    state.finishedAt = null;
    if (meta && meta.date) {
      els.meta.textContent = meta.date;
    }
    els.row.hidden = false;
    els.body.textContent = state.offset === 0 ? "Aguardando saída do pipeline…\n" : els.body.textContent;
    schedulePoll();
  }

  function closeConsole(storeDbId) {
    const state = ensureState(storeDbId);
    const els = consoleElements(storeDbId);
    state.open = false;
    if (els) {
      els.row.hidden = true;
    }
  }

  function appendLog(storeDbId, text) {
    const els = consoleElements(storeDbId);
    if (!els || !text) {
      return;
    }
    const body = els.body;
    const nearBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 48;
    body.textContent += text;
    if (statePinned(storeDbId, nearBottom)) {
      body.scrollTop = body.scrollHeight;
    }
  }

  function statePinned(storeDbId, nearBottom) {
    const state = ensureState(storeDbId);
    if (!state.pinnedBottom) {
      return false;
    }
    return nearBottom || bodyIsEmpty(storeDbId);
  }

  function bodyIsEmpty(storeDbId) {
    const els = consoleElements(storeDbId);
    return els && els.body.textContent.trim() === "Aguardando saída do pipeline…";
  }

  function updateMeta(storeDbId, payload) {
    const els = consoleElements(storeDbId);
    if (!els || !els.meta) {
      return;
    }
    const parts = [];
    if (payload.date) {
      parts.push(payload.date);
    }
    if (payload.current_phase) {
      parts.push(payload.current_phase);
    }
    if (payload.running) {
      parts.push("em execução");
    } else if (payload.failed) {
      parts.push("falhou");
    } else if (payload.has_log) {
      parts.push("concluído");
    }
    els.meta.textContent = parts.length ? parts.join(" · ") : "";
  }

  async function refreshReviewButton(storeDbId) {
    const wrap = document.querySelector(
      '.review-link-wrap[data-store-id="' + storeDbId + '"]'
    );
    if (!wrap || wrap.querySelector(".review-link-btn")) {
      return;
    }
    try {
      const response = await fetch(
        "/api/pipeline/stores/" + storeDbId + "/review-available"
      );
      if (!response.ok) {
        return;
      }
      const data = await response.json();
      if (!data.has_review) {
        return;
      }
      const link = document.createElement("a");
      link.className = "btn review-link-btn";
      link.href = "/stores/" + storeDbId + "/review";
      link.textContent = "Revisão";
      wrap.appendChild(link);
    } catch (error) {
      console.debug("review button refresh failed", error);
    }
  }

  function logIndicatesFailure(text) {
    return /\(exit 1\)/.test(text || "") || /"ok": false/.test(text || "");
  }

  async function fetchLog(storeDbId) {
    const state = ensureState(storeDbId);
    const response = await fetch(
      "/api/pipeline/stores/" + storeDbId + "/log?offset=" + state.offset
    );
    if (!response.ok) {
      return null;
    }
    return response.json();
  }

  async function pollLogs() {
    const openStores = Object.keys(consoles).filter(function (key) {
      return consoles[key].open;
    });
    if (!openStores.length) {
      pollTimer = null;
      return;
    }

    for (const key of openStores) {
      const storeDbId = Number(key);
      const state = consoles[storeDbId];
      try {
        const payload = await fetchLog(storeDbId);
        if (!payload) {
          continue;
        }
        if (payload.content) {
          appendLog(storeDbId, payload.content);
          state.offset = payload.offset;
        }
        const failed = !payload.running && logIndicatesFailure(payload.content);
        updateMeta(storeDbId, {
          date: payload.date,
          current_phase: payload.current_phase,
          running: payload.running,
          has_log: payload.has_log,
          failed: failed,
        });
        if (!payload.running && !state.finishedAt) {
          state.finishedAt = Date.now();
          refreshReviewButton(storeDbId);
        }
      } catch (error) {
        console.debug("pipeline log poll failed", error);
      }
    }

    const stillPolling = openStores.some(function (key) {
      const state = consoles[Number(key)];
      if (!state.open) {
        return false;
      }
      if (!state.finishedAt) {
        return true;
      }
      return Date.now() - state.finishedAt < TAIL_AFTER_FINISH_MS;
    });

    if (stillPolling) {
      pollTimer = setTimeout(pollLogs, POLL_MS);
    } else {
      openStores.forEach(function (key) {
        refreshReviewButton(Number(key));
      });
      pollTimer = null;
    }
  }

  function schedulePoll() {
    if (pollTimer === null) {
      pollTimer = setTimeout(pollLogs, 0);
    }
  }

  document.addEventListener("click", function (event) {
    const closeBtn = event.target.closest(".pipeline-console-close");
    if (!closeBtn) {
      return;
    }
    const row = closeBtn.closest(".pipeline-console-row");
    if (!row) {
      return;
    }
    closeConsole(Number(row.dataset.storeId));
  });

  document.querySelectorAll(".pipeline-console-body").forEach(function (body) {
    body.addEventListener("scroll", function () {
      const row = body.closest(".pipeline-console-row");
      if (!row) {
        return;
      }
      const state = ensureState(Number(row.dataset.storeId));
      const nearBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 48;
      state.pinnedBottom = nearBottom;
    });
  });

  document.addEventListener("pipeline-started", function (event) {
    const detail = event.detail || {};
    if (!detail.storeDbId) {
      return;
    }
    const state = ensureState(detail.storeDbId);
    state.offset = 0;
    state.pinnedBottom = true;
    const els = consoleElements(detail.storeDbId);
    if (els) {
      els.body.textContent = "";
    }
    openConsole(detail.storeDbId, detail);
  });

  document.addEventListener("pipeline-status-update", function (event) {
    const running = event.detail && event.detail.running ? event.detail.running : [];
    running.forEach(function (run) {
      const state = ensureState(run.store_db_id);
      if (!state.open) {
        openConsole(run.store_db_id, {
          date: run.date,
          storeLabel: run.store_id,
        });
        state.offset = 0;
        const els = consoleElements(run.store_db_id);
        if (els) {
          els.body.textContent = "";
        }
      }
      updateMeta(run.store_db_id, {
        date: run.date,
        current_phase: run.current_phase,
        running: true,
        has_log: true,
      });
      schedulePoll();
    });
  });

  window.openPipelineConsole = openConsole;
})();
