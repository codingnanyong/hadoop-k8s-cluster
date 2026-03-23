# Security Policy

## Repository hygiene (this project)

- **Do not commit** real cluster node hostnames, node IPs, host disk paths, JDBC URLs with embedded credentials, or database passwords.
- Use **`hive-metastore-db-secret.example.yaml`** as a template; keep the real `hive-metastore-db-secret.yaml` local only (see `.gitignore`).
- Replace placeholders such as `YOUR_NODE_IP`, `worker-01` / `worker-02` / `worker-03`, and `/var/lib/hadoop-k8s/...` with values that match **your** environment before applying manifests.
- If you ever committed secrets by mistake, **rotate** those credentials and use `git filter-repo` or similar to purge history.

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| main    | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly.

### How to Report

1. **Do not** open a public issue for security vulnerabilities.
2. Email the details to **<codingnanyong@gmail.com>** with the subject line: `[Security] <project name> - <brief description>`.
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)
   - Your contact information for follow-up

### What to Expect

- **Acknowledgment**: Within 48 hours
- **Assessment**: Within 7 days
- **Fix timeline**: Depends on severity; critical issues will be prioritized
- **Credit**: Contributors will be acknowledged (unless you prefer anonymity) after a fix is released

Thank you for helping keep this project and its users safe.
