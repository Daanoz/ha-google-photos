"""TypeDefinition for Google Photos Library API"""
from typing import TypedDict, Optional, Callable, Any

from googleapiclient.discovery import Resource


class PhotosLibraryService(Resource):
    """Service implementation for the Photo Library api."""

    albums: Callable[[], Any]
    mediaItems: Callable[[], Any]


class MediaMetadataPhoto(TypedDict):
    """Metadata that is specific to a photo, such as, ISO, focal length and exposure time.
    Some of these fields may be null or not included."""

    cameraMake: Optional[str]
    cameraModel: Optional[str]
    focalLength: Optional[float]
    apertureFNumber: Optional[float]
    isoEquivalent: Optional[int]
    exposureTime: Optional[str]


class MediaMetadataVideo(TypedDict):
    """Metadata that is specific to a video, for example, fps and processing status.
    Some of these fields may be null or not included."""

    cameraMake: Optional[str]
    cameraModel: Optional[str]
    fps: Optional[float]
    status: Optional[str]


class MediaContributorInfo(TypedDict):
    """Information about the user who added the media item. Note that this information is
    included only if the media item is within a shared album created by your app and you
    have the sharing scope."""

    profilePictureBaseUrl: str
    displayName: str


class MediaMetadata(TypedDict):
    """Metadata for a media item."""

    creationTime: str
    width: str
    height: str
    photo: Optional[MediaMetadataPhoto]
    video: Optional[MediaMetadataVideo]


class MediaListItem(TypedDict):
    """Representation of a media item (such as a photo or video) as part of a list in Google Photos."""

    id: str
    mediaMetadata: Optional[MediaMetadata]


class MediaItem(MediaListItem):
    """Representation of a media item (such as a photo or video) in Google Photos."""

    description: str
    productUrl: str
    baseUrl: str
    mimeType: str
    contributorInfo: Optional[MediaContributorInfo]
    filename: str


class Album(TypedDict):
    """Representation of an album in Google Photos. Albums are containers for media items."""

    id: str
    title: str
    productUrl: str | None
    isWriteable: bool
    mediaItemsCount: str | None
    coverPhotoBaseUrl: str | None
    coverPhotoMediaItemId: str | None
