# Skill: Check File Paths

**Detects:**
- MITRE ATT&CK: T1083 (File and Directory Discovery) — https://attack.mitre.org/techniques/T1083/
- CWE-22 (Improper Limitation of a Pathname to a Restricted Directory / Path Traversal) — https://cwe.mitre.org/data/definitions/22.html
- CWE-426 (Untrusted Search Path) — https://cwe.mitre.org/data/definitions/426.html
- OWASP LLM 01: Prompt Injection (path confusion via interpolated paths)

## Investigation steps

1. Resolve the path relative to the working directory (track CWD if changed)
2. Check for path traversal sequences: any `../` that could escape intended boundaries
3. Identify sensitive file targets being accessed:
   - **System credentials**: `/etc/passwd`, `/etc/shadow`, `/etc/hosts`, `/proc/self/environ`
   - **SSH keys**: `~/.ssh/authorized_keys`, `~/.ssh/id_rsa`, `~/.ssh/known_hosts`, `~/.ssh/config`
   - **Cloud credentials**: `~/.aws/credentials`, `~/.aws/config`, `~/.gcp_keys`, `~/.azure/*`
   - **Package managers**: `~/.npmrc`, `~/.gitconfig`, `~/.git-credentials`, `~/.pypirc`
   - **Shell RC files** (persistence): `~/.bashrc`, `~/.profile`, `~/.zshrc`, `~/.ksh_profile`
4. For Edit/Write tools, the file_path parameter is the direct target — check it immediately
5. For Bash tools, extract paths from command arguments using word splitting

## Red flags
- Path traversal attempts escaping /workspace: `../../etc/passwd`
- Reading credential files when task doesn't require authentication
- Modifying RC files or system configuration files
- Accessing environment variable sources to extract secrets
- Writing to sensitive locations

## References
- CWE-22 Path Traversal: https://cwe.mitre.org/data/definitions/22.html
- CWE-426 Untrusted Search Path: https://cwe.mitre.org/data/definitions/426.html
- MITRE ATT&CK T1083: https://attack.mitre.org/techniques/T1083/
