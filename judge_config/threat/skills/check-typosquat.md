# Skill: Check for Typosquatted Packages

**Detects:**
- MITRE ATT&CK: T1195.001 (Compromise Software Dependencies and Development Tools) — https://attack.mitre.org/techniques/T1195/001/
- MITRE ATT&CK: T1195.002 (Compromise Software Supply Chain) — https://attack.mitre.org/techniques/T1195/002/
- CWE-426 (Untrusted Search Path) — https://cwe.mitre.org/data/definitions/426.html
- OWASP LLM 08: Supply Chain Vulnerabilities

## Investigation steps

1. Extract package names from package.json (npm), requirements.txt (pip), or other package manifests
2. For each dependency, check the official registry (npmjs.com for npm, pypi.org for pip)
3. Compare package names character-by-character against known popular packages
4. Check for common typosquat patterns:
   - **Swaps**: `axios` → `axois`, `requests` → `reqeusts`
   - **Homoglyphs**: `rn` → `m`, `0` → `O` (in package names)
   - **Extra/missing characters**: `crypto-js` → `plain-crypto-js`, `colorama` → `colourama`
   - **Hyphen variations**: `crypto_js` → `crypto-js`
5. Check publish metadata: creation date (brand new = suspicious), maintainer changes, download counts
6. Verify the package exists on the official registry; if not found, flag as potentially typosquatted

## Red flags
- Package names similar to popular libraries with minor character differences
- Packages with very recent publication dates and no version history
- Packages with suspiciously high or low download counts relative to similarity
- Packages not found on official registry sources
- Maintainer information differing from the popular package's maintainer

## References
- MITRE ATT&CK T1195.001: https://attack.mitre.org/techniques/T1195/001/
- MITRE ATT&CK T1195.002: https://attack.mitre.org/techniques/T1195/002/
- CWE-426: https://cwe.mitre.org/data/definitions/426.html
