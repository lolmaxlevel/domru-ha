# Phone and SMS Authentication Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse SMS credentials across restarts, report documented authentication failures clearly, and place all call and door buttons in Controls.

**Architecture:** Store the SMS access token in config-entry data and pass it into `DomruApiClient`; existing SMS entries fall back to their stored refresh token as the access token. Keep HTTP status interpretation in the API client and expose stable exception messages to the config flow.

**Tech Stack:** Python 3, Home Assistant config flows/entities, `aiohttp`, `unittest`, Ruff.

---

### Task 1: Persist and reuse the SMS token

**Files:**
- Modify: `custom_components/domru/const.py`
- Modify: `custom_components/domru/api.py`
- Modify: `custom_components/domru/config_flow.py`
- Modify: `custom_components/domru/__init__.py`
- Test: `tests/test_api_phone_login.py`
- Test: `tests/test_config_flow_compat.py`

- [ ] **Step 1: Write failing token-reuse tests**

Add an `access_token` constructor argument test asserting that
`async_authenticate()` makes no HTTP request, plus source compatibility checks
asserting that config flow stores `CONF_ACCESS_TOKEN` and setup passes
`entry.data.get(CONF_ACCESS_TOKEN) or entry.data.get(CONF_REFRESH_TOKEN)`.

```python
def test_stored_access_token_authentication_makes_no_refresh_request(self) -> None:
    session = FakeSession()
    client = DomruApiClient(
        username=None,
        password=None,
        session=session,
        access_token="sms-token",
        refresh_token="sms-token",
        operator_id=123,
    )
    asyncio.run(client.async_authenticate())
    self.assertEqual(session.requests, [])
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m unittest tests.test_api_phone_login tests.test_config_flow_compat -v`

Expected: failure because `DomruApiClient` does not accept `access_token` and
the config flow does not store it.

- [ ] **Step 3: Implement direct token reuse**

Add `CONF_ACCESS_TOKEN = "access_token"`; expose `client.access_token`; accept
`access_token` in the client constructor; return immediately from
`_set_access_token()` when it is present. Store it after SMS confirmation and in
the config entry. During setup use:

```python
access_token=(
    entry.data.get(CONF_ACCESS_TOKEN)
    or entry.data.get(CONF_REFRESH_TOKEN)
),
```

The fallback supports entries created by the previous release.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `python -m unittest tests.test_api_phone_login tests.test_config_flow_compat -v`

Expected: all focused tests pass.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/domru/const.py custom_components/domru/api.py custom_components/domru/config_flow.py custom_components/domru/__init__.py tests/test_api_phone_login.py tests/test_config_flow_compat.py
git commit -m "fix: reuse SMS token across restarts"
```

### Task 2: Map documented phone and SMS errors

**Files:**
- Modify: `custom_components/domru/api.py`
- Test: `tests/test_api_phone_login.py`

- [ ] **Step 1: Write failing response-status tests**

Add tests for phone lookup `204`, phone lookup `400`, phone lookup `200` with no
contracts, SMS request `429`, and SMS confirmation `406`. Assert these messages:

```text
Phone number is not registered.
Invalid phone number or login.
Password authentication is required for this account.
Too many SMS requests. Try again later.
Invalid SMS code format.
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m unittest tests.test_api_phone_login -v`

Expected: failures containing generic `HTTP 204`, `HTTP 400`, `HTTP 429`, or
`HTTP 406`, or an empty account list.

- [ ] **Step 3: Implement endpoint-specific status handling**

Extend `_api_wrapper()` with optional `status_messages: dict[int, str]`. Before
generic error handling, raise `DomruApiClientAuthenticationError` using the
mapped message. Configure the three phone endpoints with the messages above,
and explicitly reject a successful phone-lookup response that contains no
contract list with `Password authentication is required for this account.`

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `python -m unittest tests.test_api_phone_login -v`

Expected: all phone-login tests pass.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/domru/api.py tests/test_api_phone_login.py
git commit -m "fix: report phone authentication errors"
```

### Task 3: Move every call and door button to Controls

**Files:**
- Modify: `custom_components/domru/button.py`
- Test: `tests/test_ha_sip_entities.py`

- [ ] **Step 1: Write a failing category regression test**

Read `custom_components/domru/button.py` and assert that no button description
assigns `EntityCategory.CONFIG`:

```python
def test_call_and_door_buttons_are_control_entities(self) -> None:
    source = Path("custom_components/domru/button.py").read_text()
    self.assertNotIn("entity_category=EntityCategory.CONFIG", source)
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m unittest tests.test_ha_sip_entities -v`

Expected: failure because base and generated door buttons are configuration
entities.

- [ ] **Step 3: Remove configuration categories**

Remove the `EntityCategory` import and every
`entity_category=EntityCategory.CONFIG` argument from `button.py`.

- [ ] **Step 4: Run the test and verify GREEN**

Run: `python -m unittest tests.test_ha_sip_entities -v`

Expected: all SIP entity tests pass.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/domru/button.py tests/test_ha_sip_entities.py
git commit -m "fix: show door controls in controls section"
```

### Task 4: Full verification

**Files:**
- Verify: all changed files

- [ ] **Step 1: Run the complete test suite**

Run: `python -m unittest discover tests`

Expected: all tests pass.

- [ ] **Step 2: Run lint and formatting checks**

Run: `python -m ruff check .`

Expected: exit code 0.

Run: `python -m ruff format . --check`

Expected: exit code 0.

- [ ] **Step 3: Check patch integrity**

Run: `git diff --check`

Expected: no output.

- [ ] **Step 4: Inspect repository state**

Run: `git status --short --branch`

Expected: only the local untracked `.codex/` directory remains.

