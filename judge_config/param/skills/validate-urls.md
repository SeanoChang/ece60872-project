# Skill: Validate URLs

**Detects:**
- MITRE ATT&CK: T1190 (Exploit Public-Facing Application) — https://attack.mitre.org/techniques/T1190/
- MITRE ATT&CK: T1195 (Supply Chain Compromise) — https://attack.mitre.org/techniques/T1195/
- CWE-400 (Uncontrolled Resource Consumption) — https://cwe.mitre.org/data/definitions/400.html
- OWASP LLM 02: Sensitive Information Disclosure (exfiltration via untrusted URLs)

## Investigation steps

1. Extract all URLs from command arguments and environment variables (http://, https://, ftp://)
2. Flag non-HTTPS URLs — data sent in cleartext to potential network eavesdroppers
3. Flag IP address URLs (e.g., `http://192.168.1.100`, `http://10.0.0.1`) — likely attacker infrastructure or internal network reconnaissance
4. Flag unusual ports (anything other than 80, 443, 8080) — potential backdoor or C2 communication
5. Verify domain legitimacy — cross-check against known services or trusted registries
6. Flag localhost URLs to unexpected ports — internal service exploitation or local privilege escalation
7. Flag download-and-execute patterns: `curl ... | bash`, `wget -O- ... | sh`, `curl ... | python`, `wget ... && bash`
8. Check if credentials are embedded in the URL (`http://user:pass@host`)

## Red flags
- Non-HTTPS exfiltration endpoints
- IP address URLs instead of domain names
- Download-and-execute piping to shell interpreters
- Embedded credentials in URLs
- Unusual ports suggesting C2 communication
- URLs to services not mentioned in the project or task scope

## References
- MITRE ATT&CK T1190: https://attack.mitre.org/techniques/T1190/
- MITRE ATT&CK T1195: https://attack.mitre.org/techniques/T1195/
- CWE-400 Uncontrolled Resource Consumption: https://cwe.mitre.org/data/definitions/400.html
