#!/usr/bin/env node
/**
 * API POS provisória — lê data/pos/transactions.json e filtra por intervalo.
 *
 * Uso:
 *   node data/pos/server.js
 *   GET /transactions?store_id=LOJA-01&date=2026-05-22&t_from=2026-05-22T10:00:00&t_to=2026-05-22T10:02:00&lane_id=1
 */

const http = require("http");
const fs = require("fs");
const path = require("path");
const { URL } = require("url");

const PORT = Number(process.env.PORT || 3099);
const HOST = process.env.HOST || "127.0.0.1";
const DATA_FILE = path.join(__dirname, "transactions.json");
const DEFAULT_STATUSES = new Set(["paid", "completed"]);

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

function loadCatalog() {
  const raw = fs.readFileSync(DATA_FILE, "utf8");
  return JSON.parse(raw);
}

function listExports(catalog) {
  if (Array.isArray(catalog.exports)) {
    return catalog.exports.map((item) => ({
      timezone: item.timezone || catalog.timezone || "America/Sao_Paulo",
      ...item,
    }));
  }
  return [
    {
      store_id: catalog.store_id,
      date: catalog.date,
      timezone: catalog.timezone || "America/Sao_Paulo",
      transactions: catalog.transactions || [],
    },
  ];
}

function findExport(catalog, storeId, date) {
  const match = listExports(catalog).find(
    (item) => item.store_id === storeId && item.date === date
  );
  if (!match) {
    const err = new Error(`POS não encontrado para store_id=${storeId} date=${date}`);
    err.statusCode = 404;
    throw err;
  }
  return match;
}

function parseDateTime(value, date, fieldName) {
  if (!value) {
    const err = new Error(`Parâmetro obrigatório: ${fieldName}`);
    err.statusCode = 400;
    throw err;
  }
  const text = String(value);
  const iso = text.includes("T") ? text : `${date}T${text}`;
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    const err = new Error(`${fieldName} inválido: ${value}`);
    err.statusCode = 400;
    throw err;
  }
  return parsed;
}

function parseStatuses(raw) {
  if (!raw) return DEFAULT_STATUSES;
  return new Set(
    String(raw)
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean)
  );
}

function filterTransactions(exportDay, { tFrom, tTo, laneId, statuses }) {
  return (exportDay.transactions || [])
    .filter((tx) => {
      const sale = new Date(tx.t_sale);
      if (sale < tFrom || sale > tTo) return false;
      if (laneId != null && Number(tx.lane_id) !== Number(laneId)) return false;
      if (!statuses.has(String(tx.status))) return false;
      return true;
    })
    .sort((a, b) => new Date(a.t_sale) - new Date(b.t_sale));
}

function sendJson(res, statusCode, payload) {
  const body = JSON.stringify(payload, null, 2);
  res.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
  });
  res.end(body);
}

async function handleRequest(req, res) {
  const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);

  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    });
    res.end();
    return;
  }

  if (url.pathname === "/health") {
    sendJson(res, 200, { ok: true, data_file: path.basename(DATA_FILE) });
    return;
  }

  try {
    const catalog = loadCatalog();

    if (url.pathname === "/day") {
      const storeId = url.searchParams.get("store_id");
      const date = url.searchParams.get("date");
      if (!storeId || !date) {
        sendJson(res, 400, { error: "Informe store_id e date" });
        return;
      }
      const exportDay = findExport(catalog, storeId, date);
      sendJson(res, 200, exportDay);
      return;
    }

    if (url.pathname === "/transactions" && req.method === "GET") {
      const storeId = url.searchParams.get("store_id");
      const date = url.searchParams.get("date");
      const laneIdRaw = url.searchParams.get("lane_id");
      const laneId = laneIdRaw == null || laneIdRaw === "" ? null : Number(laneIdRaw);
      const statuses = parseStatuses(url.searchParams.get("statuses"));

      if (!storeId || !date) {
        sendJson(res, 400, { error: "Informe store_id e date" });
        return;
      }

      const tFrom = parseDateTime(url.searchParams.get("t_from"), date, "t_from");
      const tTo = parseDateTime(url.searchParams.get("t_to"), date, "t_to");
      const exportDay = findExport(catalog, storeId, date);
      const transactions = filterTransactions(exportDay, {
        tFrom,
        tTo,
        laneId,
        statuses,
      });

      sendJson(res, 200, {
        store_id: storeId,
        date,
        timezone: exportDay.timezone,
        t_from: tFrom.toISOString(),
        t_to: tTo.toISOString(),
        lane_id: laneId,
        count: transactions.length,
        transactions,
      });
      return;
    }

    if (url.pathname === "/transactions/query" && req.method === "POST") {
      const body = JSON.parse((await readBody(req)) || "{}");
      const storeId = body.store_id;
      const date = body.date;
      if (!storeId || !date) {
        sendJson(res, 400, { error: "Informe store_id e date no body" });
        return;
      }
      const laneId = body.lane_id == null ? null : Number(body.lane_id);
      const statuses = parseStatuses(body.statuses && body.statuses.join(","));
      const tFrom = parseDateTime(body.t_from, date, "t_from");
      const tTo = parseDateTime(body.t_to, date, "t_to");
      const exportDay = findExport(catalog, storeId, date);
      const transactions = filterTransactions(exportDay, {
        tFrom,
        tTo,
        laneId,
        statuses,
      });
      sendJson(res, 200, {
        store_id: storeId,
        date,
        timezone: exportDay.timezone,
        t_from: tFrom.toISOString(),
        t_to: tTo.toISOString(),
        lane_id: laneId,
        count: transactions.length,
        transactions,
      });
      return;
    }

    sendJson(res, 404, {
      error: "Rota não encontrada",
      routes: [
        "GET /health",
        "GET /day?store_id=&date=",
        "GET /transactions?store_id=&date=&t_from=&t_to=&lane_id=",
        "POST /transactions/query { store_id, date, t_from, t_to, lane_id? }",
      ],
    });
  } catch (error) {
    sendJson(res, error.statusCode || 500, {
      error: error.message || String(error),
    });
  }
}

const server = http.createServer((req, res) => {
  handleRequest(req, res).catch((error) => {
    sendJson(res, 500, { error: error.message || String(error) });
  });
});

server.listen(PORT, HOST, () => {
  console.log(`POS mock API em http://${HOST}:${PORT}`);
  console.log(`Arquivo: ${DATA_FILE}`);
});

server.on("error", (error) => {
  if (error.code === "EADDRINUSE") {
    console.error(
      `Porta ${PORT} já em uso. Encerre o processo anterior ou use outra porta:\n` +
        `  set PORT=3100 && node data/pos/server.js`
    );
    process.exit(1);
  }
  throw error;
});
