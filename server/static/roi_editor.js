(function () {
  const config = window.roiEditorConfig;
  if (!config) return;

  const stage = document.getElementById("roi-stage");
  const image = document.getElementById("frame-image");
  const roiBox = document.getElementById("roi-box");
  const preview = document.getElementById("roi-preview");
  const status = document.getElementById("roi-status");
  const fileInput = document.getElementById("video-file");
  const fileName = document.getElementById("video-file-name");
  const seekInput = document.getElementById("seek-seconds");
  const captureBtn = document.getElementById("capture-frame");
  const videoDateInput = document.getElementById("video-date");
  const loadFromStorageBtn = document.getElementById("load-from-storage");

  let frameSize = { width: 0, height: 0 };
  let currentRoi = { ...config.initialRoi };
  let dragStart = null;
  let dragging = false;
  let saveTimer = null;
  let imageObjectUrl = null;
  let videoDuration = config.videoDuration || 0;
  let currentFile = null;
  let videoAvailable = !!config.videoAvailable;
  let captureInProgress = false;

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

  function displayRectFromRoi(roi) {
    const scale = scaleFactors();
    return {
      left: roi.x / scale.x,
      top: roi.y / scale.y,
      width: roi.width / scale.x,
      height: roi.height / scale.y,
    };
  }

  function roiFromDisplayRect(rect) {
    const scale = scaleFactors();
    const x = Math.max(0, Math.round(rect.left * scale.x));
    const y = Math.max(0, Math.round(rect.top * scale.y));
    const width = Math.max(1, Math.round(rect.width * scale.x));
    const height = Math.max(1, Math.round(rect.height * scale.y));
    const maxWidth = Math.max(1, frameSize.width - x);
    const maxHeight = Math.max(1, frameSize.height - y);
    return {
      x,
      y,
      width: Math.min(width, maxWidth),
      height: Math.min(height, maxHeight),
    };
  }

  function renderRoiBox(roi) {
    if (!frameSize.width || !roi || roi.width <= 0 || roi.height <= 0) {
      roiBox.hidden = true;
      return;
    }
    const rect = displayRectFromRoi(roi);
    roiBox.hidden = false;
    roiBox.style.left = rect.left + "px";
    roiBox.style.top = rect.top + "px";
    roiBox.style.width = rect.width + "px";
    roiBox.style.height = rect.height + "px";
  }

  function updatePreview(roi) {
    preview.textContent =
      "ROI: x=" + roi.x + ", y=" + roi.y +
      ", width=" + roi.width + ", height=" + roi.height +
      "  →  canto inferior direito: (" + (roi.x + roi.width) + ", " + (roi.y + roi.height) + ")";
  }

  async function saveRoi(roi) {
    const url = "/stores/" + config.storeId + "/cameras/" + config.cameraId + "/roi";
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ocr_x: roi.x,
        ocr_y: roi.y,
        ocr_width: roi.width,
        ocr_height: roi.height,
      }),
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || "Falha ao salvar ROI");
    }
    return response.json();
  }

  function scheduleSave(roi) {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(async function () {
      try {
        setStatus("Salvando ROI…", "pending");
        await saveRoi(roi);
        setStatus("ROI salvo automaticamente.", "success");
      } catch (error) {
        setStatus("Erro ao salvar: " + error.message, "error");
      }
    }, 250);
  }

  function applyRoi(roi, persist) {
    currentRoi = roi;
    renderRoiBox(roi);
    updatePreview(roi);
    if (persist) scheduleSave(roi);
  }

  function pointerPosition(event) {
    const bounds = stage.getBoundingClientRect();
    return {
      x: Math.min(Math.max(event.clientX - bounds.left, 0), bounds.width),
      y: Math.min(Math.max(event.clientY - bounds.top, 0), bounds.height),
    };
  }

  function onPointerDown(event) {
    if (!frameSize.width) return;
    event.preventDefault();
    dragging = true;
    dragStart = pointerPosition(event);
    roiBox.hidden = false;
    roiBox.style.left = dragStart.x + "px";
    roiBox.style.top = dragStart.y + "px";
    roiBox.style.width = "0px";
    roiBox.style.height = "0px";
    stage.setPointerCapture(event.pointerId);
  }

  function onPointerMove(event) {
    if (!dragging || !dragStart) return;
    event.preventDefault();
    const point = pointerPosition(event);
    const left = Math.min(dragStart.x, point.x);
    const top = Math.min(dragStart.y, point.y);
    const width = Math.abs(point.x - dragStart.x);
    const height = Math.abs(point.y - dragStart.y);
    roiBox.style.left = left + "px";
    roiBox.style.top = top + "px";
    roiBox.style.width = width + "px";
    roiBox.style.height = height + "px";
  }

  function onPointerUp(event) {
    if (!dragging || !dragStart) return;
    event.preventDefault();
    dragging = false;
    stage.releasePointerCapture(event.pointerId);
    const point = pointerPosition(event);
    const left = Math.min(dragStart.x, point.x);
    const top = Math.min(dragStart.y, point.y);
    const width = Math.abs(point.x - dragStart.x);
    const height = Math.abs(point.y - dragStart.y);
    dragStart = null;
    if (width < 4 || height < 4) {
      renderRoiBox(currentRoi);
      return;
    }
    const roi = roiFromDisplayRect({ left, top, width, height });
    applyRoi(roi, true);
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
    return "editor_frames/" + config.storeId + "/" + config.cameraId + "/frame.jpg";
  }

  function savedFrameUrl() {
    return (
      "/stores/" + config.storeId + "/cameras/" + config.cameraId +
      "/editor-frame?_=" + Date.now()
    );
  }

  function frameEndpoint(action) {
    return "/stores/" + config.storeId + "/cameras/" + config.cameraId + "/" + action;
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
    roiBox.hidden = true;
    revokeImageObjectUrl();
    imageObjectUrl = URL.createObjectURL(blob);
    image.onload = function () {
      image.onload = null;
      image.onerror = null;
      onFrameLoaded(label, true);
    };
    image.onerror = function () {
      image.onload = null;
      image.onerror = null;
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
      frameSize = {
        width: image.naturalWidth,
        height: image.naturalHeight,
      };
    }
    if (!frameSize.width || !frameSize.height) {
      setStatus("Frame inválido (0×0).", "error");
      stage.hidden = true;
      return;
    }
    stage.hidden = false;
    captureBtn.disabled = false;
    fileName.textContent = label;
    applyRoi(currentRoi, false);
    setStatus(
      savedOnServer
        ? "Frame salvo no servidor. Outros dispositivos podem editar sem o vídeo original."
        : "Frame pronto. Arraste sobre o timestamp para definir o ROI (salva ao soltar).",
      savedOnServer ? "success" : "info"
    );
  }

  function loadImageFromUrl(url, label, savedOnServer) {
    roiBox.hidden = true;
    revokeImageObjectUrl();
    image.onload = function () {
      image.onload = null;
      image.onerror = null;
      onFrameLoaded(label, savedOnServer);
    };
    image.onerror = function () {
      image.onload = null;
      image.onerror = null;
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
      setStatus("Erro ao extrair frame: " + message, "error");
    } finally {
      captureInProgress = false;
    }
  }

  function captureFrame() {
    if (currentFile) {
      loadFrameFromUpload();
    } else {
      loadFrameFromStorage();
    }
  }

  function loadSelectedFile(file) {
    if (!file) return;
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

  stage.addEventListener("pointerdown", onPointerDown);
  stage.addEventListener("pointermove", onPointerMove);
  stage.addEventListener("pointerup", onPointerUp);
  stage.addEventListener("pointercancel", function () {
    dragging = false;
    dragStart = null;
    renderRoiBox(currentRoi);
  });

  fileInput.addEventListener("change", function () {
    const file = fileInput.files && fileInput.files[0];
    if (file) loadSelectedFile(file);
  });

  loadFromStorageBtn.addEventListener("click", loadFrameFromStorage);
  captureBtn.addEventListener("click", captureFrame);
  seekInput.addEventListener("change", function () {
    if (currentFile || videoAvailable) captureFrame();
  });
  window.addEventListener("resize", function () {
    renderRoiBox(currentRoi);
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
    setStatus(
      "Vídeo não encontrado: " + config.videoRelpath + ". Faça upload ou use um frame já salvo.",
      "error"
    );
  } else {
    setStatus("Faça upload de um vídeo para capturar o frame no servidor.", "info");
  }
})();
