# Domru Pure Python SIP Design

## Goal

Implement a pure Python SIP layer for the Dom.ru Home Assistant integration that can answer an intercom call, trigger door opening by completing the SIP dialog, and hang up without requiring audio support or an external SIP service.

The current REST door-open endpoint may unlock the door but does not stop ringing because it does not answer or terminate the SIP call. The captured Android app flow shows the official app stops ringing by completing this SIP sequence:

`REGISTER -> 401 -> REGISTER with Authorization -> 200 OK -> INVITE -> 100 Trying -> 200 OK with SDP -> ACK -> BYE -> 200 OK`

## Scope

- Rewrite `custom_components/domru/sip.py` as a small pure Python UDP SIP user agent.
- Keep the Home Assistant services/buttons already exposed by the integration.
- Add a standalone debug script under `dev/` that runs the same SIP core outside Home Assistant with extensive redacted wire logs.
- Do not implement real two-way audio. The SIP answer will advertise a minimal RTP endpoint and then hang up after the dialog is established.

## Architecture

### SIP Message Layer

Create parser and builder primitives inside `sip.py`.

- Parse request/status start lines, headers, repeated headers, compact headers, and body.
- Preserve repeated `Via` headers for response generation.
- Calculate `Content-Length` from encoded body bytes.
- Redact secrets in log output: `Authorization`, `WWW-Authenticate`, nonces, digest responses, and passwords.

### Digest Registration

Support the registration flow observed in the PCAPs.

- Send unauthenticated `REGISTER`.
- Parse `401 Unauthorized` and `WWW-Authenticate`.
- Send authenticated `REGISTER` with SIP digest response.
- Track registration expiry and re-register before expiry.
- Send `REGISTER` with `Expires: 0` during shutdown when registered.

### Call State Machine

Represent the active call explicitly.

States:

- `idle`: no active call.
- `ringing`: `INVITE` received and `100 Trying` sent.
- `answered`: `200 OK` sent, waiting for `ACK`.
- `established`: `ACK` received.
- `ending`: `BYE` sent, waiting for remote `200 OK`.

Incoming call handling:

- On `INVITE`, store dialog headers, remote contact, record-route, Call-ID, CSeq, and SDP.
- Send `100 Trying` immediately with no local To tag.
- `answer_call()` sends `200 OK` with local tag and minimal SDP.
- On `ACK`, mark established and optionally auto-hangup after a short configurable delay.
- `hangup_call()` sends `BYE` using the remote `Contact` URI and `Route` from `Record-Route`.
- On remote `200 OK` for BYE, clear the call.
- On `CANCEL` while ringing, send `200 OK` for CANCEL and `487 Request Terminated` for the INVITE.
- On remote `BYE`, send `200 OK` and clear the call.

### Home Assistant Wiring

Keep the existing integration surface.

- `answer_call` service calls SIP `answer_call()`.
- `reject_call` service sends `486 Busy Here` while ringing.
- Add or reuse a hangup path so automations can explicitly end a call.
- `open_door` button should prefer SIP answer plus hangup when a SIP call is ringing. If there is no active call, keep the existing REST open-door fallback.
- Sensors continue to expose SIP registration and call status.

### Standalone Debug Runner

Add `dev/sip_debug_client.py`.

Capabilities:

- Accept realm, username, password, local bind address, local port, and auto-answer/auto-hangup flags from CLI arguments or environment variables.
- Start the SIP client without Home Assistant.
- Log every inbound/outbound SIP message with direction, endpoint, first line, important headers, state transitions, and redacted authentication material.
- Print clear status events: registered, incoming call, answered, ACK received, BYE sent, ended, rejected, errors.
- Provide simple commands from stdin: `answer`, `hangup`, `reject`, `register`, `quit`.

This script is for collecting logs when Home Assistant would slow iteration. It should not duplicate SIP protocol logic; it imports the same core classes used by the integration.

## Testing

Use test-driven implementation.

Initial tests:

- SIP parser preserves repeated `Via` headers and body.
- Response builder emits correct `Content-Length`.
- Digest auth builds the expected response for a fixed nonce.
- Registration handles `401` then authenticated `REGISTER`.
- INVITE handling sends `100 Trying` and enters `ringing`.
- `answer_call()` sends `200 OK` with SDP and stable To tag.
- `ACK` transitions answered call to established.
- `hangup_call()` sends BYE with Contact request URI and Record-Route as Route.
- Remote `200 OK` for BYE clears call state.
- `CANCEL` sends both required responses and clears call.

## Acceptance Criteria

- A ringing Dom.ru intercom call can be answered by SIP and ringing stops.
- The call can be hung up after answer without audio support.
- The existing REST open-door path remains available when no SIP call is active.
- The standalone debug client can reproduce registration and call handling outside Home Assistant with redacted logs suitable to share.
- Unit tests cover parser, builders, registration, and call state transitions.
