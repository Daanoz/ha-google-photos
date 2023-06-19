# Google Photos Integration for Home Assistant

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]][license]

[![hacs][hacsbadge]][hacs]
[![Project Maintenance][maintenance-shield]][user_profile]
[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

[![Discord][discord-shield]][discord]
[![Community Forum][forum-shield]][forum]

This integration allows you to add albums from your Google Photos account as a `camera` entity to your Home Assistant setup. The entity will be showing media from your Google Photo album so you can add some personalization to your dashboards.

**This component will set up the following platforms.**

For each selected album:

Platform | Name | Description
-- | --  | --
`camera` | `media` | An image from the Google Photos Album.
`sensor` | `filename` | Filename of the currently selected media item.
`sensor` | `creation_timestamp` | Timestamp of the currently selected media item.
`sensor` | `media_count` | Counter showing the number of media items in the album (photo + video). It could take a while to populate all media items, to check if the integration is still loading an attribute `is_updating` is available.
`select` | `image_selection_mode` | Configuration setting on how to pick the next image.
`select` | `crop_mode` | Configuration setting on how to crop the image, either `Original`, `Crop` or `Combine images` [(explanation)](#crop-modes).
`select` | `update_interval` | Configuration setting on how often to update the image, if you have a lot of albums running on your instance it is adviseable to not set this to low.

![example][exampleimg]

## Installation

### HACS (Once available)
1. Find the integration as `Google Photos`
1. Click install.
1. Restart Home Assistant.

### Manual
1. Using the tool of choice open the directory (folder) for your HA configuration (where you find `configuration.yaml`).
1. If you do not have a `custom_components` directory (folder) there, you need to create it.
1. In the `custom_components` directory (folder) create a new folder called `google_photos`.
1. Download _all_ the files from the `custom_components/google_photos/` directory (folder) in this repository.
1. Place the files you downloaded in the new directory (folder) you created.
1. Restart Home Assistant

## Configuration
1. In the HA UI go to "Configuration" -> "Integrations" click "+" and search for "Google Photos".
1. Generate a Client ID and Client Secret on Google Developers Console. The authentication procedure in this integration is based of the [Google Mail](https://next.home-assistant.io/integrations/google_mail/) integration.
    1. First, go to the Google Developers Console to enable [Photos Library API](https://console.cloud.google.com/apis/library/photoslibrary.googleapis.com)
    1. The wizard will ask you to choose a project to manage your application. Select a project and click continue.
    1. Verify that your Photos Library API was enabled and click ‘Go to credentials’
    1. Navigate to APIs & Services (left sidebar) > [Credentials](https://console.cloud.google.com/apis/credentials)
    1. Click on the field on the left of the screen, OAuth Consent Screen.
    1. Select External and Create.
    1. Set the App Name (the name of the application asking for consent) to anything you want, e.g., Home Assistant.
    1. You then need to select a Support email. To do this, click the drop-down box and select your email address.
    1. You finally need to complete the section: Developer contact information. To do this, enter your email address (the same as above is fine).
    1. Scroll to the bottom and click Save and Continue. You don’t have to fill out anything else, or it may enable additional review.
    1. You will then be automatically taken to the Scopes page. You do not need to add any scopes here, so click Save and Continue to move to the Optional info page. You do not need to add anything to the Optional info page, so click Save and Continue, which will take you to the Summary page. Click Back to Dashboard.
    1. Click OAuth consent screen again and set Publish Status to Production otherwise your credentials will expire every 7 days.
    1. Make sure Publishing status is set to production.
    1. Click Credentials in the menu on the left-hand side of the screen, then click Create credentials (at the top of the screen), then select OAuth client ID.
    1. Set the Application type to Web application and give this credential set a name (like “Home Assistant Credentials”).
    1. Add [https://my.home-assistant.io/redirect/oauth](https://my.home-assistant.io/redirect/oauth) to Authorized redirect URIs then click Create.
    1/ You will then be presented with a pop-up saying OAuth client created showing Your Client ID and Your Client Secret. Make a note of these (for example, copy and paste them into a text editor), as you will need these shortly. Once you have noted these strings, click OK. If you need to find these credentials again at any point, then navigate to APIs & Services > Credentials, and you will see Home Assistant Credentials (or whatever you named them in the previous step) under OAuth 2.0 Client IDs. To view both the Client ID and Client secret, click on the pencil icon; this will take you to the settings page for these credentials, and the information will be on the right-hand side of the page.
    1. Double-check that the Photos Library API has been automatically enabled. To do this, select Library from the menu, then search for Photos Library API. If it is enabled you will see API Enabled with a green tick next to it. If it is not enabled, then enable it.
1. Provide the integration with a client id and client secret to use with th Google Photos Library api. If you want to change the credentials, go to [![Open your Home Assistant instance and Manage your application credentials.](https://my.home-assistant.io/badges/application_credentials.svg)](https://my.home-assistant.io/redirect/application_credentials/).
1. Continue through the steps of selecting the account you want to authorize.
1. **NOTE**: You may get a message telling you that the app has not been verified and you will need to acknowledge that in order to proceed.
1. You can now see the details of what you are authorizing Home Assistant to access with two options at the bottom. Click **Continue**.
1. The page will now display *Link account to Home Assistant?*, note Your instance URL. If this is not correct, please refer to [My Home Assistant](https://next.home-assistant.io/integrations/my). If everything looks good, click **Link Account**.
1. You may close the window, and return back to Home Assistant where you should see a Success! message from Home Assistant.

After the setup is complete a device will be created with entity for your favorite photos. To add more albums from you account, click configure on the integration card.

### Example setup

Screenshots:
- [OAuth consent screen setup](/docs/OAuthConsentOverview.png)
- [OAuth consent screen edit, step1](/docs/OAuthConsent1.png)
- [OAuth consent screen edit, step2](/docs/OAuthConsent2.png)
- [OAuth consent screen edit, step3](/docs/OAuthConsent3.png)
- [OAuth consent screen edit, step4](/docs/OAuthConsent4.png)
- [Credentials](/docs/Credentials.png)

## Crop modes

### Original

Provides scaled down images that would fit in the requested view in the original aspect ratio. If your dashboard configuration does not specify the aspect ratio, the card size could change for every image.

### Crop

Crop image to fit into the requested view.

### Combine images

In combine images mode, the integration will combine two images of the same orientation if it calculates that showing two images side by side would lead to a lower loss in square pixels than cropping a single image. For example; two portrait images on a landscape view.

## Examples

### Dashboard Picture card

```
show_state: false
show_name: false
camera_view: auto
type: picture-entity
entity: camera.google_photos_library_favorites
aspect_ratio: '1:1'
tap_action:
  action: call-service
  service: google_photos.next_media
  data:
    mode: RANDOM
  target:
    entity_id: camera.google_photos_library_favorites
```

### Lovelace wall panel

You can combine this integration with the [lovelace-wallpanel](https://github.com/j-a-n/lovelace-wallpanel) (min version 4.8) extension by [j-a-n](https://github.com/j-a-n) to show your photos as a screensaver on your dashboards. For the best results set the crop mode of the album to [Crop](#crop) or [Combine images](#combine-images).

Home Assistant Dashboard configuration yaml (raw config):
```yaml
wallpanel:
  enabled: true
  hide_toolbar: true
  hide_sidebar: true
  fullscreen: true
  image_fit: cover
  image_url: media-entity://camera.google_photos_favorites_media,
  cards:
      # Note: For this markdown card to work you need to enable write metadata in the integration settings.
    - type: markdown
      content: >-
        {{states.camera.google_photos_favorites_media.attributes.media_metadata.photo.cameraMake}},
        {{states.camera.google_photos_favorites_media.attributes.media_metadata.photo.cameraModel}}
```

**Important** Make sure to align the image crop modes with the configuration of the wall panel, if not set correctly images might appear blurry. For crop mode [original](#original), set the `image_fit` property to `contain`.

## Service

It is possible to control the album using the service exposed by `google_photos`.

### Go to next media

#### Example
```
service: google_photos.next_media
data:
  entity_id: camera.google_photos_library_favorites
  mode: Random
```

#### Key Descriptions
| Key | Required | Default | Description |
| --- | --- | --- | --- |
| entity_id | Yes | | Entity name of a Google Photo album camera. |
| mode | No | `Random` | Selection mode next image, either `Random` or `Album order` |

## FAQ

### How can I change my credentials? / I entered the wrong credentials now what?

Go to [![Open your Home Assistant instance and Manage your application credentials.](https://my.home-assistant.io/badges/application_credentials.svg)](https://my.home-assistant.io/redirect/application_credentials/) (or click the 3 dot menu on the integrations screen), here you can delete the credentials, the setup flow will ask for new credentials again when setting up the integration.

### Why is it always loading the same image after loading the integration?

This is the cover photo of you album, you can change it in Google Photos, or trigger a `next_media` on the service after start-up.

## Notes / Remarks / Limitations

- Currently the album media list is cached for 3 hours.
- Directly after loading the integration / starting HA, the album will only contain 100 items. This is done to reduce server load on the Google Photos servers, every 30 seconds a new batch of media is requested.

## Future plans
- Give end user more control over album cache time
- Support for videos
- Support loading media using [content categories](https://developers.google.com/photos/library/guides/apply-filters#content-categories)
- Support loading media filtered by date/time
- Custom photo carousel fronted component
- Add trigger on new media

## Debug Logging
To enable debug log, add the following lines to your configuration.yaml and restart your HomeAssistant.

```yaml
logger:
  default: info
  logs:
    custom_components.google_photos: debug
    googleapiclient: debug
```

## Contributions are welcome!

If you want to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md)

<!---->

***

[buymecoffee]: https://www.buymeacoffee.com/Daanoz
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
[commits-shield]: https://img.shields.io/github/commit-activity/y/daanoz/ha-google-photos.svg?style=for-the-badge
[commits]: https://github.com/daanoz/ha-google-photos/commits/master
[hacs]: https://hacs.xyz
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[discord]: https://discord.com/invite/home-assistant
[discord-shield]: https://img.shields.io/discord/330944238910963714.svg?style=for-the-badge
[exampleimg]: https://raw.githubusercontent.com/daanoz/ha-google-photos/main/example.png
[forum-shield]: https://img.shields.io/badge/community-forum-brightgreen.svg?style=for-the-badge
[forum]: https://community.home-assistant.io/
[license]: https://github.com/daanoz/ha-google-photos/blob/main/LICENSE
[license-shield]: https://img.shields.io/github/license/custom-components/integration_blueprint.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-Daan%20Sieben%20%40Daanoz-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/daanoz/ha-google-photos.svg?style=for-the-badge
[releases]: https://github.com/daanoz/ha-google-photos/releases
[user_profile]: https://github.com/daanoz
