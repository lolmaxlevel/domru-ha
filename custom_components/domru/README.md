# Dom.ru Smart Intercom Integration for Home Assistant

This integration allows you to control your Dom.ru Smart Intercom (digital intercom system) from Home Assistant.

## Features

- 🔐 Authentication using login and password
- 🚪 Open door control
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
4. Enter your login credentials (login/password)
5. Complete the setup

## Supported Entities

- **Sensor**: Place name, Access control name
- **Button**: Open door
- **Camera**: Intercom camera snapshots
- **Binary Sensor**: Connectivity status
- **Switch**: Future switch controls

## API Documentation

The integration is based on reverse-engineered API from Dom.ru mobile application. See `dom-ru-api.md` for detailed API documentation.

### Authentication

The integration supports login/password authentication using hashed credentials:
- `hash1`: SHA1 of password (base64 encoded)
- `hash2`: MD5 of specific combined string with timestamp

### Endpoints

- **Auth**: `POST /auth/v2/auth/{login}/password`
- **Places**: `GET /rest/v3/subscriber-places`
- **Access Controls**: `GET /rest/v1/places/{placeId}/accesscontrols`
- **Cameras**: `GET /rest/v1/forpost/cameras`
- **Door Action**: `POST /rest/v1/places/{placeId}/accesscontrols/{deviceId}/actions`
- **Snapshots**: `GET /rest/v1/forpost/cameras/{cameraId}/snapshots`

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

