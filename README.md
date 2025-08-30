# HQli Vulnerable REST API & Enumeration Script

This project demonstrates a sample REST API vulnerable to HQL injection, along with a Python script to enumerate user IDs, properties, and property values from the `User1` entity.

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

2. **Run the script:**
   ```powershell
   python hqli-all.py
   ```
   The script will enumerate user IDs, properties, and property values from the `User1` entity by exploiting the HQL injection vulnerability.

## Notes
- The API endpoints and injection points are defined in the Java source code, primarily in `AgentController.java` and related files.
- The Python script (`hqli-all.py`) is designed to interact with the vulnerable API and demonstrate enumeration via HQL injection.
- For educational purposes only. Do **not** deploy this code in production environments.

## Project Structure
- `src/main/java/com/pdstat/hqli/` - Java source code for the REST API
- `hqli-all.py` - Python enumeration script
- `pom.xml` - Maven build file

## References
- [Spring Boot Documentation](https://spring.io/projects/spring-boot)
- [SQL/HQL Injection Overview](https://owasp.org/www-community/attacks/SQL_Injection)

---
**Disclaimer:** This project is for educational and testing purposes only. Do not use on systems without proper authorization.
