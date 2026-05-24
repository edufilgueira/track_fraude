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
  const sourceVideo = document.getElementById("source-video");

  let frameSize = { width: 0, height: 0 };
  let currentRoi = { ...config.initialRoi };
  let dragStart = null;
  let dragging = false;
  let saveTimer = null;
  let objectUrl = null;
  let imageObjectUrl = null;
  let videoReady = false;
  let useServerExtract = false;
  let currentFile = null;
  let videoDuration = 0;

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

  function revokeObjectUrl() {
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl);
      objectUrl = null;
    }
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

  function applyFrameResponse(response) {
    frameSize = {
      width: Number(response.headers.get("X-Frame-Width") || 0),
      height: Number(response.headers.get("X-Frame-Height") || 0),
    };
    const durationHeader = Number(response.headers.get("X-Video-Duration") || 0);
    if (durationHeader > 0) {
      videoDuration = durationHeader;
      seekInput.max = String(Math.floor(videoDuration * 10) / 10);
    }
    return response.blob().then(function (blob) {
      if (imageObjectUrl) URL.revokeObjectURL(imageObjectUrl);
      imageObjectUrl = URL.createObjectURL(blob);
      image.src = imageObjectUrl;
      stage.hidden = false;
      captureBtn.disabled = false;
    });
  }

  async function captureFrameFromServer() {
    if (!currentFile) {
      setStatus("Selecione um arquivo de vídeo.", "error");
      return;
    }

    const seconds = clampSeekSeconds(seekInput.value);
    setStatus("Extraindo frame no servidor…", "pending");
    roiBox.hidden = true;

    const formData = new FormData();
    formData.append("video", currentFile);
    formData.append("seconds", String(seconds));

    const url =
      "/stores/" + config.storeId + "/cameras/" + config.cameraId + "/frame-upload";

    try {
      const response = await fetch(url, { method: "POST", body: formData });
      if (!response.ok) {
        let detail = await response.text();
        try {
          detail = JSON.parse(detail).detail || detail;
        } catch (_err) {
          /* resposta plain text */
        }
        throw new Error(detail || "Falha ao extrair frame");
      }
      await applyFrameResponse(response);
      if (useServerExtract) {
        setStatus(
          "Frame extraído no servidor (codec não reproduzível no navegador). Arraste para definir o ROI.",
          "info"
        );
      }
    } catch (error) {
      setStatus("Erro ao extrair frame: " + error.message, "error");
    }
  }

  function captureFrameFromBrowser() {
    if (!videoReady || !sourceVideo.videoWidth) {
      setStatus("Selecione um vídeo válido primeiro.", "error");
      return;
    }

    const seconds = clampSeekSeconds(seekInput.value);
    setStatus("Capturando frame…", "pending");
    roiBox.hidden = true;

    const seekAndCapture = function () {
      const canvas = document.createElement("canvas");
      canvas.width = sourceVideo.videoWidth;
      canvas.height = sourceVideo.videoHeight;
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        setStatus("Seu navegador não suporta captura de frame.", "error");
        return;
      }
      ctx.drawImage(sourceVideo, 0, 0, canvas.width, canvas.height);
      frameSize = { width: canvas.width, height: canvas.height };
      image.src = canvas.toDataURL("image/jpeg", 0.92);
      stage.hidden = false;
    };

    if (Math.abs(sourceVideo.currentTime - seconds) < 0.05) {
      seekAndCapture();
      return;
    }

    sourceVideo.onseeked = function () {
      sourceVideo.onseeked = null;
      seekAndCapture();
    };
    sourceVideo.currentTime = seconds;
  }

  function captureFrame() {
    if (useServerExtract) {
      captureFrameFromServer();
    } else {
      captureFrameFromBrowser();
    }
  }

  function startServerExtract() {
    useServerExtract = true;
    videoReady = true;
    captureBtn.disabled = false;
    seekInput.value = "0";
    captureFrameFromServer();
  }

  function tryBrowserDecode(file) {
    useServerExtract = false;
    videoReady = false;
    videoDuration = 0;
    captureBtn.disabled = true;
    stage.hidden = true;
    frameSize = { width: 0, height: 0 };

    revokeObjectUrl();
    objectUrl = URL.createObjectURL(file);
    sourceVideo.onloadedmetadata = null;
    sourceVideo.onerror = null;

    sourceVideo.onloadedmetadata = function () {
      if (!sourceVideo.videoWidth || !sourceVideo.videoHeight) {
        startServerExtract();
        return;
      }
      videoReady = true;
      captureBtn.disabled = false;
      videoDuration = Number.isFinite(sourceVideo.duration) ? sourceVideo.duration : 0;
      if (videoDuration > 0) {
        seekInput.max = String(Math.floor(videoDuration * 10) / 10);
      }
      setStatus("Vídeo carregado no navegador. Capturando frame inicial…", "info");
      seekInput.value = "0";
      captureFrameFromBrowser();
    };

    sourceVideo.onerror = function () {
      startServerExtract();
    };

    sourceVideo.src = objectUrl;
    sourceVideo.load();
  }

  function loadSelectedFile(file) {
    if (!file) return;

    currentFile = file;
    fileName.textContent = file.name + " (" + Math.round(file.size / (1024 * 1024)) + " MB)";
    setStatus("Carregando vídeo…", "pending");
    tryBrowserDecode(file);
  }

  image.addEventListener("load", function () {
    applyRoi(currentRoi, false);
    if (!useServerExtract) {
      setStatus(
        "Frame pronto. Arraste sobre o timestamp para definir o ROI (salva ao soltar).",
        "info"
      );
    }
  });

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

  captureBtn.addEventListener("click", captureFrame);
  seekInput.addEventListener("change", captureFrame);
  window.addEventListener("resize", function () {
    renderRoiBox(currentRoi);
  });
  window.addEventListener("beforeunload", revokeObjectUrl);
})();
