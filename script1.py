#!/usr/bin/env python3
"""
Download Intelbras MHDX 1404.

  python3 script.py          # baixa
  python3 script.py --list   # só lista
  NVR_DEBUG=1 python3 script.py

Fluxo: login RPC2 (sessão do browser) → busca → RPC_Loadfile.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests
from requests.auth import HTTPDigestAuth
from urllib3.exceptions import IncompleteRead as Urllib3IncompleteRead

# ============ CONFIGURE AQUI ============
NVR_IP = os.environ.get("NVR_IP", "192.168.0.108")
USER = os.environ.get("NVR_USER", "admin")
PASS = os.environ.get("NVR_PASS", "V03admin%")

# Câmera no painel do NVR (1–4). O path do arquivo usa /1/dav/, /2/dav/, etc.
# A API de busca usa outro índice (câmera 1 costuma ser API channel 2 neste MHDX).
CHANNEL = 1

START = "2026-6-10 14:10:00"
END = "2026-6-10 14:10:00"

OUT_DIR = Path(__file__).parent / "nvr_videos"
DEBUG = os.environ.get("NVR_DEBUG", "").lower() in ("1", "true", "yes")
# ========================================


@dataclass
class Recording:
    channel: int
    filepath: str
    start_time: str
    end_time: str
    length: int
    cut_length: int | None = None


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

    @staticmethod
    def _is_login_challenge(data: dict) -> bool:
        err = data.get("error") or {}
        if err.get("code") == 268632079:
            return True
        msg = str(err.get("message", "")).lower()
        return "login challenge" in msg

    def login(self) -> bool:
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
                print("login RPC2: OK")
                return True

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

                r = self.session.get(
                    f"{self.base}/cgi-bin/mediaFileFind.cgi",
                    params={"action": "findNextFile", "object": obj, "count": 50},
                    timeout=30,
                )
                recs = self._parse_cgi_items(r.text)
                if recs:
                    dbg(f"CGI ok via {mode}")
                    return recs
            finally:
                self.cgi_destroy(obj)
        return []

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

                data = self.rpc("mediaFileFind.findNextFile", {"object": obj, "count": 50})
                recs = self._parse_rpc_files(data)
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

    @staticmethod
    def api_search_channels(camera: int) -> list[int]:
        """Índices API a tentar (MHDX: câmera 1 → path /1/dav/, busca API channel 2)."""
        candidates = [camera + 1, camera, camera - 1, camera + 2, 0]
        return [c for c in dict.fromkeys(candidates) if c >= 0]

    def find_recordings(self, channel: int, start: str, end: str) -> list[Recording]:
        channels = self.api_search_channels(channel)

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
            for ch in channels:
                print(f"busca CGI: API ch={ch} câmera {channel} ({label}) {st} → {en}")
                recs = self.cgi_find(ch, st, en)
                if recs:
                    matched = self.filter_channel(recs, channel)
                    if matched:
                        print(f"  → {len(matched)} arquivo(s) em /{channel}/dav/")
                        return matched
                    dbg(f"API ch={ch} retornou outro path: {[r.filepath for r in recs]}")
                print("  → vazio")

            if self.rpc_logged_in:
                for ch in channels:
                    print(f"busca RPC2: API ch={ch} câmera {channel} ({label}) {st} → {en}")
                    try:
                        recs = self.rpc_find(ch, st, en)
                    except RuntimeError as exc:
                        print(f"  → {exc}")
                        continue
                    if recs:
                        matched = self.filter_channel(recs, channel)
                        if matched:
                            print(f"  → {len(matched)} arquivo(s) em /{channel}/dav/")
                            return matched
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

    def download_clip(
        self,
        channel: int,
        start: str,
        end: str,
        dest: Path,
    ) -> int | None:
        """Recorte por tempo (~2 min) — bem menor que o bloco inteiro."""
        dest.parent.mkdir(parents=True, exist_ok=True)

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
        ]

        if dest.exists() and dest.stat().st_size == 0:
            dest.unlink()

        api_channels = self.api_search_channels(channel)
        for label, st, en in times:
            for ch in api_channels:
                for use_subtype in (False, True):
                    dbg(f"loadfile {label} ch={ch} subtype={use_subtype} {st} → {en}")

                    # tentativa 1: params (requests codifica)
                    attempts: list[tuple[str, str | dict]] = [
                        ("params", {
                            "action": "startLoad",
                            "channel": ch,
                            "startTime": st,
                            "endTime": en,
                            **({"subtype": 0} if use_subtype else {}),
                        }),
                        # tentativa 2: URL manual (':' literal, como findFile)
                        ("url", (
                            f"{self.base}/cgi-bin/loadfile.cgi?"
                            f"action=startLoad&channel={ch}"
                            f"&startTime={st.replace(' ', '%20')}"
                            f"&endTime={en.replace(' ', '%20')}"
                            + ("&subtype=0" if use_subtype else "")
                        )),
                    ]

                    for mode, spec in attempts:
                        try:
                            if mode == "params":
                                r = self.session.get(
                                    f"{self.base}/cgi-bin/loadfile.cgi",
                                    params=spec,
                                    stream=True,
                                    timeout=600,
                                )
                            else:
                                r = self.session.get(spec, stream=True, timeout=600)
                        except requests.RequestException as exc:
                            dbg(f"loadfile erro rede ({mode}): {exc}")
                            continue
                        if r.status_code != 200:
                            dbg(f"loadfile HTTP {r.status_code} ({mode})")
                            continue
                        size = self._write_stream(r, dest, expected=None)
                        if size > 50_000:
                            print(f"recorte loadfile OK (canal {ch}, {label}, {size:,} bytes)")
                            return size
                        if size > 0 and size < 50_000:
                            dest.unlink(missing_ok=True)
                        dbg(f"loadfile arquivo pequeno ({mode}): {size} bytes")
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
            return self._download_curl(remote_path, dest)

        size = dest.stat().st_size if dest.exists() else 0
        raise RuntimeError(
            f"download RPC falhou (gravado: {size:,} bytes). "
            "Tente novamente — o script retoma de onde parou."
        )

    def _download_curl(self, remote_path: str, dest: Path) -> int:
        encoded = quote(remote_path, safe="/")
        url = f"{self.base}/cgi-bin/RPC_Loadfile{encoded}"
        print("\nfallback curl --digest (com retomada)...")
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "curl",
            "--digest",
            "-u",
            f"{self.user}:{self.password}",
            "-C",
            "-",
            "--retry",
            "5",
            "--retry-delay",
            "3",
            "-o",
            str(dest),
            url,
        ]
        dbg(" ".join(cmd[:6]) + " ...")
        subprocess.run(cmd, check=True, timeout=7200)
        return dest.stat().st_size

    def download(
        self,
        rec: Recording,
        dest: Path,
        *,
        channel: int,
        start: str,
        end: str,
    ) -> tuple[int, bool]:
        """Retorna (tamanho_bytes, já_é_recorte_2min)."""
        print("tentando recorte por tempo (loadfile.cgi)...")
        clip_size = self.download_clip(channel, start, end, dest)
        if clip_size:
            return clip_size, True

        print("loadfile indisponível — baixando bloco .dav inteiro (pode demorar)...")
        return self.download_rpc(rec.filepath, dest, expected=rec.length), False


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
    if mp4.exists() and mp4.stat().st_size < 10_000:
        mp4.unlink()

    # .dav Intelbras = HEVC cru; -c copy para MP4 costuma falhar. Re-encode é mais confiável.
    input_flags = ["-fflags", "+genpts+discardcorrupt", "-err_detect", "ignore_err"]
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
            print(f"MP4 OK: {mp4} ({mp4.stat().st_size:,} bytes)")
            return mp4
        if mp4.exists():
            mp4.unlink(missing_ok=True)
        print(f"  → falhou ou arquivo vazio, próxima tentativa...")

    print("\nconversão MP4 falhou. O .dav está OK — tente manualmente:")
    print(f"  ffmpeg -y -i {dest} -c:v libx264 -preset fast -crf 23 {mp4}")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Intelbras MHDX")
    parser.add_argument("--list", action="store_true", help="Só listar")
    args = parser.parse_args()

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

        rec = client.pick_recording(recs, CHANNEL)

        dest = OUT_DIR / "recorte.dav"
        if dest.exists() and dest.stat().st_size == 0:
            dest.unlink()
        size, clipped = client.download(rec, dest, channel=CHANNEL, start=START, end=END)
        print(f"\nSalvo: {dest} ({size:,} bytes)")
        convert_to_mp4(dest, rec, already_clipped=clipped, start=START, end=END)
        return 0
    except KeyboardInterrupt:
        print("\ninterrompido", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
