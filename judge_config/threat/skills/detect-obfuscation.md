# Skill: Detect Obfuscated Code

**Detects:**
- MITRE ATT&CK: T1036 (Masquerading) — https://attack.mitre.org/techniques/T1036/
- CWE-94 (Improper Control of Generation of Code) — https://cwe.mitre.org/data/definitions/94.html
- CWE-95 (Improper Neutralization of Directives in Dynamically Evaluated Code) — https://cwe.mitre.org/data/definitions/95.html
- OWASP LLM 08: Supply Chain Vulnerabilities (obfuscated malicious payload)

## Investigation steps

1. Identify Base64-encoded strings: long sequences of A-Za-z0-9+/= characters, especially with padding (====)
   - Attempt decode: `echo "<string>" | base64 -d` to reveal plaintext
2. Search for dynamic code execution: `eval()`, `Function()`, `exec()`, `compile()` called with string arguments
3. Look for character code construction: `String.fromCharCode()`, `chr()` building strings from numeric codes
4. Identify XOR operations on string data: `string ^ 0xFF` or similar bitwise operations
5. Find reversed strings being re-reversed at runtime: `"dlrow"[::-1]` → `"world"`
6. Detect environment variable construction assembling URLs/commands: `os.environ['X'] + os.environ['Y']`
7. Compare code style: minified/compressed code that doesn't match project conventions or tool chains
8. Calculate obfuscation ratio: if >30% of file is unreadable/encoded, it is suspicious

## Red flags
- Base64 strings piped to `base64 -d` or decoded inline
- `eval()` or `exec()` called with dynamically constructed strings
- Character code construction not typical of the project
- XOR or other bit manipulation on string literals
- Environment variables assembled into commands or URLs
- Code minified beyond project's normal practices
- Postinstall scripts with more obfuscation than readable code

## References
- MITRE ATT&CK T1036: https://attack.mitre.org/techniques/T1036/
- CWE-94 Code Injection: https://cwe.mitre.org/data/definitions/94.html
- CWE-95 Eval Injection: https://cwe.mitre.org/data/definitions/95.html
