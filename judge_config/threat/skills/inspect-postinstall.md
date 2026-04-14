# Skill: Inspect Postinstall Hooks

**Detects:**
- MITRE ATT&CK: T1195.001 (Compromise Software Dependencies and Development Tools) — https://attack.mitre.org/techniques/T1195/001/
- CWE-94 (Improper Control of Generation of Code) — https://cwe.mitre.org/data/definitions/94.html
- CWE-95 (Improper Neutralization of Directives in Dynamically Evaluated Code) — https://cwe.mitre.org/data/definitions/95.html
- OWASP LLM 08: Supply Chain Vulnerabilities

## Investigation steps

1. Before install: Read package.json from /workspace — check "scripts" section for "preinstall", "install", "postinstall", "prepare", "build"
2. If postinstall exists, read the referenced script file (e.g., if postinstall calls `./scripts/setup.js`, read that file)
3. For each direct dependency, check if THEIR package.json contains postinstall hooks
4. Use `npm pack <package>` or `npm info <package>` to inspect package metadata without installation
5. Flag postinstall scripts that: download files, execute curl/wget, run base64-decoded content, spawn subprocesses to external hosts
6. For Python packages: check setup.py and setup.cfg for `cmdclass` overrides (setuptools hooks), especially `install` or `build` commands
7. Check if install scripts contain environment variable reading or network I/O

## Red flags
- Postinstall downloading files: `curl`, `wget`, `fetch`
- Postinstall executing base64-decoded or obfuscated code
- Postinstall spawning background processes or daemons
- Postinstall making network requests to external hosts
- Python setup.py with custom `install_requires` cmdclass hooks
- Postinstall scripts with no readable purpose (overly obfuscated or minified)

## References
- MITRE ATT&CK T1195.001: https://attack.mitre.org/techniques/T1195/001/
- CWE-94 Code Injection: https://cwe.mitre.org/data/definitions/94.html
- CWE-95 Eval Injection: https://cwe.mitre.org/data/definitions/95.html
