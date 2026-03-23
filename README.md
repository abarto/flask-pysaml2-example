# Introduction

This project is a SAML Service Provider (SP) example built with
[Flask](https://palletsprojects.com/p/flask/) and
[pysaml2](https://github.com/IdentityPython/pysaml2).

It demonstrates a complete SP-initiated SSO flow and includes defaults that are
safer for real-world deployments:

- AuthnRequest/Response correlation using request IDs.
- RelayState validation to prevent open redirects.
- Cached IdP metadata fetch with timeout.
- Configurable SAML attribute mapping for JIT provisioning.
- SP metadata endpoint for easier IdP onboarding.

## What this example includes

- Login start endpoint: `/auth/saml/login/<idp_name>`
- Assertion Consumer Service (ACS): `/auth/saml/sso/<idp_name>`
- SP metadata endpoint: `/auth/saml/metadata/<idp_name>`
- Local user session with `flask-login`
- JIT user provisioning into SQLite

# Requirements

- [python](https://www.python.org/) 3.12+
- [uv](https://docs.astral.sh/uv/)

You also need build dependencies for PySAML2 (`libffi` and `xmlsec1`).

## Mac OS X

```shell
brew install libffi libxmlsec1
```

## RHEL/Fedora/CentOS

```shell
sudo yum install libffi-devel xmlsec1 xmlsec1-openssl
```

## Debian/Ubuntu

```shell
sudo apt-get install libffi-dev xmlsec1 libxmlsec1-openssl
```

# Installation

```shell
uv sync
```

# Configuration

Prefer config file or environment variables over editing application code.

## Option A: instance config file

Create `instance/config.py` and start from
[`config.py.example`](./config.py.example).

## Option B: environment variable for IdP settings

You can pass IdP settings as JSON:

```shell
export SAML_IDP_SETTINGS_JSON='{"example-oktadev":{"entityid":"http://flask-pysaml2-example","metadata_url":"https://dev-12345678.okta.com/app/foobar/sso/saml/metadata","want_response_signed":true}}'
```

# Running

```shell
FLASK_APP=flask_pysaml2_example FLASK_DEBUG=1 uv run flask run --port 5000
```

Or with Docker:

```shell
docker compose up
```

# Minimal SP-Initiated Flow

Use this path first if your goal is to understand the core pysaml2 flow with as
little cognitive load as possible.

1. Configure exactly one IdP in `instance/config.py` (or `SAML_IDP_SETTINGS_JSON`) with only `entityid` and `metadata_url`.
2. Start the app and open `http://localhost:5000`.
3. Click the IdP login link, which calls `/auth/saml/login/<idp_name>`.
4. Complete login at the IdP and return to `/auth/saml/sso/<idp_name>`.
5. Confirm you land on `/user` and that a local session/user was created.

At this stage, focus on understanding the SP-initiated round trip:
`login endpoint -> IdP redirect -> SAMLResponse POST to ACS -> local login`.

# Hardened Flow (What Was Added And Why)

After completing the minimal path, revisit the same flow and map each safeguard
to a concrete risk.

1. Request/response correlation with request IDs (`InResponseTo`) helps reject unsolicited or mismatched assertions.
2. RelayState allowlisting blocks open-redirect abuse and ensures post-login navigation stays on trusted hosts.
3. Metadata fetch timeout and cache reduce IdP metadata latency and avoid repeated network calls during login.
4. Explicit status handling for auth failures (400/401/404/502/500) makes failures easier to reason about while learning.
5. Unknown IdP handling avoids ambiguous behavior and teaches explicit trust boundaries in multi-IdP setups.
6. JIT provisioning error handling keeps auth failures visible and prevents silent partial user creation.

Use this second pass to connect behavior to intent: each check is not new
functionality, but a defense or reliability improvement around the same basic
SAML login flow.

# SAML Flow (SP-Initiated)

```text
Browser -> Flask SP: GET /auth/saml/login/<idp>
Flask SP -> Browser: 302 to IdP SSO URL (+ AuthnRequest, RelayState)
Browser -> IdP: AuthnRequest
IdP -> Browser: HTML form POST (SAMLResponse + RelayState)
Browser -> Flask SP: POST /auth/saml/sso/<idp>
Flask SP: verify response, verify InResponseTo, provision user, create session
Flask SP -> Browser: 302 to safe RelayState (or /user)
```

# Quick Validation with saml.oktadev.com

1. Run the Flask app and expose it through ngrok:

```shell
ngrok http 5000
```

2. Open `http://saml.oktadev.com` and configure:

- `Issuer`: `urn:example:idp`
- `SAML ACS URL`: `http://<replace-me>.ngrok.io/auth/saml/sso/example-oktadev`
- `SAML Audience URI`: `http://flask-pysaml2-example`

3. (Recommended) import SP metadata from:

- `http://<replace-me>.ngrok.io/auth/saml/metadata/example-oktadev`

4. Submit and verify login succeeds.

If successful, output will be similar to:
![img](./docs/_static/validation-success.png)

# Security Validation

After basic validation, run the extended checks in saml.oktadev.com using
**Run security validation**.

# Minimal Production Checklist

- Use HTTPS everywhere (ACS, metadata endpoint, app base URL).
- Set a strong `SECRET_KEY`.
- Keep `SESSION_COOKIE_SECURE=true` in production.
- Keep `allow_unsolicited` disabled (enabled requests must be correlated).
- Require signed assertions and preferably signed responses.
- Validate RelayState against same-host or explicit allowlist.
- Cache IdP metadata with timeout and monitor certificate rotation.
- Log authentication events, but avoid logging full assertions/PII payloads.

# Tests

Run unit tests:

```shell
uv run python -m unittest discover -s tests -p 'test_*.py'
```
