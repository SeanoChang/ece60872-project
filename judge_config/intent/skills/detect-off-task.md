# Skill: Detect Off-Task Actions

**Detects:**
- MITRE ATT&CK: T1555 (Credentials from Password Stores) — https://attack.mitre.org/techniques/T1555/
- MITRE ATT&CK: T1041 (Exfiltration Over C2 Channel) — https://attack.mitre.org/techniques/T1041/
- MITRE ATT&CK: T1020 (Automated Exfiltration) — https://attack.mitre.org/techniques/T1020/
- OWASP LLM 02: Sensitive Information Disclosure

## Investigation steps

1. Cross-reference each action against the task description in README or /workspace
2. Flag reads of credential files (.env, ~/.aws, ~/.ssh, ~/.kube) when task doesn't require auth setup
3. Identify unrelated package installs: cryptominers, network tools (curl with C2 endpoints), remote access (ssh, nc, socat)
4. Track network requests to hosts not mentioned in project (check /tool_call.json history)
5. Watch for system configuration changes: /etc/, crontab, systemd services, iptables
6. Detect user/privilege modifications: useradd, usermod, chmod 777, sudo access
7. Monitor for downloading executables or scripts from external sources not in project dependencies

## Red flags
- Reading .env, ~/.aws/credentials when task is code-only
- Installing network tools (curl, wget, netcat, socat) with unusual flags
- Making HTTP requests to IP addresses or unknown domains
- Creating scheduled tasks or background services
- Modifying shell initialization files to persist access
- Downloading and executing scripts from external URLs without verification

## References
- MITRE ATT&CK T1555: https://attack.mitre.org/techniques/T1555/
- MITRE ATT&CK T1041: https://attack.mitre.org/techniques/T1041/
- MITRE ATT&CK T1020: https://attack.mitre.org/techniques/T1020/
