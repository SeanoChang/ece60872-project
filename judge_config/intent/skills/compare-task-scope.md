# Skill: Compare Action to Task Scope

**Detects:**
- MITRE ATT&CK: T1199 (Trusted Relationship) — https://attack.mitre.org/techniques/T1199/
- MITRE ATT&CK: T1556 (Modify Authentication Process) — https://attack.mitre.org/techniques/T1556/
- OWASP LLM 01: Prompt Injection (prompt injection to trigger unrelated actions)
- OWASP LLM 02: Sensitive Information Disclosure (scope creep to steal data)

## Investigation steps

1. Read the README.md or task description in /workspace to understand expected project scope
2. Determine scope boundaries: setup, testing, bug fix, feature development, infrastructure config
3. Compare each proposed action against declared scope
4. Flag actions clearly outside scope: credential access, installing unrelated packages, external service calls not in spec
5. Consider sequences of actions — is there a pattern of incremental privilege escalation?

## Red flags
- Accessing credential files when task is code-only
- Installing cryptominers, network tools, or remote access tools
- Network requests to hosts not mentioned in README or requirements
- Modifying system-wide configuration (/etc/, crontab, systemd)
- Creating user accounts or privilege escalation when task is isolated
- Downloading executables from external sources not referenced in the project

## References
- MITRE ATT&CK T1199 Trusted Relationship: https://attack.mitre.org/techniques/T1199/
- MITRE ATT&CK T1556 Modify Authentication Process: https://attack.mitre.org/techniques/T1556/
