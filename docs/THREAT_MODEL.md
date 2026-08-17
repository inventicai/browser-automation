# Threat Model

## Trust boundaries

| Boundary | Inside | Outside |
|---|---|---|
| Orchestrator process | trusted | – |
| Browser extension | trusted | – |
| Network between them | – | untrusted (use WSS + auth) |
| Web page being automated | – | untrusted (treat all DOM as hostile) |

## Top risks

1. **Credential exfiltration via the automated browser.** Mitigated by running in the user's real Chrome (cookies already there) and never persisting them server-side. Extension never reads `cookie`/`Authorization` headers.
2. **Prompt injection from the page being automated.** Pydantic AI model sees only the AX tree + URL + user goal. Page text is not fed verbatim into planning context.
3. **Irreversible actions (purchase, delete, send).** Require explicit user approval in the extension side panel before execution.
4. **CDP exposure.** Server never exposes CDP ports publicly. Extension is outbound-only.

## What is *not* in scope

- CAPTCHA bypass, anti-detection, stealth.
- Persisting browser cookies, localStorage, or session tokens on the server.
- Remote code execution via the extension.
