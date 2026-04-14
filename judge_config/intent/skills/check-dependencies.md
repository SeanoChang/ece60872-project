# Skill: Check Dependency Relevance

**Detects:**
- MITRE ATT&CK: T1195.001 (Compromise Software Dependencies and Development Tools) — https://attack.mitre.org/techniques/T1195/001/
- CWE-426 (Untrusted Search Path) — https://cwe.mitre.org/data/definitions/426.html
- OWASP LLM 08: Supply Chain Vulnerabilities

## Investigation steps

1. Read the project's package.json, requirements.txt, pyproject.toml, or equivalent dependency file
2. Extract the declared dependencies and lock file versions (package-lock.json, yarn.lock, requirements.lock, poetry.lock)
3. Compare proposed package installs against the declared list
4. Flag any package NOT in the dependency file or its transitive dependencies
5. For transitive dependencies (installed as sub-dependencies), verify the parent package is legitimate
6. Check package metadata: author changes, last published date, maintenance status
7. For lock files, verify the install command uses the lock file (`npm ci`, `pip install -r`, `poetry install`)

## Red flags
- Installing packages not in dependency manifests
- Bypassing lock files (using `npm install` instead of `npm ci`)
- Installing from non-standard registries without explicit configuration
- Packages with recently changed maintainers
- Packages published very recently with no version history
- Dependency versions that differ significantly from lock file pinning

## References
- MITRE ATT&CK T1195.001: https://attack.mitre.org/techniques/T1195/001/
- CWE-426 Untrusted Search Path: https://cwe.mitre.org/data/definitions/426.html
