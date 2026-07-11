# Phone and SMS Authentication Reliability Design

## Goal

Make phone and SMS config entries usable immediately and after Home Assistant
restarts, expose readable errors for the documented authentication responses,
and show all door and call buttons in Home Assistant's Controls section.

## Authentication

The SMS confirmation response returns an opaque access token and a refresh token
with the same value. The integration will store the access token in the config
entry and initialize the API client with it. On startup, an SMS-authenticated
entry will reuse that token directly instead of calling the uncertain
`/auth/v2/session/refresh` endpoint.

Password authentication remains unchanged. Existing SMS entries that contain
only `refresh_token` will treat that value as the reusable access token, which
provides backward compatibility without asking the user for another SMS code.

This change does not alter config-entry unique IDs or account selection.

## Flow errors

The phone and SMS flow will translate the documented API outcomes into readable
Home Assistant errors:

- phone lookup `204`: the phone is not registered;
- phone lookup `400`: the phone/login format is invalid;
- phone lookup `200` without contracts: password authentication is required;
- SMS request `429`: too many SMS requests; retry later;
- SMS confirmation `406`: the SMS code format is invalid;
- known invalid-code responses: the SMS code is incorrect and can be retried.

The flow remains on the relevant step so the user can correct the input without
restarting configuration.

## Button placement

Remove `EntityCategory.CONFIG` from `open_door`, `dismiss_call`, and every
dynamically generated `open_door_*` button. Home Assistant will therefore place
all of them in Controls.

## Testing

Add regression coverage before implementation for:

- direct reuse of a stored SMS token without a refresh request;
- backward compatibility with existing refresh-token-only SMS entries;
- persistence of the SMS access token in new config entries;
- each documented phone/SMS error mapping;
- absence of the configuration entity category from all call/door buttons.

