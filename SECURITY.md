# Security & Responsible Usage Policy

## Authorized Use Only

**AuditFlow** is a defensive open-source security auditing, isolated local verification, and responsible vulnerability disclosure workflow framework.

By using this software, you agree to the following strict boundaries:

1. **Source-Code Auditing & Isolated Local Sandboxes Only**: Dynamic verification features are designed strictly to run against **local, self-hosted, ephemeral isolated environments** (such as disposable local Docker containers or isolated local VMs) built from open-source repositories.
2. **No Unauthorized External Testing**: Never point AuditFlow's verification or evidence-capture modules at third-party production systems, public internet hosts, or environments without explicit written authorization.
3. **Responsible Disclosure**: Validated findings should be reported responsibly to the upstream maintainers and/or national vulnerability databases (such as CNVD, CNNVD, or CVE CNAs) with clear remediation guidance, and sensitive system secrets should never be leaked in public reports.
4. **Local Network Guardrails**: AuditFlow enforces local/private-network URL allowlists by default during verification runs and requires explicit human-in-the-loop approval before entering any dynamic verification stage.

## Reporting Security Issues in AuditFlow Itself

If you discover a security vulnerability in AuditFlow itself (for example, command injection in a CLI adapter or path traversal in report output), please report it privately to the maintainers before opening a public issue.
