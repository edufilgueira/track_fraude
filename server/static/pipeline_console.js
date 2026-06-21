(function () {
  const POLL_MS = 1000;
  const POLL_MS_HIDDEN = 5000;
  const TAIL_AFTER_FINISH_MS = 8000;
  const TAIL_INCOMPLETE_MS = 120000;
  /** Limite de texto no console — evita travar a aba com logs longos. */
  const MAX_LOG_CHARS = 120000;

  const consoles = {};
  let pollTimer = null;
  let tabVisible = !document.hidden;

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
        logText: "",
        logPath: null,
        runId: null,
        pollRunning: false,
        truncatedNotice: false,
        userDismissed: false,
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

  function trimLogText(text) {
    if (text.length <= MAX_LOG_CHARS) {
      return { text: text, truncated: false };
    }
    const slice = text.slice(-MAX_LOG_CHARS);
    const firstNewline = slice.indexOf("\n");
    const trimmed = firstNewline >= 0 ? slice.slice(firstNewline + 1) : slice;
    return {
      text: "… (log anterior omitido para manter a aba responsiva)\n" + trimmed,
      truncated: true,
    };
  }

  function renderLogBody(storeDbId) {
    const state = ensureState(storeDbId);
    const els = consoleElements(storeDbId);
    if (!els) {
      return;
    }
    const body = els.body;
    const nearBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 48;
    body.textContent = state.logText || "Aguardando saída do pipeline…\n";
    if (statePinned(storeDbId, nearBottom)) {
      body.scrollTop = body.scrollHeight;
    }
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
    renderLogBody(storeDbId);
    schedulePoll();
  }

  function closeConsole(storeDbId) {
    const state = ensureState(storeDbId);
    const els = consoleElements(storeDbId);
    state.open = false;
    state.userDismissed = true;
    if (els) {
      els.row.hidden = true;
    }
    if (!hasOpenConsoles()) {
      clearPollTimer();
    }
  }

  function hasOpenConsoles() {
    return Object.keys(consoles).some(function (key) {
      return consoles[key].open;
    });
  }

  function clearPollTimer() {
    if (pollTimer !== null) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  function appendLog(storeDbId, text) {
    if (!text) {
      return;
    }
    const state = ensureState(storeDbId);
    if (!state.logText && text) {
      state.logText = "";
    }
    state.logText += text;
    const trimmed = trimLogText(state.logText);
    state.logText = trimmed.text;
    if (trimmed.truncated) {
      state.truncatedNotice = true;
    }
    renderLogBody(storeDbId);
  }

  function statePinned(storeDbId, nearBottom) {
    const state = ensureState(storeDbId);
    if (!state.pinnedBottom) {
      return false;
    }
    return nearBottom || bodyIsEmpty(storeDbId);
  }

  function bodyIsEmpty(storeDbId) {
    const state = ensureState(storeDbId);
    return !state.logText || state.logText.trim() === "";
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

  function logIsComplete(text, payload) {
    if (payload && payload.log_complete) {
      return true;
    }
    return (
      /tempo total:\s*[\d.]+s/.test(text || "") ||
      /--- cancelado pelo usu/i.test(text || "")
    );
  }

  async function fetchLog(storeDbId) {
    const state = ensureState(storeDbId);
    const response = await fetch(
      "/api/pipeline/stores/" + storeDbId + "/log?offset=" + state.offset,
      { signal: AbortSignal.timeout(15000) }
    );
    if (!response.ok) {
      return null;
    }
    return response.json();
  }

  function pollIntervalMs() {
    return tabVisible ? POLL_MS : POLL_MS_HIDDEN;
  }

  function shouldKeepPolling(openStores) {
    return openStores.some(function (key) {
      const state = consoles[Number(key)];
      if (!state.open) {
        return false;
      }
      if (state.pollRunning || !state.finishedAt) {
        return true;
      }
      if (!logIsComplete(state.logText, null)) {
        return Date.now() - state.finishedAt < TAIL_INCOMPLETE_MS;
      }
      return Date.now() - state.finishedAt < TAIL_AFTER_FINISH_MS;
    });
  }

  async function pollLogs() {
    pollTimer = null;

    const openStores = Object.keys(consoles).filter(function (key) {
      return consoles[key].open;
    });
    if (!openStores.length) {
      return;
    }

    if (tabVisible) {
      for (const key of openStores) {
        const storeDbId = Number(key);
        const state = consoles[storeDbId];
        try {
          const payload = await fetchLog(storeDbId);
          if (!payload) {
            continue;
          }
          if (
            payload.log_path &&
            state.logPath &&
            payload.log_path !== state.logPath
          ) {
            state.offset = 0;
            state.logText = "";
            state.finishedAt = null;
          }
          if (payload.log_path) {
            state.logPath = payload.log_path;
          }
          if (payload.content) {
            appendLog(storeDbId, payload.content);
            state.offset = payload.offset;
            if (state.finishedAt) {
              state.finishedAt = null;
            }
          }
          const complete = logIsComplete(state.logText, payload);
          const failed =
            !payload.running && complete && logIndicatesFailure(state.logText);
          const stillRunning = payload.running || !complete;
          state.pollRunning = stillRunning;
          updateMeta(storeDbId, {
            date: payload.date,
            current_phase: payload.current_phase,
            running: stillRunning,
            has_log: payload.has_log,
            failed: failed,
          });
          if (!stillRunning && !state.finishedAt) {
            state.finishedAt = Date.now();
            refreshReviewButton(storeDbId);
          }
        } catch (error) {
          if (error.name !== "TimeoutError" && error.name !== "AbortError") {
            console.debug("pipeline log poll failed", error);
          }
        }
      }
    }

    if (shouldKeepPolling(openStores)) {
      pollTimer = setTimeout(pollLogs, pollIntervalMs());
    } else {
      openStores.forEach(function (key) {
        refreshReviewButton(Number(key));
      });
    }
  }

  function schedulePoll() {
    if (pollTimer === null && hasOpenConsoles()) {
      pollTimer = setTimeout(pollLogs, 0);
    }
  }

  document.addEventListener("visibilitychange", function () {
    tabVisible = !document.hidden;
    if (tabVisible && hasOpenConsoles()) {
      schedulePoll();
    }
  });

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
    state.logText = "";
    state.logPath = detail.logPath || null;
    state.runId = detail.runId || null;
    state.truncatedNotice = false;
    state.userDismissed = false;
    state.finishedAt = null;
    state.pinnedBottom = true;
    openConsole(detail.storeDbId, detail);
  });

  document.addEventListener("pipeline-status-update", function (event) {
    const running = event.detail && event.detail.running ? event.detail.running : [];
    running.forEach(function (run) {
      const state = ensureState(run.store_db_id);
      if (state.open) {
        updateMeta(run.store_db_id, {
          date: run.date,
          current_phase: run.current_phase,
          running: true,
          has_log: true,
        });
        schedulePoll();
        return;
      }
      if (state.userDismissed) {
        return;
      }
      if (state.runId && run.run_id && state.runId === run.run_id) {
        openConsole(run.store_db_id, {
          date: run.date,
          storeLabel: run.store_id,
        });
        schedulePoll();
        return;
      }
      state.offset = 0;
      state.logText = "";
      state.logPath = null;
      state.runId = run.run_id || null;
      state.truncatedNotice = false;
      openConsole(run.store_db_id, {
        date: run.date,
        storeLabel: run.store_id,
      });
    });
  });

  window.openPipelineConsole = openConsole;
})();
