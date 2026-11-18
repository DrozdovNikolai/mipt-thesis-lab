"""HTTP/1.1 loopback proxy with exact application-wire counters and controlled response loss.

Counts bytes read/written by the proxy, excluding TCP/IP/TLS. Bandwidth is per
connection, RTT is synthetic, upstream is actual Uvicorn/PostgreSQL. No external forwarding.
"""

import asyncio
import gzip
import hashlib
import json
import time
from urllib.parse import urlsplit
import httpx
from h1.common import append, BACKEND

control = dict(
    rtt_ms=0, kib_s=0, offline=False, gzip=False, drop_next=False, drop_path="", offline_after_drop=False, corrupt_receipt=False, label="setup"
)
events = []
upstream = None


async def handle(reader, writer):
    global control
    try:
        while True:
            try:
                head = await reader.readuntil(b"\r\n\r\n")
            except asyncio.IncompleteReadError:
                break
            first, *lines = head[:-4].split(b"\r\n")
            method, target, version = first.decode("latin1").split(" ")
            headers = {}
            for line in lines:
                k, v = line.split(b":", 1)
                headers[k.decode("latin1").lower()] = v.strip().decode("latin1")
            assert (
                "transfer-encoding" not in headers
            ), "Chunked request outside declared proxy profile"
            body = await reader.readexactly(int(headers.get("content-length", "0")))
            path = urlsplit(target).path
            if path == "/_control":
                if method == "POST":
                    update = json.loads(body or b"{}")
                    if update.pop("reset_events", False):
                        events.clear()
                    assert set(update) <= set(control)
                    control.update(update)
                result = json.dumps(dict(control=control, events=events)).encode()
                wire = (
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                    + str(len(result)).encode()
                    + b"\r\n\r\n"
                    + result
                )
                writer.write(wire)
                await writer.drain()
                continue
            cfg = dict(control)
            started = time.perf_counter()
            record = dict(
                label=cfg["label"],
                method=method,
                path=path,
                request_bytes=len(head) + len(body),
                request_body_sha256=hashlib.sha256(body).hexdigest(),
                rtt_ms=cfg["rtt_ms"],
                kib_s=cfg["kib_s"],
                gzip=cfg["gzip"],
                started_at=time.time(),
            )
            if cfg["offline"]:
                record.update(dropped="before_forward", response_bytes=0)
                events.append(record)
                append("proxy-http.jsonl", record)
                break
            await asyncio.sleep(cfg["rtt_ms"] / 2000)
            if cfg["kib_s"]:
                await asyncio.sleep(len(body) / (cfg["kib_s"] * 1024))
            forwarded = {
                k: v
                for k, v in headers.items()
                if k not in ("host", "connection", "accept-encoding", "content-length")
            }
            try:
                r = await upstream.request(
                    method,
                    target,
                    content=body,
                    headers={**forwarded, "accept-encoding": "identity"},
                )
            except httpx.TransportError as error:
                record.update(dropped="upstream_transport", response_bytes=0,
                    error=type(error).__name__, ms=(time.perf_counter()-started)*1000)
                events.append(record)
                append("proxy-http.jsonl", record)
                break
            record["status"] = r.status_code
            if (
                control["drop_next"]
                and method in ("POST", "PUT")
                and (not cfg["drop_path"] or path.endswith(cfg["drop_path"]))
                and r.status_code == 200
            ):
                control["drop_next"] = False
                if cfg["offline_after_drop"]:
                    control["offline"] = True
                record.update(
                    dropped="after_backend_response",
                    response_bytes=0,
                    ms=(time.perf_counter() - started) * 1000,
                )
                events.append(record)
                append("proxy-http.jsonl", record)
                break
            response_body = r.content
            if cfg["corrupt_receipt"] and path.endswith("/submit") and r.status_code == 200:
                changed = r.json()
                changed["submitReceipt"]["submissionManifestHash"] = "0" * 64
                response_body = json.dumps(changed).encode()
                record["receipt_corrupted"] = True
                control["corrupt_receipt"] = False
            response_headers = {
                k: v
                for k, v in r.headers.items()
                if k
                not in (
                    "content-length",
                    "content-encoding",
                    "transfer-encoding",
                    "connection",
                )
            }
            if (
                cfg["gzip"]
                and "gzip" in headers.get("accept-encoding", "")
                and len(response_body) >= 500
            ):
                response_body = gzip.compress(response_body, mtime=0)
                response_headers["content-encoding"] = "gzip"
            response_headers["content-length"] = str(len(response_body))
            response_headers["connection"] = "keep-alive"
            wire_head = (
                f"HTTP/1.1 {r.status_code} {r.reason_phrase}\r\n"
                + "".join(f"{k}: {v}\r\n" for k, v in response_headers.items())
                + "\r\n"
            ).encode("latin1")
            await asyncio.sleep(cfg["rtt_ms"] / 2000)
            writer.write(wire_head)
            await writer.drain()
            sent = len(wire_head)
            for i in range(0, len(response_body), 4096):
                chunk = response_body[i : i + 4096]
                if cfg["kib_s"]:
                    await asyncio.sleep(len(chunk) / (cfg["kib_s"] * 1024))
                writer.write(chunk)
                await writer.drain()
                sent += len(chunk)
            record.update(
                response_bytes=sent, ms=(time.perf_counter() - started) * 1000
            )
            events.append(record)
            append("proxy-http.jsonl", record)
            if headers.get("connection") == "close":
                break
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    except Exception as e:
        append("proxy-errors.jsonl", dict(type=type(e).__name__, message=str(e)))
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except ConnectionError:
            pass


async def main():
    global upstream
    async with httpx.AsyncClient(
        base_url=BACKEND, timeout=120
    ) as upstream:
        server = await asyncio.start_server(handle, "0.0.0.0", 8001)
        async with server:
            await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
