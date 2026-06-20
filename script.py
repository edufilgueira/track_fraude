#!/usr/bin/env python3
"""
Download Intelbras MHDX 1404.

  python3 script.py          # baixa cada .dav listado pelo NVR (loadfile)
  python3 script.py --list   # só lista
  NVR_DEBUG=1 python3 script.py

Fluxo: busca mediaFileFind → um loadfile por arquivo/gravação → manifest.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import requests
from requests.auth import HTTPDigestAuth
from urllib3.exceptions import IncompleteRead as Urllib3IncompleteRead

# ============ CONFIGURE AQUI ============
NVR_IP = os.environ.get("NVR_IP", "192.168.0.108")
USER = os.environ.get("NVR_USER", "admin")
PASS = os.environ.get("NVR_PASS", "V03admin%")

# Câmera a baixar (1–4). Troque aqui para outra câmera (ex.: CHANNEL = 2).
# Arquivos ficam em /1/dav/, /2/dav/, etc. No MHDX 1404 a API usa índice N+1 (interno).
CHANNEL = 1

START = "2026-6-10 00:00:00"
END   = "2026-6-11 00:00:00"

OUT_DIR = Path(__file__).parent / "nvr_videos"
FIND_PAGE_SIZE = 50
MIN_DAV_BYTES = 50_000
LARGE_DOWNLOAD_BYTES = 100_000_000
# Se loadfile do arquivo inteiro falhar, fatia esse trecho em janelas de N minutos
LOADFILE_SUB_MINUTES = 10
# Trechos mais curtos que isso são ignorados (comum em gravação por movimento)
MIN_CLIP_SECONDS = 60
# Arquivos maiores que isso não usam RPC (curl:18 no MHDX ~900 MB)
RPC_MAX_BYTES = 200_000_000

# --- Tempos de espera (segundos) entre downloads no NVR ---
WAIT_AFTER_LARGE_DOWNLOAD_SEC = 120   # após arquivo grande (ver LARGE_DOWNLOAD_BYTES)
WAIT_BETWEEN_DOWNLOADS_SEC = 10       # pausa normal entre um chunk e outro
WAIT_AFTER_STOPLOAD_SEC = 3           # após encerrar sessão loadfile (stopLoad)
WAIT_ON_RETRY_SEC = 30                # pausa base ao re-tentar chunk que falhou
CHUNK_RETRIES = 2                     # quantas vezes re-tenta cada janela

# True = converte .dav → .mp4 com ffmpeg ao final; False = só baixa os .dav
CONVERT_MP4 = True
if "NVR_CONVERT_MP4" in os.environ:
    CONVERT_MP4 = os.environ["NVR_CONVERT_MP4"].lower() in ("1", "true", "yes")

DEBUG = os.environ.get("NVR_DEBUG", "").lower() in ("1", "true", "yes")
# ========================================


def parse_dt(value: str) -> datetime:
    value = value.strip()
    m = re.match(
        r"^(\d{4})-(\d{1,2})-(\d{1,2}) (\d{1,2}):(\d{2}):(\d{2})$",
        value,
    )
    if not m:
        raise ValueError(f"data/hora inválida: {value!r}")
    return datetime(
        int(m.group(1)),
        int(m.group(2)),
        int(m.group(3)),
        int(m.group(4)),
        int(m.group(5)),
        int(m.group(6)),
    )


def format_nvr_time(dt: datetime) -> str:
    return f"{dt.year}-{dt.month}-{dt.day} {dt.strftime('%H:%M:%S')}"


def iter_time_chunks_minutes(start: str, end: str, minutes: int):
    cur = parse_dt(start)
    stop = parse_dt(end)
    step = timedelta(minutes=minutes)
    while cur < stop:
        nxt = min(cur + step, stop)
        yield format_nvr_time(cur), format_nvr_time(nxt)
        cur = nxt


def valid_dav(path: Path) -> bool:
    return path.exists() and path.stat().st_size > MIN_DAV_BYTES


def chunk_meta_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".meta")


def write_chunk_meta(
    path: Path,
    start: str,
    end: str,
    *,
    rec: Recording | None = None,
    method: str = "loadfile",
) -> None:
    lines = [start.strip(), end.strip()]
    if rec is not None and method == "rpc":
        lines.extend([rec.start_time, rec.end_time, method])
    chunk_meta_path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_segment_meta(path: Path, default_rec: Recording) -> DavSegment:
    meta = chunk_meta_path(path)
    if meta.exists():
        lines = meta.read_text(encoding="utf-8").strip().splitlines()
        if len(lines) >= 2:
            seg_start, seg_end = lines[0], lines[1]
            if len(lines) >= 5 and lines[4] == "rpc":
                rec = Recording(
                    channel=default_rec.channel,
                    filepath=default_rec.filepath,
                    start_time=lines[2],
                    end_time=lines[3],
                    length=default_rec.length,
                )
                return DavSegment(path, rec, seg_start, seg_end, already_clipped=False)
            return DavSegment(path, default_rec, seg_start, seg_end, already_clipped=True)
    return DavSegment(path, default_rec, START, END, already_clipped=True)


def chunk_matches_window(path: Path, start: str, end: str) -> bool:
    if not valid_dav(path):
        return False
    meta = chunk_meta_path(path)
    if not meta.exists():
        return False
    lines = meta.read_text(encoding="utf-8").strip().splitlines()
    return len(lines) >= 2 and lines[0] == start.strip() and lines[1] == end.strip()


def sort_dav_paths(paths: list[Path]) -> list[Path]:
    def key(path: Path) -> tuple[int, int, str]:
        m = re.match(r"(?:chunk|block|win|nvr)_(\d+)(?:_(\d+))?\.dav$", path.name)
        if m:
            return (int(m.group(1)), int(m.group(2) or 0), path.name)
        return (999_999, 0, path.name)

    return sorted(paths, key=key)


def clip_window_to_recordings(
    blocks: list[tuple[Recording, str, str]],
    w_start: str,
    w_end: str,
) -> tuple[str, str] | None:
    """Recorte da janela para o trecho que realmente tem gravação no NVR."""
    ws = parse_dt(w_start)
    we = parse_dt(w_end)
    clip_start: datetime | None = None
    clip_end: datetime | None = None
    for _rec, seg_start, seg_end in blocks:
        rs = parse_dt(seg_start)
        re = parse_dt(seg_end)
        if re <= ws or rs >= we:
            continue
        overlap_start = max(rs, ws)
        overlap_end = min(re, we)
        clip_start = overlap_start if clip_start is None else min(clip_start, overlap_start)
        clip_end = overlap_end if clip_end is None else max(clip_end, overlap_end)
    if clip_start is None or clip_end is None or clip_end <= clip_start:
        return None
    return format_nvr_time(clip_start), format_nvr_time(clip_end)


def window_overlaps_recordings(
    blocks: list[tuple[Recording, str, str]],
    w_start: str,
    w_end: str,
) -> bool:
    return clip_window_to_recordings(blocks, w_start, w_end) is not None


def expected_interval_seconds(start: str, end: str) -> float:
    return (parse_dt(end) - parse_dt(start)).total_seconds()


def probe_media_duration(path: Path) -> float | None:
    """Duração decodificável em segundos (ffprobe). None se indisponível."""
    if not shutil.which("ffprobe") or not path.exists():
        return None
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-fflags",
        "+genpts+discardcorrupt",
        "-err_detect",
        "ignore_err",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
    except (subprocess.SubprocessError, OSError):
        return None
    if out.returncode != 0:
        dbg(f"ffprobe falhou ({path.name}): {out.stderr.strip()}")
        return None
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


def format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def media_duration_ok(path: Path, start: str, end: str, *, tolerance: float = 90) -> bool:
    actual = probe_media_duration(path)
    if actual is None:
        return True
    expected = expected_interval_seconds(start, end)
    return actual >= expected - tolerance


def loadfile_result_ok(path: Path, start: str, end: str) -> bool:
    """loadfile válido: duração decodificável compatível com a janela pedida."""
    if not valid_dav(path):
        return False
    return media_duration_ok(path, start, end)


def warn_if_short_media(path: Path, start: str, end: str, *, label: str) -> None:
    expected = expected_interval_seconds(start, end)
    actual = probe_media_duration(path)
    if actual is None:
        return
    short_by = expected - actual
    if short_by > 90:
        print(
            f"\nAVISO: {label} decodifica só ~{format_duration(actual)} "
            f"(pedido ~{format_duration(expected)}). "
            "O .dav pode estar truncado — o script tentará RPC ou re-download."
        )


def cached_chunk_ok(path: Path, start: str, end: str) -> bool:
    if not chunk_matches_window(path, start, end):
        return False
    return media_duration_ok(path, start, end)


def clip_timeout(start: str, end: str) -> int:
    secs = max(60, int((parse_dt(end) - parse_dt(start)).total_seconds()))
    return max(600, min(7200, secs * 3))


@dataclass
class Recording:
    channel: int
    filepath: str
    start_time: str
    end_time: str
    length: int
    cut_length: int | None = None


@dataclass
class DavSegment:
    path: Path
    rec: Recording
    seg_start: str
    seg_end: str
    already_clipped: bool


def dbg(msg: str) -> None:
    if DEBUG:
        print(f"  [debug] {msg}")


class NVRClient:
    def __init__(self, host: str, user: str, password: str) -> None:
        self.host = host
        self.user = user
        self.password = password
        self.base = f"http://{host}"
        self.session = requests.Session()
        self.session.auth = HTTPDigestAuth(user, password)
        self.rpc_session: int | str = 0
        self._rpc_id = 0
        self.rpc_logged_in = False
        self._last_download_finished = 0.0
        self._loadfile_prefs: tuple[int, str, bool, str] | None = None

    def _pause_before_download(self) -> None:
        elapsed = time.time() - self._last_download_finished
        if elapsed < WAIT_BETWEEN_DOWNLOADS_SEC:
            time.sleep(WAIT_BETWEEN_DOWNLOADS_SEC - elapsed)

    def _pause_after_download(self, nbytes: int) -> None:
        if nbytes >= LARGE_DOWNLOAD_BYTES:
            delay = WAIT_AFTER_LARGE_DOWNLOAD_SEC
        else:
            delay = WAIT_BETWEEN_DOWNLOADS_SEC
        dbg(f"pausa {delay}s após download ({nbytes:,} bytes)")
        time.sleep(delay)
        self._last_download_finished = time.time()
        if nbytes >= LARGE_DOWNLOAD_BYTES:
            self.login(quiet=True)

    def _reset_http_session(self) -> None:
        auth = self.session.auth
        self.session.close()
        self.session = requests.Session()
        self.session.auth = auth

    def loadfile_stop(self) -> None:
        for action in ("stopLoad", "stop"):
            try:
                self.session.get(
                    f"{self.base}/cgi-bin/loadfile.cgi",
                    params={"action": action},
                    timeout=10,
                )
            except requests.RequestException:
                pass
        if WAIT_AFTER_STOPLOAD_SEC > 0:
            time.sleep(WAIT_AFTER_STOPLOAD_SEC)

    @staticmethod
    def api_channel(camera: int) -> int:
        """MHDX 1404: câmera painel N → índice API N+1 (CHANNEL=1 → ch=2)."""
        return camera + 1

    def api_loadfile_channels(self, camera: int) -> list[int]:
        return [self.api_channel(camera)]

    def prime_window(self, channel: int, start: str, end: str) -> None:
        """Busca rápida no intervalo — alguns firmwares exigem antes do loadfile."""
        api_ch = self.api_channel(channel)
        obj = self.cgi_create()
        try:
            for _mode, url in self._cgi_find_urls(obj, api_ch, start, end):
                r = self.session.get(url, timeout=20)
                if "Bad Request" not in r.text and not r.text.strip().startswith("Error"):
                    self.session.get(
                        f"{self.base}/cgi-bin/mediaFileFind.cgi",
                        params={"action": "findNextFile", "object": obj, "count": 1},
                        timeout=20,
                    )
                    return
        finally:
            self.cgi_destroy(obj)

    @staticmethod
    def _is_login_challenge(data: dict) -> bool:
        err = data.get("error") or {}
        if err.get("code") == 268632079:
            return True
        msg = str(err.get("message", "")).lower()
        return "login challenge" in msg

    def login(self, *, quiet: bool = False) -> bool:
        """Login RPC2 (opcional). Código 268632079 no passo 1 = challenge normal."""
        url = f"{self.base}/RPC2_Login"

        for client_type, login_type in (("Web3.0", None), ("", "Direct")):
            self._rpc_id += 1
            params1: dict[str, str] = {
                "userName": self.user,
                "password": "",
                "clientType": client_type,
            }
            if login_type:
                params1["loginType"] = login_type

            r1 = self.session.post(
                url,
                json={
                    "method": "global.login",
                    "params": params1,
                    "id": self._rpc_id,
                    "session": 0,
                },
                timeout=30,
            )
            d1 = r1.json()
            dbg(f"login step1 ({client_type!r}): {d1}")

            if not self._is_login_challenge(d1) and not d1.get("params"):
                continue

            p1 = d1.get("params") or {}
            if "realm" not in p1 or "random" not in p1:
                continue

            self.rpc_session = d1.get("session", 0)
            realm = p1["realm"]
            random = p1["random"]

            pwd_hash = hashlib.md5(
                f"{self.user}:{realm}:{self.password}".encode()
            ).hexdigest().upper()
            pass_hash = hashlib.md5(
                f"{self.user}:{random}:{pwd_hash}".encode()
            ).hexdigest().upper()

            params2: dict[str, str] = {
                "userName": self.user,
                "password": pass_hash,
                "clientType": client_type,
                "authorityType": "Default",
                "passwordType": "Default",
            }
            if login_type:
                params2["loginType"] = login_type

            self._rpc_id += 1
            r2 = self.session.post(
                url,
                json={
                    "method": "global.login",
                    "params": params2,
                    "id": self._rpc_id,
                    "session": self.rpc_session,
                },
                timeout=30,
            )
            d2 = r2.json()
            dbg(f"login step2: {d2}")
            if d2.get("result"):
                self.rpc_session = d2.get("session", self.rpc_session)
                self.rpc_logged_in = True
                if not quiet:
                    print("login RPC2: OK")
                return True

        if not quiet:
            print("login RPC2: pulado (busca/download usam HTTP Digest)")
        return False

    def rpc(self, method: str, params: dict | None = None) -> dict:
        self._rpc_id += 1
        body = {
            "method": method,
            "params": params if params is not None else {},
            "id": self._rpc_id,
            "session": self.rpc_session,
        }
        dbg(f"RPC {method} {params}")
        r = self.session.post(f"{self.base}/RPC2", json=body, timeout=60)
        data = r.json()
        if data.get("error"):
            raise RuntimeError(f"{method}: {data['error']}")
        return data

    @staticmethod
    def encode_start(value: str) -> str:
        # Dahua CGI: 2021-10-4%2010:00:00%20  (':' literal, espaço final %20)
        return value.strip().replace(" ", "%20") + "%20"

    @staticmethod
    def encode_end(value: str) -> str:
        return value.strip().replace(" ", "%20")

    def cgi_create(self) -> str:
        r = self.session.get(
            f"{self.base}/cgi-bin/mediaFileFind.cgi",
            params={"action": "factory.create"},
            timeout=30,
        )
        m = re.search(r"object=(\d+)", r.text) or re.search(r"result=(\d+)", r.text)
        if not m:
            raise RuntimeError(f"factory.create: {r.text.strip()}")
        return m.group(1)

    def cgi_destroy(self, obj: str) -> None:
        self.session.get(
            f"{self.base}/cgi-bin/mediaFileFind.cgi",
            params={"action": "destroy", "object": obj},
            timeout=15,
        )

    def _cgi_find_urls(self, obj: str, channel: int, start: str, end: str) -> list[tuple[str, str]]:
        st, en = start.strip(), end.strip()
        return [
            (
                "quote-trail",
                (
                    f"{self.base}/cgi-bin/mediaFileFind.cgi?"
                    f"action=findFile&object={obj}"
                    f"&condition.Channel={channel}"
                    f"&condition.StartTime={quote(st + ' ', safe='')}"
                    f"&condition.EndTime={quote(en, safe='')}"
                ),
            ),
            (
                "dahua",
                (
                    f"{self.base}/cgi-bin/mediaFileFind.cgi?"
                    f"action=findFile&object={obj}"
                    f"&condition.Channel={channel}"
                    f"&condition.StartTime={self.encode_start(st)}"
                    f"&condition.EndTime={self.encode_end(en)}"
                ),
            ),
        ]

    def cgi_find(self, channel: int, start: str, end: str) -> list[Recording]:
        for mode in ("quote-trail", "dahua"):
            obj = self.cgi_create()
            try:
                urls = dict(self._cgi_find_urls(obj, channel, start, end))
                url = urls[mode]
                dbg(f"CGI {mode} GET {url}")
                r = self.session.get(url, timeout=30)
                if "Bad Request" in r.text or r.text.strip().startswith("Error"):
                    dbg(f"CGI findFile ({mode}): {r.text.strip()}")
                    continue

                recs = self._cgi_fetch_all(obj)
                if recs:
                    dbg(f"CGI ok via {mode} ({len(recs)} arquivo(s))")
                    return recs
            finally:
                self.cgi_destroy(obj)
        return []

    def _cgi_fetch_all(self, obj: int) -> list[Recording]:
        all_recs: list[Recording] = []
        while True:
            r = self.session.get(
                f"{self.base}/cgi-bin/mediaFileFind.cgi",
                params={
    "action": "findNextFile",
    "object": obj,
                    "count": FIND_PAGE_SIZE,
                },
                timeout=60,
            )
            batch = self._parse_cgi_items(r.text)
            if not batch:
                break
            all_recs.extend(batch)
            if len(batch) < FIND_PAGE_SIZE:
                break
        return all_recs

    def rpc_find(self, channel: int, start: str, end: str) -> list[Recording]:
        created = self.rpc("mediaFileFind.factory.create")
        obj = created.get("result")
        if obj is None:
            raise RuntimeError(f"factory.create sem result: {created}")

        try:
            for cond in (
                {
                    "Channel": channel,
                    "StartTime": start.strip(),
                    "EndTime": end.strip(),
                    "Types": ["dav"],
                },
                {
                    "Channel": channel,
                    "StartTime": start.strip(),
                    "EndTime": end.strip(),
                },
            ):
                try:
                    self.rpc(
                        "mediaFileFind.findFile",
                        {"object": obj, "condition": cond},
                    )
                except RuntimeError as exc:
                    dbg(f"RPC findFile cond={cond}: {exc}")
                    continue

                recs = self._rpc_fetch_all(obj)
                if recs:
                    return recs
            return []
        finally:
            for method in ("mediaFileFind.close", "mediaFileFind.destroy"):
                try:
                    self.rpc(method, {"object": obj})
                    break
                except RuntimeError:
                    pass

    def _rpc_fetch_all(self, obj: int) -> list[Recording]:
        all_recs: list[Recording] = []
        while True:
            data = self.rpc(
                "mediaFileFind.findNextFile",
                {"object": obj, "count": FIND_PAGE_SIZE},
            )
            batch = self._parse_rpc_files(data)
            if not batch:
                break
            all_recs.extend(batch)
            if len(batch) < FIND_PAGE_SIZE:
                break
        return all_recs

    @staticmethod
    def _parse_cgi_items(text: str) -> list[Recording]:
        if not re.search(r"found=[1-9]", text):
            return []
        rows: dict[int, dict[str, str]] = {}
        for line in text.splitlines():
            m = re.match(r"items\[(\d+)\]\.(\w+)=(.*)", line)
            if m:
                rows.setdefault(int(m.group(1)), {})[m.group(2)] = m.group(3).strip()
        out: list[Recording] = []
        for idx in sorted(rows):
            r = rows[idx]
            if "FilePath" not in r:
                continue
            out.append(
                Recording(
                    channel=int(r.get("Channel", 0)),
                    filepath=r["FilePath"],
                    start_time=r.get("StartTime", ""),
                    end_time=r.get("EndTime", ""),
                    length=int(r.get("Length", 0)),
                    cut_length=int(r["CutLength"]) if "CutLength" in r else None,
                )
            )
        return out

    @staticmethod
    def _parse_rpc_files(data: dict) -> list[Recording]:
        params = data.get("params") or {}
        files = params.get("infos") or params.get("files") or data.get("result") or []
        if isinstance(files, dict):
            files = [files]
        if not isinstance(files, list):
            return []

        out: list[Recording] = []
        for f in files:
            if not isinstance(f, dict) or "FilePath" not in f:
                continue
            out.append(
                Recording(
                    channel=int(f.get("Channel", 0)),
                    filepath=f["FilePath"],
                    start_time=f.get("StartTime", ""),
                    end_time=f.get("EndTime", ""),
                    length=int(f.get("Length", 0)),
                    cut_length=int(f["CutLength"]) if "CutLength" in f else None,
                )
            )
        dbg(f"RPC files: {len(out)}")
        return out

    def find_recordings(self, channel: int, start: str, end: str) -> list[Recording]:
        api_ch = self.api_channel(channel)

        def time_opts() -> list[tuple[str, str, str]]:
            def p(v: str) -> tuple[int, int, int, str]:
                d, t = v.strip().split(" ", 1)
                y, m, day = (int(x) for x in d.split("-"))
                return y, m, day, t

            sy, sm, sd, st = p(start)
            ey, em, ed, et = p(end)
            return [
                ("pedido", start.strip(), end.strip()),
                ("wide", f"{sy}-{sm}-{sd} 14:00:00", f"{ey}-{em}-{ed} 15:00:00"),
                ("padded", f"{sy}-{sm:02d}-{sd:02d} {st}", f"{ey}-{em:02d}-{ed:02d} {et}"),
            ]

        for label, st, en in time_opts():
            print(f"busca CGI: canal {channel} ({label}) {st} → {en}")
            recs = self.cgi_find(api_ch, st, en)
            if recs:
                matched = self.filter_channel(recs, channel)
                if matched:
                    print(f"  → {len(matched)} arquivo(s) em /{channel}/dav/")
                    return matched
                dbg(f"API ch={api_ch} retornou outro path: {[r.filepath for r in recs]}")
            else:
                print("  → vazio")

            if self.rpc_logged_in:
                print(f"busca RPC2: canal {channel} ({label}) {st} → {en}")
                try:
                    recs = self.rpc_find(api_ch, st, en)
                except RuntimeError as exc:
                    print(f"  → {exc}")
                    recs = []
                if recs:
                    matched = self.filter_channel(recs, channel)
                    if matched:
                        print(f"  → {len(matched)} arquivo(s) em /{channel}/dav/")
                        return matched
                else:
                    print("  → vazio")

        raise RuntimeError(f"Nenhuma gravação: canal {channel}, {start} → {end}")

    @staticmethod
    def _path_channel(filepath: str) -> int | None:
        m = re.search(r"/mnt/dvr/\d{4}-\d{2}-\d{2}/(\d+)/dav/", filepath)
        return int(m.group(1)) if m else None

    @staticmethod
    def _matches_channel(rec: Recording, channel: int) -> bool:
        # Path /N/dav/ é o número da câmera no painel (mais confiável que rec.channel).
        path_ch = NVRClient._path_channel(rec.filepath)
        if path_ch is not None:
            return path_ch == channel
        return rec.channel == channel

    def filter_channel(self, recs: list[Recording], channel: int) -> list[Recording]:
        return [r for r in recs if self._matches_channel(r, channel)]

    def pick_recording(self, recs: list[Recording], channel: int) -> Recording:
        matched = self.filter_channel(recs, channel)
        if matched:
            return matched[0]
        paths = ", ".join(
            f"câmera {self._path_channel(r.filepath) or r.channel}" for r in recs
        )
        raise RuntimeError(
            f"Gravação encontrada, mas não no canal {channel} pedido.\n"
            f"  Disponível em: {paths}\n"
            f"  Ajuste CHANNEL no script (ex.: CHANNEL = 1) ou confira START/END."
        )

    def overlapping_segments(
        self,
        recs: list[Recording],
        channel: int,
        start: str,
        end: str,
    ) -> list[tuple[Recording, str, str]]:
        matched = self.filter_channel(recs, channel)
        window_start = parse_dt(start)
        window_end = parse_dt(end)
        out: list[tuple[Recording, str, str]] = []
        for rec in matched:
            rec_start = parse_dt(rec.start_time)
            rec_end = parse_dt(rec.end_time)
            if rec_end <= window_start or rec_start >= window_end:
                continue
            seg_start = format_nvr_time(max(rec_start, window_start))
            seg_end = format_nvr_time(min(rec_end, window_end))
            out.append((rec, seg_start, seg_end))
        return out

    def _minimal_loadfile_attempts(
        self,
        channel: int,
        start: str,
        end: str,
    ) -> list[tuple[int, str, str, str, bool, str]]:
        """Uma tentativa rápida (url + unpadded no canal derivado de CHANNEL)."""
        ch = self.api_channel(channel)

        def p(v: str) -> tuple[int, int, int, str]:
            d, t = v.strip().split(" ", 1)
            y, m, day = (int(x) for x in d.split("-"))
            return y, m, day, t

        sy, sm, sd, st = p(start)
        ey, em, ed, et = p(end)
        st_un = f"{sy}-{sm}-{sd} {st}"
        en_un = f"{ey}-{em}-{ed} {et}"
        return [(ch, "unpadded", st_un, en_un, False, "url")]

    def _loadfile_attempts(
        self,
        channel: int,
        start: str,
        end: str,
    ) -> list[tuple[int, str, str, str, bool, str]]:
        def p(v: str) -> tuple[int, int, int, str]:
            d, t = v.strip().split(" ", 1)
            y, m, day = (int(x) for x in d.split("-"))
            return y, m, day, t

        sy, sm, sd, st = p(start)
        ey, em, ed, et = p(end)
        times = [
            ("raw", start.strip(), end.strip()),
            ("padded", f"{sy}-{sm:02d}-{sd:02d} {st}", f"{ey}-{em:02d}-{ed:02d} {et}"),
            ("unpadded", f"{sy}-{sm}-{sd} {st}", f"{ey}-{em}-{ed} {et}"),
            ("trail", start.strip(), end.strip()),
        ]
        if self._loadfile_prefs:
            ch, label, use_subtype, mode = self._loadfile_prefs
            for lbl, s, e in times:
                if lbl == label:
                    return [(ch, lbl, s, e, use_subtype, mode)]

        # MHDX: só unpadded + url funciona de forma confiável (params → HTTP 400).
        return self._minimal_loadfile_attempts(channel, start, end)

    def _loadfile_url(self, ch: int, st: str, en: str, *, label: str, use_subtype: bool) -> str:
        if label == "trail":
            start_enc = self.encode_start(st)
            end_enc = self.encode_end(en)
        else:
            start_enc = st.replace(" ", "%20")
            end_enc = en.replace(" ", "%20")
        return (
            f"{self.base}/cgi-bin/loadfile.cgi?"
            f"action=startLoad&channel={ch}"
            f"&startTime={start_enc}"
            f"&endTime={end_enc}"
            + ("&subtype=0" if use_subtype else "")
        )

    def _run_loadfile(
        self,
        ch: int,
        st: str,
        en: str,
        *,
        label: str,
        use_subtype: bool,
        mode: str,
        dest: Path,
        timeout: int,
    ) -> int | None:
        self.loadfile_stop()
        spec: str | dict
        if mode == "params":
            spec = {
                "action": "startLoad",
                "channel": ch,
                "startTime": st,
                "endTime": en,
                **({"subtype": 0} if use_subtype else {}),
            }
        else:
            spec = self._loadfile_url(ch, st, en, label=label, use_subtype=use_subtype)

        r: requests.Response | None = None
        try:
            if mode == "params":
                r = self.session.get(
                    f"{self.base}/cgi-bin/loadfile.cgi",
                    params=spec,
                    stream=True,
                    timeout=timeout,
                )
            else:
                dbg(f"loadfile GET {spec}")
                r = self.session.get(spec, stream=True, timeout=timeout)
            if r.status_code != 200:
                body = r.content[:300].decode("utf-8", errors="replace").strip()
                dbg(
                    f"loadfile HTTP {r.status_code} ({mode}) ch={ch} "
                    f"{label}: {body or '(vazio)'}"
                )
                return None
            ctype = (r.headers.get("Content-Type") or "").lower()
            if "text" in ctype or "html" in ctype or "json" in ctype:
                dbg(f"loadfile resposta não-vídeo: {ctype}")
                return None
            size = self._write_stream(r, dest, expected=None)
            if size > MIN_DAV_BYTES:
                return size
            if size > 0:
                dest.unlink(missing_ok=True)
            return None
        except requests.RequestException as exc:
            dbg(f"loadfile erro rede ({mode}): {exc}")
            return None
        finally:
            if r is not None:
                r.close()
            self.loadfile_stop()

    def download_clip(
        self,
        channel: int,
        start: str,
        end: str,
        dest: Path,
        *,
        timeout: int | None = None,
        quiet: bool = False,
    ) -> int | None:
        """Recorte por tempo via loadfile.cgi (uma requisição unpadded+url)."""
        clip_secs = expected_interval_seconds(start, end)
        if clip_secs < MIN_CLIP_SECONDS:
            dbg(f"janela {clip_secs:.0f}s < {MIN_CLIP_SECONDS}s — ignorada")
            return None

        dest.parent.mkdir(parents=True, exist_ok=True)
        if timeout is None:
            timeout = clip_timeout(start, end)

        if dest.exists() and dest.stat().st_size == 0:
            dest.unlink()

        self._pause_before_download()
        self.loadfile_stop()
        if self._loadfile_prefs is None:
            try:
                self.prime_window(channel, start, end)
            except Exception as exc:
                dbg(f"prime_window: {exc}")

        attempts = self._loadfile_attempts(channel, start, end)
        for ch, label, st, en, use_subtype, mode in attempts:
            dbg(f"loadfile {label} ch={ch} {st} → {en}")
            size = self._run_loadfile(
                ch, st, en,
                label=label,
                use_subtype=use_subtype,
                mode=mode,
                dest=dest,
                timeout=timeout,
            )
            if size and size > MIN_DAV_BYTES:
                self._loadfile_prefs = (ch, label, use_subtype, mode)
                self._pause_after_download(size)
                if not quiet:
                    print(f"    OK ({size:,} bytes)")
                return size

        if not quiet:
            dbg(f"loadfile falhou: canal {channel}, {start} → {end}")
        return None

    def download_clip_resilient(
        self,
        channel: int,
        start: str,
        end: str,
        dest: Path,
        *,
        quiet: bool = False,
    ) -> int | None:
        if cached_chunk_ok(dest, start, end):
            if not quiet:
                print(f"    já existe ({dest.stat().st_size:,} bytes), pulando")
            return dest.stat().st_size
        if dest.exists():
            if not quiet:
                print("    arquivo em cache curto/corrompido — baixando de novo...")
            dest.unlink(missing_ok=True)
            chunk_meta_path(dest).unlink(missing_ok=True)

        for attempt in range(1, CHUNK_RETRIES + 1):
            if attempt > 1:
                wait = WAIT_ON_RETRY_SEC * attempt
                print(f"    tentativa {attempt}/{CHUNK_RETRIES} (pausa {wait}s)...")
                time.sleep(wait)
                self.loadfile_stop()

            size = self.download_clip(
                channel,
                start,
                end,
                dest,
                quiet=True,
            )
            if size and size > MIN_DAV_BYTES:
                write_chunk_meta(dest, start, end)
                if not quiet:
                    print(f"    OK ({size:,} bytes)")
                return size
            if dest.exists():
                dest.unlink(missing_ok=True)
                chunk_meta_path(dest).unlink(missing_ok=True)

        return None

    @staticmethod
    def _encode_path_variants(remote_path: str) -> list[str]:
        return [
            quote(remote_path, safe="/"),
            quote(remote_path, safe=""),
            remote_path.replace("[", "%5B").replace("]", "%5D").replace("@", "%40"),
        ]

    def _write_stream(
        self,
        r: requests.Response,
        dest: Path,
        *,
        expected: int | None,
        append: bool = False,
    ) -> int:
        mode = "ab" if append else "wb"
        with dest.open(mode) as f:
            try:
                for chunk in r.iter_content(256 * 1024):
                    if chunk:
                        f.write(chunk)
            except (requests.exceptions.ChunkedEncodingError, Urllib3IncompleteRead):
                # mantém bytes já gravados para retomar
                pass
        return dest.stat().st_size if dest.exists() else 0

    def download_rpc(
        self,
        remote_path: str,
        dest: Path,
        *,
        expected: int | None = None,
    ) -> int:
        dest.parent.mkdir(parents=True, exist_ok=True)

        for enc in self._encode_path_variants(remote_path):
            url = f"{self.base}/cgi-bin/RPC_Loadfile{enc}"
            dbg(f"RPC_Loadfile {url}")

            for attempt in range(1, 6):
                offset = dest.stat().st_size if dest.exists() else 0
                headers = {"Connection": "close"}
                if offset > 0:
                    headers["Range"] = f"bytes={offset}-"
                    print(f"  retomando em {offset:,} bytes (tentativa {attempt})...")
                else:
                    print(f"\nbaixando bloco inteiro (tentativa {attempt})...")

                try:
                    r = self.session.get(
                        url,
                        headers=headers,
                        stream=True,
                        timeout=(30, 3600),
                    )
                    if r.status_code not in (200, 206):
                        dbg(f"HTTP {r.status_code}")
                        break

                    size = self._write_stream(r, dest, expected=expected, append=offset > 0)
                    if expected and size >= expected * 0.99:
                        return size
                    if size > 1_000_000 and not expected:
                        return size
                    if size > 50_000 and expected and size >= (expected // 2):
                        # pode ser recorte parcial aceitável
                        return size
                except Exception as exc:
                    dbg(f"RPC erro: {exc}")

                time.sleep(2 * attempt)

        if shutil.which("curl"):
            curl_size = self._download_curl(remote_path, dest, expected=expected)
            if curl_size >= MIN_DAV_BYTES:
                return curl_size

        size = dest.stat().st_size if dest.exists() else 0
        raise RuntimeError(
            f"download RPC falhou (gravado: {size:,} bytes). "
            "Tente novamente — o script retoma de onde parou."
        )

    def _download_curl(
        self,
        remote_path: str,
        dest: Path,
        *,
        expected: int | None = None,
    ) -> int:
        encoded = quote(remote_path, safe="/")
        url = f"{self.base}/cgi-bin/RPC_Loadfile{encoded}"
        print("\nfallback curl --digest (com retomada)...")
        dest.parent.mkdir(parents=True, exist_ok=True)

        for attempt in range(1, 6):
            offset = dest.stat().st_size if dest.exists() else 0
            if offset > 0:
                print(f"  curl retomando em {offset:,} bytes (tentativa {attempt})...")
            cmd = [
                "curl",
                "-sS",
                "--digest",
                "-u",
                f"{self.user}:{self.password}",
                "-C",
                "-",
                "--retry",
                "3",
                "--retry-delay",
                "5",
                "-o",
                str(dest),
                url,
            ]
            dbg(" ".join(cmd[:7]) + " ...")
            try:
                result = subprocess.run(
                    cmd,
                    check=False,
                    timeout=7200,
                    capture_output=not DEBUG,
                )
            except (subprocess.SubprocessError, OSError) as exc:
                dbg(f"curl erro: {exc}")
                time.sleep(5 * attempt)
                continue

            size = dest.stat().st_size if dest.exists() else 0
            if result.returncode == 0 and size >= MIN_DAV_BYTES:
                return size
            if size >= MIN_DAV_BYTES:
                dbg(f"curl exit {result.returncode}, parcial {size:,} bytes")
                if expected and size >= expected * 0.99:
                    return size
            time.sleep(5 * attempt)

        return dest.stat().st_size if dest.exists() else 0

    def download(
        self,
        rec: Recording,
        dest: Path,
        *,
        channel: int,
        start: str,
        end: str,
    ) -> tuple[int, bool]:
        """Retorna (tamanho_bytes, já_é_recorte_por_tempo)."""
        print("tentando recorte por tempo (loadfile.cgi)...")
        clip_size = self.download_clip(channel, start, end, dest)
        if clip_size:
            return clip_size, True

        duration_h = (parse_dt(end) - parse_dt(start)).total_seconds() / 3600
        if duration_h > 1 or rec.length > 200_000_000:
            raise RuntimeError(
                "loadfile falhou para o intervalo pedido. "
                "Intervalos longos são baixados em partes — use o fluxo automático "
                "(não force RPC no bloco .dav inteiro)."
            )

        print("loadfile indisponível — baixando bloco .dav inteiro (pode demorar)...")
        return self.download_rpc(rec.filepath, dest, expected=rec.length), False

    def _try_loadfile_window(
        self,
        channel: int,
        rec: Recording,
        seg_start: str,
        seg_end: str,
        dest: Path,
    ) -> DavSegment | None:
        if dest.exists() and dest.stat().st_size == 0:
            dest.unlink(missing_ok=True)
            chunk_meta_path(dest).unlink(missing_ok=True)

        size = self.download_clip_resilient(channel, seg_start, seg_end, dest)
        if size and loadfile_result_ok(dest, seg_start, seg_end):
            write_chunk_meta(dest, seg_start, seg_end, method="loadfile")
            return DavSegment(dest, rec, seg_start, seg_end, already_clipped=True)

        if dest.exists():
            dest.unlink(missing_ok=True)
            chunk_meta_path(dest).unlink(missing_ok=True)
        return None

    def _download_loadfile_subchunks(
        self,
        channel: int,
        rec: Recording,
        seg_start: str,
        seg_end: str,
        dest: Path,
    ) -> list[DavSegment]:
        windows = list(iter_time_chunks_minutes(seg_start, seg_end, LOADFILE_SUB_MINUTES))
        if len(windows) <= 1:
            return []

        print(f"    loadfile em {len(windows)} parte(s) de {LOADFILE_SUB_MINUTES} min...")
        parts: list[DavSegment] = []
        for sub_idx, (sub_start, sub_end) in enumerate(windows):
            sub_dest = dest.parent / f"{dest.stem}_{sub_idx:02d}.dav"
            print(f"      [{sub_idx + 1}/{len(windows)}] {sub_start} → {sub_end}")
            segment = self._try_loadfile_window(channel, rec, sub_start, sub_end, sub_dest)
            if segment:
                parts.append(segment)
            else:
                print("        falhou")
        return parts

    def _download_one_nvr_file(
        self,
        channel: int,
        rec: Recording,
        seg_start: str,
        seg_end: str,
        dest: Path,
    ) -> list[DavSegment]:
        """loadfile no horário do arquivo NVR; fallback 10 min; RPC só arquivos pequenos."""
        segment = self._try_loadfile_window(channel, rec, seg_start, seg_end, dest)
        if segment:
            return [segment]

        parts = self._download_loadfile_subchunks(channel, rec, seg_start, seg_end, dest)
        if parts:
            return parts

        if rec.length > RPC_MAX_BYTES:
            dbg(
                f"RPC ignorado ({rec.length / 1_048_576:.0f} MiB) "
                f"para {seg_start} → {seg_end}"
            )
            return []

        print("    loadfile falhou — tentando arquivo original (RPC)...")
        try:
            rpc_size = self.download_rpc(rec.filepath, dest, expected=rec.length)
        except RuntimeError as exc:
            print(f"    RPC falhou: {exc}")
            return []
        if rpc_size < MIN_DAV_BYTES:
            return []

        write_chunk_meta(dest, seg_start, seg_end, rec=rec, method="rpc")
        return [DavSegment(dest, rec, seg_start, seg_end, already_clipped=False)]

    def _download_nvr_files(
        self,
        channel: int,
        blocks: list[tuple[Recording, str, str]],
        out_dir: Path,
    ) -> list[DavSegment]:
        for stale in (out_dir / "recorte.dav", out_dir / "recorte.mp4"):
            if stale.exists():
                stale.unlink(missing_ok=True)

        segments_dir = out_dir / "segments"
        segments_dir.mkdir(exist_ok=True)

        blocks_sorted = sorted(blocks, key=lambda b: parse_dt(b[1]))
        eligible: list[tuple[Recording, str, str]] = []
        for rec, seg_start, seg_end in blocks_sorted:
            if expected_interval_seconds(seg_start, seg_end) < MIN_CLIP_SECONDS:
                print(f"  pulando {seg_start} → {seg_end} (< {MIN_CLIP_SECONDS}s)")
                continue
            eligible.append((rec, seg_start, seg_end))

        total = len(eligible)
        skipped = len(blocks_sorted) - total
        print(
            f"download por arquivo NVR: {total} trecho(s)"
            + (f" ({skipped} muito curto(s) ignorado(s))" if skipped else "")
        )

        segments: list[DavSegment] = []
        for i, (rec, seg_start, seg_end) in enumerate(eligible):
            part = segments_dir / f"nvr_{i:04d}.dav"
            print(f"  [{i + 1}/{total}] {seg_start} → {seg_end}")
            dbg(f"    {rec.filepath}")
            file_segments = self._download_one_nvr_file(
                channel, rec, seg_start, seg_end, part
            )
            if file_segments:
                segments.extend(file_segments)
                for seg in file_segments:
                    if seg.already_clipped:
                        warn_if_short_media(
                            seg.path,
                            seg.seg_start,
                            seg.seg_end,
                            label=seg.path.name,
                        )
            else:
                print("    falhou")

        segments.sort(key=lambda s: s.path.name)
        return segments

    def download_interval(
        self,
        channel: int,
        start: str,
        end: str,
        recs: list[Recording],
        out_dir: Path,
    ) -> list[DavSegment]:
        """Baixa cada gravação listada pelo NVR em START→END (um loadfile por .dav)."""
        out_dir.mkdir(parents=True, exist_ok=True)

        blocks = self.overlapping_segments(recs, channel, start, end)
        if not blocks:
            raise RuntimeError(f"Nenhum bloco NVR no intervalo {start} → {end}")

        eligible = sum(
            1
            for _, s, e in blocks
            if expected_interval_seconds(s, e) >= MIN_CLIP_SECONDS
        )
        segments = self._download_nvr_files(channel, blocks, out_dir)
        if not segments:
            raise RuntimeError(
                "Nenhum trecho baixado. Rode de novo — arquivos em segments/ "
                "são reaproveitados."
            )
        if len(segments) < eligible:
            print(
                f"\nAVISO: {len(segments)}/{eligible} trecho(s) baixado(s). "
                "Rode o script de novo para retomar os faltantes."
            )
        return segments


def convert_to_mp4(
    dest: Path,
    rec: Recording,
    *,
    already_clipped: bool,
    start: str,
    end: str,
) -> Path | None:
    if not shutil.which("ffmpeg"):
        print("\nffmpeg não encontrado. Para gerar MP4: sudo apt install ffmpeg")
        return None

    mp4 = dest.with_suffix(".mp4")
    expected_secs = expected_interval_seconds(start, end)
    if mp4.exists() and mp4.stat().st_size > 100_000:
        dur = probe_media_duration(mp4)
        if dur is None or dur >= expected_secs - 90:
            dur_txt = f", ~{format_duration(dur)}" if dur else ""
            print(f"MP4 já existe: {mp4} ({mp4.stat().st_size:,} bytes{dur_txt})")
            return mp4
        print(
            f"MP4 existente curto (~{format_duration(dur or 0)} "
            f"vs ~{format_duration(expected_secs)}) — reconvertendo..."
        )
        mp4.unlink(missing_ok=True)
    elif mp4.exists() and mp4.stat().st_size < 10_000:
        mp4.unlink()

    # .dav Intelbras = HEVC cru; blocos concatenados pelo NVR quebram após ~30 min.
    input_flags = [
        "-fflags", "+genpts+discardcorrupt+igndts",
        "-err_detect", "ignore_err",
        "-probesize", "50M",
        "-analyzeduration", "50M",
    ]
    output_flags = ["-movflags", "+faststart", "-an"]

    def build_cmds() -> list[tuple[str, list[str]]]:
        base = ["ffmpeg", "-y", *input_flags, "-i", str(dest)]
        if already_clipped:
            return [
                ("re-encode H.264", [
                    *base,
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                    *output_flags, str(mp4),
                ]),
                ("copy HEVC", [
                    *base, "-c:v", "copy", *output_flags, str(mp4),
                ]),
            ]
        try:
            clip = datetime.strptime(start.strip(), "%Y-%m-%d %H:%M:%S")
            rec_start = datetime.strptime(rec.start_time, "%Y-%m-%d %H:%M:%S")
            offset = max(0, int((clip - rec_start).total_seconds()))
            duration = int(
                (datetime.strptime(end.strip(), "%Y-%m-%d %H:%M:%S") - clip).total_seconds()
            )
        except ValueError:
            return [
                ("re-encode H.264", [
                    *base,
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                    *output_flags, str(mp4),
                ]),
            ]
        h, rem = divmod(offset, 3600)
        m, sec = divmod(rem, 60)
        dh, rem = divmod(duration, 3600)
        dm, ds = divmod(rem, 60)
        ss = f"{h:02d}:{m:02d}:{sec:02d}"
        tt = f"{dh:02d}:{dm:02d}:{ds:02d}"
        trim_base = [
            "ffmpeg", "-y",
            "-ss", ss, *input_flags, "-i", str(dest), "-t", tt,
        ]
        return [
            ("recorte + re-encode H.264", [
                *trim_base,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                *output_flags, str(mp4),
            ]),
            ("recorte + copy HEVC", [
                *trim_base, "-c:v", "copy", *output_flags, str(mp4),
            ]),
        ]

    for label, cmd in build_cmds():
        print(f"\nconvertendo ({label}) → {mp4}")
        dbg(" ".join(cmd))
        subprocess.run(cmd, check=False)
        if mp4.exists() and mp4.stat().st_size > 100_000:
            dur = probe_media_duration(mp4)
            if dur and dur < expected_secs - 90:
                print(
                    f"  MP4 curto (~{format_duration(dur)} vs "
                    f"~{format_duration(expected_secs)}) — próxima tentativa..."
                )
                mp4.unlink(missing_ok=True)
                continue
            dur_txt = f", ~{format_duration(dur)}" if dur else ""
            print(f"MP4 OK: {mp4} ({mp4.stat().st_size:,} bytes{dur_txt})")
            return mp4
        if mp4.exists():
            mp4.unlink(missing_ok=True)
        print(f"  → falhou ou arquivo vazio, próxima tentativa...")

    print("\nconversão MP4 falhou. O .dav está OK — tente manualmente:")
    print(f"  ffmpeg -y -i {dest} -c:v libx264 -preset fast -crf 23 {mp4}")
    return None


def concat_mp4s(parts: list[Path], dest: Path) -> Path | None:
    if not shutil.which("ffmpeg"):
        return None
    if len(parts) == 1:
        return parts[0]
    dest.parent.mkdir(parents=True, exist_ok=True)
    list_file = dest.with_suffix(".concat.txt")
    lines = []
    for part in parts:
        path = str(part.resolve()).replace("'", "'\\''")
        lines.append(f"file '{path}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    print(f"\nunindo {len(parts)} MP4 → {dest}")
    dbg(" ".join(cmd))
    subprocess.run(cmd, check=False)
    if dest.exists() and dest.stat().st_size > 100_000:
        dur = probe_media_duration(dest)
        dur_txt = f", ~{format_duration(dur)}" if dur else ""
        print(f"MP4 final OK: {dest} ({dest.stat().st_size:,} bytes{dur_txt})")
        list_file.unlink(missing_ok=True)
        return dest
    if dest.exists():
        dest.unlink(missing_ok=True)

    print("  concat copy falhou — tentando re-encode...")
    cmd_reencode = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-movflags",
        "+faststart",
        "-an",
        str(dest),
    ]
    subprocess.run(cmd_reencode, check=False)
    list_file.unlink(missing_ok=True)
    if dest.exists() and dest.stat().st_size > 100_000:
        dur = probe_media_duration(dest)
        dur_txt = f", ~{format_duration(dur)}" if dur else ""
        print(f"MP4 final OK (re-encode): {dest} ({dest.stat().st_size:,} bytes{dur_txt})")
        return dest
    if dest.exists():
        dest.unlink(missing_ok=True)
    return None


def output_dir_for_interval(start: str, end: str) -> Path:
    safe = lambda s: re.sub(r"[^0-9A-Za-z]+", "-", s.strip()).strip("-")
    return OUT_DIR / f"{safe(start)}_to_{safe(end)}"


def write_manifest(
    work_dir: Path,
    segments: list[DavSegment],
    *,
    channel: int,
    start: str,
    end: str,
) -> Path:
    manifest = work_dir / "manifest.json"
    payload = {
        "channel": channel,
        "interval_start": start.strip(),
        "interval_end": end.strip(),
        "segments": [
            {
                "file": str(seg.path.relative_to(work_dir)).replace("\\", "/"),
                "remote_path": seg.rec.filepath,
                "t_start": seg.seg_start,
                "t_end": seg.seg_end,
                "method": "loadfile" if seg.already_clipped else "rpc",
            }
            for seg in segments
        ],
    }
    manifest.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def format_bytes(n: int) -> str:
    if n >= 1_073_741_824:
        return f"{n / 1_073_741_824:.2f} GiB"
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f} MiB"
    if n >= 1024:
        return f"{n / 1024:.1f} KiB"
    return f"{n} B"


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Intelbras MHDX")
    parser.add_argument("--list", action="store_true", help="Só listar")
    parser.add_argument(
        "--no-mp4",
        action="store_true",
        help="Não converter para MP4 (equivalente a CONVERT_MP4 = False)",
    )
    args = parser.parse_args()
    convert_mp4 = CONVERT_MP4 and not args.no_mp4

    try:
        client = NVRClient(NVR_IP, USER, PASS)
        client.login()  # opcional; CGI funciona só com Digest

        print(f"\nNVR {NVR_IP} | canal {CHANNEL} | {START} → {END}\n")
        recs = client.find_recordings(CHANNEL, START, END)

        for i, rec in enumerate(recs):
            print(f"[{i}] {rec.start_time} → {rec.end_time}  ({rec.length / 1024 / 1024:.0f} MB)")
            print(f"    {rec.filepath}")

        if args.list:
            return 0

        client.pick_recording(recs, CHANNEL)  # valida canal antes de baixar

        work_dir = output_dir_for_interval(START, END)
        segments = client.download_interval(CHANNEL, START, END, recs, work_dir)
        total_bytes = sum(s.path.stat().st_size for s in segments)
        work_dir_abs = work_dir.resolve()
        print(
            f"\n{len(segments)} arquivo(s) .dav ({total_bytes:,} bytes / "
            f"{format_bytes(total_bytes)})"
        )
        print(f"Pasta: {work_dir_abs}")
        for seg in segments:
            dur = probe_media_duration(seg.path)
            dur_txt = f", decodifica ~{format_duration(dur)}" if dur else ""
            src = "loadfile" if seg.already_clipped else "RPC+recorte"
            print(
                f"  {seg.path.name}: {seg.seg_start} → {seg.seg_end} "
                f"({format_bytes(seg.path.stat().st_size)}, {src}{dur_txt})"
            )

        manifest = write_manifest(
            work_dir, segments, channel=CHANNEL, start=START, end=END
        )
        print(f"\nmanifest: {manifest.resolve()}")

        if not convert_mp4:
            print("\nConversão MP4 desligada — arquivos .dav:")
            for seg in segments:
                print(f"  {seg.path.resolve()}  ({format_bytes(seg.path.stat().st_size)})")
            if len(segments) > 1:
                print(
                    "\nDica: vários blocos → use CONVERT_MP4 = True para unir em recorte.mp4."
                )
            print(f"\nConfira: ls -lh {work_dir_abs}")
            return 0

        mp4_parts: list[Path] = []
        for i, seg in enumerate(segments):
            print(
                f"\n--- segmento {i + 1}/{len(segments)}: {seg.path.name} "
                f"({seg.seg_start} → {seg.seg_end}, "
                f"{'loadfile' if seg.already_clipped else 'RPC'}) ---"
            )
            mp4 = convert_to_mp4(
                seg.path,
                seg.rec,
                already_clipped=seg.already_clipped,
                start=seg.seg_start,
                end=seg.seg_end,
            )
            if mp4:
                mp4_parts.append(mp4)

        blocks = client.overlapping_segments(recs, CHANNEL, START, END)
        clipped = clip_window_to_recordings(blocks, START, END)
        expected_total = sum(
            expected_interval_seconds(s.seg_start, s.seg_end) for s in segments
        )
        if len(mp4_parts) > 1:
            final = concat_mp4s(mp4_parts, work_dir / "recorte.mp4")
        elif len(mp4_parts) == 1:
            final = work_dir / "recorte.mp4"
            if mp4_parts[0] != final:
                if final.exists():
                    final.unlink(missing_ok=True)
                shutil.copy2(mp4_parts[0], final)
            print(f"\nMP4: {final}")
        else:
            final = None

        if final and final.exists():
            dur = probe_media_duration(final)
            if dur:
                pedido = expected_interval_seconds(START, END)
                gravacao = (
                    expected_interval_seconds(clipped[0], clipped[1])
                    if clipped
                    else pedido
                )
                print(
                    f"\nDuração final do MP4: ~{format_duration(dur)} "
                    f"(baixado ~{format_duration(expected_total)}, "
                    f"gravação no intervalo ~{format_duration(gravacao)}, "
                    f"pedido ~{format_duration(pedido)})"
                )
                if dur < expected_total - 120:
                    print(
                        "AVISO: MP4 final ainda curto. Apague a pasta e rode de novo — "
                        "confira se todos os nvr_*.dav em segments/ foram baixados."
                    )
        return 0
    except KeyboardInterrupt:
        print("\ninterrompido", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
