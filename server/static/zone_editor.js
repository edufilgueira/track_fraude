(function () {
  const config = window.zoneEditorConfig;
  if (!config) return;

  const stage = document.getElementById("zone-stage");
  const frameWrap = document.getElementById("zone-frame-wrap");
  const image = document.getElementById("frame-image");
  const overlay = document.getElementById("zone-overlay");
  const preview = document.getElementById("zone-preview");
  const status = document.getElementById("zone-status");
  const fileInput = document.getElementById("video-file");
  const fileName = document.getElementById("video-file-name");
  const seekInput = document.getElementById("seek-seconds");
  const captureBtn = document.getElementById("capture-frame");
  const videoDateInput = document.getElementById("video-date");
  const loadFromStorageBtn = document.getElementById("load-from-storage");
  const undoBtn = document.getElementById("undo-point");
  const clearBtn = document.getElementById("clear-draft");
  const saveBtn = document.getElementById("save-polygon");
  const vectorBtn = document.getElementById("set-entry-vector");
  const laneTabsEl = document.getElementById("lane-tabs");
  const addLaneBtn = document.getElementById("add-lane");
  const deleteLaneBtn = document.getElementById("delete-lane");
  const labelInput = document.getElementById("zone-label");
  const r1MinInput = document.getElementById("r1-min-duration-sec");

  const LANE_COLORS = ["#60a5fa", "#34d399", "#fbbf24", "#f472b6", "#a78bfa", "#fb923c"];
  const isCheckout = config.cameraRole === "checkout";

  let frameSize = { width: 0, height: 0 };
  let savedZones = Array.isArray(config.existingZones) ? config.existingZones.slice() : [];
  let draftPoints = [];
  let videoDuration = config.videoDuration || 0;
  let currentFile = null;
  let imageObjectUrl = null;
  let videoAvailable = !!config.videoAvailable;
  let captureInProgress = false;
  let vectorMode = false;
  let vectorStart = null;
  let activeLaneId = 1;
  let laneLabels = {};
  let extraLaneIds = new Set();

  function laneColor(laneId) {
    return LANE_COLORS[(Number(laneId) - 1) % LANE_COLORS.length];
  }

  function savedZoneForLane(laneId) {
    return savedZones.find(function (z) { return z.lane_id === laneId; }) || null;
  }

  function allLaneIds() {
    const ids = new Set();
    savedZones.forEach(function (z) {
      if (z.lane_id != null) ids.add(Number(z.lane_id));
    });
    extraLaneIds.forEach(function (id) { ids.add(id); });
    if (!ids.size) ids.add(1);
    return Array.from(ids).sort(function (a, b) { return a - b; });
  }

  function nextLaneId() {
    const ids = allLaneIds();
    return Math.max.apply(null, ids.concat([0])) + 1;
  }

  function laneLabel(laneId) {
    return laneLabels[laneId] || ("Caixa " + laneId);
  }

  function syncLabelInput() {
    if (!labelInput) return;
    labelInput.value = laneLabel(activeLaneId);
  }

  function renderLaneTabs() {
    if (!laneTabsEl) return;
    laneTabsEl.innerHTML = "";
    allLaneIds().forEach(function (laneId) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "zone-lane-tab" + (laneId === activeLaneId ? " is-active" : "");
      btn.setAttribute("role", "tab");
      btn.setAttribute("aria-selected", laneId === activeLaneId ? "true" : "false");

      const dot = document.createElement("span");
      dot.className = "lane-dot";
      dot.style.background = laneColor(laneId);
      btn.appendChild(dot);

      const text = document.createElement("span");
      text.textContent = laneLabel(laneId);
      btn.appendChild(text);

      if (!savedZoneForLane(laneId)) {
        const mark = document.createElement("span");
        mark.className = "lane-unsaved";
        mark.textContent = " (sem polígono)";
        btn.appendChild(mark);
      }

      btn.addEventListener("click", function () {
        selectLane(laneId);
      });
      laneTabsEl.appendChild(btn);
    });
  }

  function selectLane(laneId) {
    activeLaneId = laneId;
    draftPoints = [];
    vectorMode = false;
    vectorStart = null;
    syncLabelInput();
    renderLaneTabs();
    renderOverlay();
    setStatus(
      "Caixa " + laneId + " selecionado. Clique na imagem para marcar o polígono.",
      "info"
    );
  }

  function addLane() {
    const laneId = nextLaneId();
    extraLaneIds.add(laneId);
    laneLabels[laneId] = "Caixa " + laneId;
    selectLane(laneId);
  }

  async function deleteActiveLane() {
    const laneId = activeLaneId;
    const zone = savedZoneForLane(laneId);
    if (zone) {
      if (!window.confirm("Excluir " + laneLabel(laneId) + " e o polígono salvo?")) {
        return;
      }
      const url =
        "/stores/" + config.storeId + "/cameras/" + config.cameraDbId +
        "/zones/" + encodeURIComponent(zone.zone_id);
      setStatus("Excluindo caixa…", "pending");
      const response = await fetch(url, { method: "DELETE" });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || "Falha ao excluir caixa");
      }
      savedZones = savedZones.filter(function (z) { return z.lane_id !== laneId; });
    }

    extraLaneIds.delete(laneId);
    delete laneLabels[laneId];
    draftPoints = [];

    const remaining = allLaneIds().filter(function (id) { return id !== laneId; });
    if (!remaining.length) {
      activeLaneId = 1;
      laneLabels[1] = "Caixa 1";
      extraLaneIds.add(1);
    } else {
      activeLaneId = remaining[0];
    }

    syncLabelInput();
    renderLaneTabs();
    renderOverlay();
    setStatus("Caixa " + laneId + " removido.", "success");
  }

  function initCheckoutLanes() {
    if (!isCheckout) return;
    const lanes = savedZones
      .filter(function (z) { return z.lane_id != null; })
      .sort(function (a, b) { return a.lane_id - b.lane_id; });

    lanes.forEach(function (z) {
      laneLabels[z.lane_id] = z.label || ("Caixa " + z.lane_id);
    });

    if (lanes.length) {
      activeLaneId = lanes[0].lane_id;
    } else {
      activeLaneId = 1;
      laneLabels[1] = "Caixa 1";
      extraLaneIds.add(1);
    }
    syncLabelInput();
    renderLaneTabs();
  }

  function polygonCentroid(polygon) {
    const cx = polygon.reduce(function (s, p) { return s + p[0]; }, 0) / polygon.length;
    const cy = polygon.reduce(function (s, p) { return s + p[1]; }, 0) / polygon.length;
    return displayPoint(cx, cy);
  }

  function setStatus(message, kind) {
    status.textContent = message;
    status.className = "roi-status" + (kind ? " roi-status-" + kind : "");
  }

  function scaleFactors() {
    const displayWidth = image.clientWidth;
    const displayHeight = image.clientHeight;
    if (!displayWidth || !displayHeight || !frameSize.width || !frameSize.height) {
      return { x: 1, y: 1 };
    }
    return {
      x: frameSize.width / displayWidth,
      y: frameSize.height / displayHeight,
    };
  }

  function framePointFromEvent(event) {
    const bounds = image.getBoundingClientRect();
    const scale = scaleFactors();
    const x = Math.min(Math.max(event.clientX - bounds.left, 0), bounds.width);
    const y = Math.min(Math.max(event.clientY - bounds.top, 0), bounds.height);
    return {
      display: { x, y },
      frame: {
        x: Math.round(x * scale.x),
        y: Math.round(y * scale.y),
      },
    };
  }

  function displayPoint(frameX, frameY) {
    const scale = scaleFactors();
    return { x: frameX / scale.x, y: frameY / scale.y };
  }

  function polygonToPoints(polygon) {
    return polygon.map(function (pair) {
      const p = displayPoint(pair[0], pair[1]);
      return p.x + "," + p.y;
    }).join(" ");
  }

  function syncOverlaySize() {
    const w = image.clientWidth;
    const h = image.clientHeight;
    if (!w || !h) return false;
    overlay.setAttribute("viewBox", "0 0 " + w + " " + h);
    overlay.setAttribute("preserveAspectRatio", "none");
    return true;
  }

  function clearSvg() {
    while (overlay.firstChild) overlay.removeChild(overlay.firstChild);
  }

  function drawArrow(from, to, color) {
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", from.x);
    line.setAttribute("y1", from.y);
    line.setAttribute("x2", to.x);
    line.setAttribute("y2", to.y);
    line.setAttribute("stroke", color);
    line.setAttribute("stroke-width", "2");
    line.setAttribute("marker-end", "url(#arrowhead)");
    overlay.appendChild(line);
  }

  function ensureArrowMarker() {
    if (overlay.querySelector("#arrowhead")) return;
    const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    defs.innerHTML =
      '<marker id="arrowhead" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">' +
      '<polygon points="0 0, 8 3, 0 6" fill="#ffffff" /></marker>';
    overlay.appendChild(defs);
  }

  function renderOverlay() {
    if (!syncOverlaySize()) return;
    clearSvg();
    ensureArrowMarker();

    savedZones.forEach(function (zone) {
      const laneId = zone.lane_id;
      const color = laneId != null ? laneColor(laneId) : "#34d399";
      const isActive = isCheckout && laneId === activeLaneId;
      const poly = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
      poly.setAttribute("class", "zone-saved-fill");
      poly.setAttribute("points", polygonToPoints(zone.polygon));
      poly.setAttribute("fill", color);
      poly.setAttribute("fill-opacity", isActive ? "0.28" : "0.18");
      poly.setAttribute("stroke", color);
      poly.setAttribute("stroke-width", isActive ? "4" : "2");
      overlay.appendChild(poly);

      if (laneId != null) {
        const center = polygonCentroid(zone.polygon);
        const tag = document.createElementNS("http://www.w3.org/2000/svg", "text");
        tag.setAttribute("class", "zone-dot-label");
        tag.setAttribute("x", center.x);
        tag.setAttribute("y", center.y);
        tag.setAttribute("text-anchor", "middle");
        tag.setAttribute("dominant-baseline", "middle");
        tag.textContent = laneLabel(laneId);
        overlay.appendChild(tag);
      }

      if (zone.entry_vector && zone.entry_vector.length === 2) {
        const cx = zone.polygon.reduce(function (s, p) { return s + p[0]; }, 0) / zone.polygon.length;
        const cy = zone.polygon.reduce(function (s, p) { return s + p[1]; }, 0) / zone.polygon.length;
        const start = displayPoint(cx, cy);
        const end = displayPoint(cx + zone.entry_vector[0] * 40, cy + zone.entry_vector[1] * 40);
        drawArrow(start, end, "#ffffff");
      }
    });

    if (draftPoints.length >= 2) {
      const draftColor = isCheckout ? laneColor(activeLaneId) : "#60a5fa";
      const draft = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      draft.setAttribute("class", "zone-draft-line");
      draft.setAttribute("stroke", draftColor);
      draft.setAttribute(
        "points",
        draftPoints.map(function (p) { return p.display.x + "," + p.display.y; }).join(" ")
      );
      overlay.appendChild(draft);
    }

    if (draftPoints.length >= 3) {
      const draftColor = isCheckout ? laneColor(activeLaneId) : "#60a5fa";
      const closed = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
      closed.setAttribute("class", "zone-draft-fill");
      closed.setAttribute("stroke", draftColor);
      closed.setAttribute("fill", draftColor);
      closed.setAttribute("fill-opacity", "0.2");
      closed.setAttribute(
        "points",
        draftPoints.map(function (p) { return p.display.x + "," + p.display.y; }).join(" ")
      );
      overlay.appendChild(closed);
    }

    draftPoints.forEach(function (p, index) {
      const draftColor = isCheckout ? laneColor(activeLaneId) : "#60a5fa";
      const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      dot.setAttribute("class", "zone-dot");
      dot.setAttribute("cx", p.display.x);
      dot.setAttribute("cy", p.display.y);
      dot.setAttribute("r", "5");
      dot.setAttribute("fill", draftColor);
      overlay.appendChild(dot);

      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("class", "zone-dot-label");
      label.setAttribute("x", p.display.x + 7);
      label.setAttribute("y", p.display.y - 7);
      label.textContent = String(index + 1);
      overlay.appendChild(label);
    });

    updatePreviewText();
  }

  function updatePreviewText() {
    if (!savedZones.length && !draftPoints.length) {
      preview.textContent = "Nenhum polígono salvo.";
      return;
    }
    const saved = savedZones.map(function (z) {
      const name = z.lane_id != null ? laneLabel(z.lane_id) : z.zone_id;
      return name + " (" + z.polygon.length + " pts)";
    }).join(", ");
    const draft = draftPoints.length
      ? " | rascunho lane " + activeLaneId + ": " + draftPoints.length + " pts"
      : "";
    preview.textContent = "Salvos: " + (saved || "—") + draft;
  }

  function buildZonePayload() {
    const polygon = draftPoints.map(function (p) { return [p.frame.x, p.frame.y]; });
    if (isCheckout) {
      const laneId = activeLaneId;
      const label = (labelInput && labelInput.value.trim()) || ("Caixa " + laneId);
      laneLabels[laneId] = label;
      return {
        zone_type: "checkout_lane",
        zone_id: "checkout_lane_" + laneId,
        lane_id: laneId,
        label: label,
        polygon: polygon,
      };
    }
    return {
      zone_type: "portal",
      zone_id: "portal",
      label: "Porta (entrada e saída)",
      polygon: polygon,
    };
  }

  async function savePolygon() {
    if (draftPoints.length < 3) {
      setStatus("Adicione pelo menos 3 pontos antes de salvar.", "error");
      return;
    }
    const payload = buildZonePayload();
    const url =
      "/stores/" + config.storeId + "/cameras/" + config.cameraDbId + "/zones";
    setStatus("Salvando polígono…", "pending");
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || "Falha ao salvar zona");
    }
    const data = await response.json();
    const idx = savedZones.findIndex(function (z) { return z.zone_id === data.zone.zone_id; });
    if (idx >= 0) savedZones[idx] = data.zone;
    else savedZones.push(data.zone);
    if (isCheckout && data.zone.lane_id != null) {
      extraLaneIds.delete(data.zone.lane_id);
      laneLabels[data.zone.lane_id] = data.zone.label || laneLabel(data.zone.lane_id);
      renderLaneTabs();
    }
    draftPoints = [];
    renderOverlay();
    setStatus("Polígono salvo: " + data.zone.zone_id, "success");
  }

  async function saveEntryVector(zoneId, vector) {
    const url =
      "/stores/" + config.storeId + "/cameras/" + config.cameraDbId + "/zones/entry-vector";
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ zone_id: zoneId, entry_vector: vector }),
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || "Falha ao salvar sentido");
    }
    const data = await response.json();
    const idx = savedZones.findIndex(function (z) { return z.zone_id === zoneId; });
    if (idx >= 0) savedZones[idx] = data.zone;
    renderOverlay();
    setStatus("Sentido de entrada salvo.", "success");
  }

  async function saveR1MinDuration() {
    if (!r1MinInput) return;
    const value = parseFloat(r1MinInput.value);
    if (!Number.isFinite(value) || value <= 0 || value > 3600) {
      setStatus("Tempo mínimo R1 inválido (1–3600 s).", "error");
      return;
    }
    const url = "/stores/" + config.storeId + "/r1-min-checkout-duration";
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ r1_min_checkout_duration_sec: value }),
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || "Falha ao salvar tempo mínimo R1");
    }
    const data = await response.json();
    r1MinInput.value = String(Math.round(data.r1_min_checkout_duration_sec));
    setStatus("Tempo mínimo R1 salvo: " + r1MinInput.value + " s", "success");
  }

  function onStageClick(event) {
    if (!frameSize.width) return;
    event.preventDefault();
    const point = framePointFromEvent(event);

    if (vectorMode) {
      if (!vectorStart) {
        vectorStart = point.frame;
        setStatus("Clique no destino (dentro da loja) para definir o sentido.", "info");
        return;
      }
      const vector = [
        point.frame.x - vectorStart.x,
        point.frame.y - vectorStart.y,
      ];
      vectorMode = false;
      vectorStart = null;
      const portal = savedZones.find(function (z) { return z.zone_id === "portal"; });
      if (!portal) {
        setStatus("Salve o polígono portal antes de definir o sentido.", "error");
        return;
      }
      saveEntryVector("portal", vector).catch(function (err) {
        setStatus("Erro: " + err.message, "error");
      });
      return;
    }

    draftPoints.push(point);
    renderOverlay();
    setStatus("Ponto " + draftPoints.length + " adicionado. Mínimo 3 para salvar.", "info");
  }

  function revokeImageObjectUrl() {
    if (imageObjectUrl) {
      URL.revokeObjectURL(imageObjectUrl);
      imageObjectUrl = null;
    }
  }

  function clampSeekSeconds(seconds) {
    let value = Math.max(0, Number(seconds) || 0);
    if (videoDuration > 0) {
      value = Math.min(value, Math.max(0, videoDuration - 0.05));
    }
    seekInput.value = String(Math.round(value * 10) / 10);
    return value;
  }

  function savedFrameLabel() {
    return "editor_frames/" + config.storeId + "/" + config.cameraDbId + "/frame.jpg";
  }

  function savedFrameUrl() {
    return (
      "/stores/" + config.storeId + "/cameras/" + config.cameraDbId +
      "/editor-frame?_=" + Date.now()
    );
  }

  function frameEndpoint(action) {
    return "/stores/" + config.storeId + "/cameras/" + config.cameraDbId + "/" + action;
  }

  async function parseFetchError(response) {
    let detail = await response.text();
    try {
      detail = JSON.parse(detail).detail || detail;
    } catch (_err) {
      /* plain text */
    }
    return detail || ("HTTP " + response.status);
  }

  async function showCaptureResponse(response, label) {
    applyCaptureHeaders(response);
    const blob = await response.blob();
    if (!blob.size) {
      throw new Error("Resposta vazia do servidor");
    }
    currentFile = null;
    revokeImageObjectUrl();
    imageObjectUrl = URL.createObjectURL(blob);
    image.onload = function () {
      image.onload = null;
      image.onerror = null;
      onFrameLoaded(label, true);
    };
    image.onerror = function () {
      stage.hidden = true;
      setStatus("Não foi possível decodificar o JPEG retornado.", "error");
    };
    image.src = imageObjectUrl;
  }

  function applyCaptureHeaders(response) {
    const durationHeader = Number(response.headers.get("X-Video-Duration") || 0);
    if (durationHeader > 0) {
      videoDuration = durationHeader;
      seekInput.max = String(Math.floor(videoDuration * 10) / 10);
    }
    const widthHeader = Number(response.headers.get("X-Frame-Width") || 0);
    const heightHeader = Number(response.headers.get("X-Frame-Height") || 0);
    if (widthHeader > 0 && heightHeader > 0) {
      frameSize = { width: widthHeader, height: heightHeader };
    }
  }

  function onFrameLoaded(label, savedOnServer) {
    if (!frameSize.width || !frameSize.height) {
      frameSize = { width: image.naturalWidth, height: image.naturalHeight };
    }
    if (!frameSize.width || !frameSize.height) {
      setStatus("Frame inválido (0×0).", "error");
      stage.hidden = true;
      return;
    }
    stage.hidden = false;
    captureBtn.disabled = false;
    fileName.textContent = label;
    requestAnimationFrame(function () {
      renderOverlay();
    });
    setStatus(
      savedOnServer
        ? "Frame salvo no servidor. Outros dispositivos podem editar sem o vídeo original."
        : "Clique na imagem para adicionar vértices (azul, igual ao ROI). Salve com ≥ 3 pontos.",
      savedOnServer ? "success" : "info"
    );
  }

  function loadImageFromUrl(url, label, savedOnServer) {
    currentFile = null;
    revokeImageObjectUrl();
    image.onload = function () {
      image.onload = null;
      image.onerror = null;
      onFrameLoaded(label, savedOnServer);
    };
    image.onerror = function () {
      stage.hidden = true;
      setStatus("Não foi possível carregar a imagem.", "error");
    };
    image.src = url;
  }

  function loadSavedFrame() {
    loadImageFromUrl(savedFrameUrl(), "Frame salvo no servidor", true);
  }

  async function loadFrameFromStorage() {
    if (captureInProgress) return;
    const date = (videoDateInput && videoDateInput.value || "").trim();
    if (!date) {
      setStatus("Informe a data da gravação (YYYY-MM-DD).", "error");
      return;
    }
    const seconds = clampSeekSeconds(seekInput.value);
    const label =
      "data/raw/video/" + date + "/" + config.cameraCode + ".mp4 → " + savedFrameLabel();
    setStatus("Extraindo frame e salvando no servidor…", "pending");
    currentFile = null;
    captureInProgress = true;

    const formData = new FormData();
    formData.append("date", date);
    formData.append("seconds", String(seconds));

    const url = frameEndpoint("frame-from-storage");

    try {
      const response = await fetch(url, {
        method: "POST",
        body: formData,
        credentials: "same-origin",
      });
      if (!response.ok) {
        throw new Error(await parseFetchError(response));
      }
      await showCaptureResponse(response, label);
    } catch (error) {
      const message =
        error && error.message === "Failed to fetch"
          ? "Falha de rede ou servidor indisponível. Verifique se o painel está rodando e tente de novo."
          : error.message;
      setStatus("Erro: " + message, "error");
    } finally {
      captureInProgress = false;
    }
  }

  async function loadFrameFromUpload() {
    if (captureInProgress) return;
    if (!currentFile) {
      if (videoAvailable) {
        loadFrameFromStorage();
      } else {
        setStatus("Faça upload de um vídeo ou use o frame já salvo no servidor.", "error");
      }
      return;
    }
    const uploadFile = currentFile;
    const uploadName = uploadFile.name || "vídeo";
    const savedLabel = uploadName + " → " + savedFrameLabel();
    const seconds = clampSeekSeconds(seekInput.value);
    const date = (videoDateInput && videoDateInput.value || "").trim();
    setStatus("Extraindo frame e salvando no servidor…", "pending");
    revokeImageObjectUrl();
    captureInProgress = true;
    const formData = new FormData();
    formData.append("video", uploadFile);
    formData.append("seconds", String(seconds));
    if (date) {
      formData.append("date", date);
    }
    const url = frameEndpoint("frame-upload");
    try {
      const response = await fetch(url, {
        method: "POST",
        body: formData,
        credentials: "same-origin",
      });
      if (!response.ok) {
        throw new Error(await parseFetchError(response));
      }
      await showCaptureResponse(response, savedLabel);
      if (date) {
        videoAvailable = true;
      }
    } catch (error) {
      const message =
        error && error.message === "Failed to fetch"
          ? "Falha de rede ou upload interrompido. Vídeos grandes podem demorar — aguarde ou use o MP4 já em data/raw/video/."
          : error.message;
      setStatus("Erro: " + message, "error");
    } finally {
      captureInProgress = false;
    }
  }

  frameWrap.addEventListener("click", onStageClick);
  undoBtn.addEventListener("click", function () {
    draftPoints.pop();
    renderOverlay();
  });
  clearBtn.addEventListener("click", function () {
    draftPoints = [];
    renderOverlay();
  });
  saveBtn.addEventListener("click", function () {
    savePolygon().catch(function (err) {
      setStatus("Erro: " + err.message, "error");
    });
  });
  if (vectorBtn) {
    vectorBtn.addEventListener("click", function () {
      vectorMode = true;
      vectorStart = null;
      setStatus("Clique na origem (lado de fora) e depois no destino (dentro da loja).", "info");
    });
  }
  if (addLaneBtn) {
    addLaneBtn.addEventListener("click", addLane);
  }
  if (deleteLaneBtn) {
    deleteLaneBtn.addEventListener("click", function () {
      deleteActiveLane().catch(function (err) {
        setStatus("Erro: " + err.message, "error");
      });
    });
  }
  if (labelInput) {
    labelInput.addEventListener("input", function () {
      if (!isCheckout) return;
      laneLabels[activeLaneId] = labelInput.value.trim() || ("Caixa " + activeLaneId);
      renderLaneTabs();
    });
  }
  if (r1MinInput) {
    r1MinInput.addEventListener("change", function () {
      saveR1MinDuration().catch(function (err) {
        setStatus("Erro: " + err.message, "error");
      });
    });
  }
  fileInput.addEventListener("change", function () {
    const file = fileInput.files && fileInput.files[0];
    if (file) {
      currentFile = file;
      captureBtn.disabled = false;
      seekInput.value = "0";
      fileName.textContent = file.name + " — clique em Capturar frame";
      setStatus(
        "Arquivo selecionado. Clique em Capturar frame para extrair e salvar em " +
          savedFrameLabel(),
        "info"
      );
    }
  });
  loadFromStorageBtn.addEventListener("click", loadFrameFromStorage);
  captureBtn.addEventListener("click", function () {
    if (currentFile) loadFrameFromUpload();
    else loadFrameFromStorage();
  });
  seekInput.addEventListener("change", function () {
    if (currentFile || videoAvailable) {
      if (currentFile) loadFrameFromUpload();
      else loadFrameFromStorage();
    }
  });
  window.addEventListener("resize", function () {
    requestAnimationFrame(renderOverlay);
  });
  window.addEventListener("beforeunload", revokeImageObjectUrl);

  if (videoDateInput && config.defaultVideoDate) {
    videoDateInput.value = config.defaultVideoDate;
  }
  if (videoDuration > 0) {
    seekInput.max = String(Math.floor(videoDuration * 10) / 10);
  }
  if (config.savedFrameAvailable) {
    captureBtn.disabled = false;
    loadSavedFrame();
  } else if (videoAvailable) {
    captureBtn.disabled = false;
    setStatus(
      "Vídeo disponível no servidor. Clique em Capturar frame — a imagem será salva no servidor para edição em outros dispositivos.",
      "info"
    );
  } else if (config.videoRelpath && !config.savedFrameAvailable) {
    setStatus("Vídeo não encontrado: " + config.videoRelpath + ". Faça upload ou use um frame já salvo.", "error");
  } else {
    setStatus("Faça upload de um vídeo para capturar o frame no servidor.", "info");
  }

  initCheckoutLanes();
})();
