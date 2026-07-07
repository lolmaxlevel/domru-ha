# Dom.ru Smart Intercom Integration for Home Assistant

This integration allows you to control your Dom.ru Smart Intercom (digital intercom system) from Home Assistant.

## Features

- 🔐 Authentication using phone + SMS code or login and password
- 🚪 Open door control
- 🚚 One-shot courier auto-open switch for the next incoming call
- 📸 Camera snapshots from intercom cameras
- 📱 Display place and access control information
- 🔔 Support for multiple intercom devices

## Installation

### Via HACS

1. Open HACS
2. Click on "Custom repositories"
3. Add `https://github.com/yourusername/domru-ha` as a custom repository
4. Select "Integration"
5. Search for "Dom.ru Smart Intercom" and install

### Manual Installation

1. Clone the repository to your `custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to Settings → Devices & Services → Create Automation
2. Click "Create Integration"
3. Search for "Dom.ru Smart Intercom"
4. Choose Phone + SMS code or Username + password
5. For phone login, enter your phone number, select an account, and confirm the SMS code
6. For password login, enter your login credentials
7. Complete the setup

## Supported Entities

- **Sensor**: Balance, payment, block status, next payment date, and call status
- **Button**: Open door, plus one button for each access control when multiple
  access controls are available
- **Camera**: Intercom camera snapshots, including access-control snapshots
- **Switch**: Courier auto-open
- **Diagnostic entities**: SIP status, event count, and last event

## Known issues

Camera previews or snapshots may not appear when the Dom.ru API returns
`500 Internal Server Error` for
`/rest/v1/forpost/cameras/{cameraId}/snapshots`. This is an upstream API
response for the snapshot request; the camera stream may still work normally.

## Door opening behavior

The **Open Door** button keeps the original behavior and opens the first
available access control. The integration also creates a separate open button
for each item returned in `access_controls` when there is more than one access
control, so Lovelace dashboards can target a specific gate, entrance, or door
directly without duplicate controls on single-door installs.

Automations can call `domru.open_door` with either `access_control_id` or
`door_index`. `door_index` is zero-based: `0` opens the first access control,
`1` opens the second, and so on. If neither field is provided, the service opens
the first available access control.

If an incoming call is active, an open button answers the call, opens the door,
and then hangs up. The `domru.open_door` service only sends the API open command.

The **Courier Auto Open** switch is one-shot mode. Turn it on before a delivery:
the next incoming call opens the door automatically, then the switch turns
itself off. Use the **Courier Auto Open Door** select entity to choose which
access control this one-shot mode opens. The select entity is disabled by
default and unavailable when there is only one access control.

> **Important:** Incoming calls depend on SIP registration. Dom.ru may route a
> call to the mobile app instead of Home Assistant, so the integration can miss
> some calls. Do not rely on it as the only critical way to answer calls or open
> the door.

## API Documentation

The integration is based on reverse-engineered API from Dom.ru mobile application. See `dom-ru-api.md` for detailed API documentation.

### Authentication

The integration supports phone authentication using SMS confirmation and stores
the returned refresh token for future sessions. It also supports login/password
authentication using hashed credentials:
- `hash1`: SHA1 of password (base64 encoded)
- `hash2`: MD5 of specific combined string with timestamp

### Endpoints

- **Auth**: `POST /auth/v2/auth/{login}/password`
- **Places**: `GET /rest/v3/subscriber-places`
- **Access Controls**: `GET /rest/v1/places/{placeId}/accesscontrols`
- **Cameras**: `GET /rest/v1/places/{placeId}/cameras`, with fallback to
  `GET /rest/v1/forpost/cameras`
- **Door Action**: `POST /rest/v1/places/{placeId}/accesscontrols/{deviceId}/actions`
- **FORPOST Door Action**:
  `POST /rest/v1/forpost/cameras/{cameraId}/devices/{deviceId}/open`
- **Entrance Door Action**:
  `POST /rest/v1/places/{placeId}/accesscontrols/{deviceId}/entrances/{entranceId}/actions`
- **Camera Snapshots**: `GET /rest/v1/forpost/cameras/{cameraId}/snapshots`
- **Access Control Snapshots**:
  `GET /rest/v1/places/{placeId}/accesscontrols/{deviceId}/videosnapshots`

## Troubleshooting

### Authentication Failed

- Ensure your login and password are correct
- Check that you have access to Dom.ru Smart Intercom service

### Connection Issues

- Verify your internet connection
- Check that the API server is accessible
- Look at the Home Assistant logs for detailed error messages

## Development

To develop this integration:

1. Clone the repository
2. Create a development environment using `.devcontainer`
3. Install required dependencies: `pip install -r requirements.txt`
4. Run linting: `scripts/lint`
5. Run development Home Assistant: `scripts/develop`

## License

See LICENSE file

## Support

For issues and questions, please visit:
- GitHub Issues: https://github.com/yourusername/domru-ha/issues
- Home Assistant Forum: https://community.home-assistant.io/

## Disclaimer

This integration is a reverse-engineered implementation based on the mobile application API. It is not officially supported by Dom.ru or Proptech. Use it at your own risk.
