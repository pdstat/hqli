-- 00-network-acl-unrestricted.sql
-- Grants HQLI unrestricted egress (DNS + TCP) in XEPDB1.
-- Re-runnable: only appends ACEs if they don't already exist.

WHENEVER SQLERROR EXIT SQL.SQLCODE
ALTER SESSION SET CONTAINER = XEPDB1;

-- Ensure the app user can call the network packages
GRANT EXECUTE ON UTL_INADDR TO HQLI;
GRANT EXECUTE ON UTL_HTTP  TO HQLI;

-- Helper: returns 1 if an ACE row already exists
CREATE OR REPLACE FUNCTION acl_exists(
  p_host        IN VARCHAR2,
  p_lower_port  IN NUMBER,
  p_upper_port  IN NUMBER,
  p_principal   IN VARCHAR2,
  p_privilege   IN VARCHAR2
) RETURN NUMBER AUTHID CURRENT_USER IS
  v_cnt NUMBER;
BEGIN
  SELECT COUNT(*)
    INTO v_cnt
    FROM dba_host_aces
   WHERE NVL(host,'*')        = NVL(p_host, '*')   -- treat NULL as wildcard row
     AND NVL(lower_port,-1)   = NVL(p_lower_port,-1)
     AND NVL(upper_port,-1)   = NVL(p_upper_port,-1)
     AND principal            = p_principal
     AND privilege            = UPPER(p_privilege);
  RETURN CASE WHEN v_cnt > 0 THEN 1 ELSE 0 END;
END;
/

BEGIN
  -- 1) DNS resolution everywhere (privilege 'resolve' MUST have NULL ports)
  IF acl_exists('*', NULL, NULL, 'HQLI', 'RESOLVE') = 0 THEN
    DBMS_NETWORK_ACL_ADMIN.APPEND_HOST_ACE(
      host       => '*',            -- wildcard: all hosts/domains/IPs
      lower_port => NULL,           -- required NULL for 'resolve'
      upper_port => NULL,
      ace        => xs$ace_type(
                     privilege_list => xs$name_list('resolve'),
                     principal_name => 'HQLI',
                     principal_type => xs_acl.ptype_db));
  END IF;

  -- 2) TCP connect+resolve everywhere (HTTP/any TCP).
  -- Ports must be NULL to mean "all ports".
  IF acl_exists('*', NULL, NULL, 'HQLI', 'CONNECT') = 0 THEN
    DBMS_NETWORK_ACL_ADMIN.APPEND_HOST_ACE(
      host       => '*',            -- all hosts
      lower_port => NULL,           -- NULL = all ports
      upper_port => NULL,
      ace        => xs$ace_type(
                     privilege_list => xs$name_list('connect','resolve'),
                     principal_name => 'HQLI',
                     principal_type => xs_acl.ptype_db));
  END IF;
END;
/
SHOW ERRORS

COMMIT;

-- Verify
SET PAGES 200 LINES 200
COL host FOR A8
COL principal FOR A20
SELECT NVL(host,'*ALL*') AS host, lower_port, upper_port, principal, privilege
FROM   dba_host_aces
WHERE  principal = 'HQLI'
ORDER  BY host, privilege;
