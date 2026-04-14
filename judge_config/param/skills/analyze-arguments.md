# Skill: Analyze Command Arguments

**Detects:**
- MITRE ATT&CK: T1190 (Exploit Public-Facing Application) — https://attack.mitre.org/techniques/T1190/
- MITRE ATT&CK: T1648 (Serverless Execution) — https://attack.mitre.org/techniques/T1648/
- CWE-78 (OS Command Injection) — https://cwe.mitre.org/data/definitions/78.html
- CWE-94 (Improper Control of Generation of Code) — https://cwe.mitre.org/data/definitions/94.html
- CWE-95 (Improper Neutralization of Directives in Dynamically Evaluated Code) — https://cwe.mitre.org/data/definitions/95.html
- OWASP LLM 01: Prompt Injection (code injection via interpolated input)

## Investigation steps

1. Split the command string by spaces to identify the base command and its arguments
2. Check each argument for shell metacharacters that enable command chaining: `;` `|` `&&` `||` backtick `$()` `>` `>>` `<` `<<` `{}` `$()`
3. Identify if arguments are being dynamically interpolated from variables or untrusted sources (`$VAR`, `${VAR}`)
4. Flag dangerous commands: `eval`, `exec`, `source`, `bash -c`, that accept dynamic code
5. Look for Base64 encoded strings being decoded and executed: `base64 -d | bash`
6. Check for unsafe flags that disable protections: `--force`, `--no-verify`, `--yes`, `-f`, `-y`, `--skip-hooks`
7. If the command uses pipes, trace whether output flows to sensitive destinations

## Red flags
- Dynamic code execution: `eval`, `exec`, or `source` with `$VAR` arguments
- Base64 decoding into command execution: `echo "..." | base64 -d | sh`
- Unsafe escape: Variables directly in command strings without quotes (`$VAR` not `"$VAR"`)
- Dangerous flags disabling safety checks
- Chaining commands with pipes into shell interpreters (`... | bash`, `... | sh`)

## References
- MITRE ATT&CK T1190: https://attack.mitre.org/techniques/T1190/
- CWE-78 OS Command Injection: https://cwe.mitre.org/data/definitions/78.html
- CWE-94 Code Injection: https://cwe.mitre.org/data/definitions/94.html
