
import io
import secrets
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_PROFILE_PICTURE_BYTES = 3 * 1024 * 1024
MAX_PROFILE_DIMENSION = 4096
OUTPUT_SIZE = (512, 512)


def _profile_directory():
    directory = (
        Path(__file__).resolve().parents[1]
        / "static"
        / "profile_pics"
    )
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_profile_picture(file_storage, user_id):
    file_storage.stream.seek(0)
    raw = file_storage.stream.read(MAX_PROFILE_PICTURE_BYTES + 1)

    if len(raw) > MAX_PROFILE_PICTURE_BYTES:
        raise ValueError("Profile pictures must be 3 MB or smaller.")
    if not raw:
        raise ValueError("The uploaded profile picture is empty.")

    try:
        check = Image.open(io.BytesIO(raw))
        if (
            check.width > MAX_PROFILE_DIMENSION
            or check.height > MAX_PROFILE_DIMENSION
        ):
            raise ValueError(
                "Profile pictures cannot exceed 4096 x 4096 pixels."
            )
        if check.format not in {"JPEG", "PNG", "WEBP"}:
            raise ValueError("Upload a JPG, PNG, or WebP image.")
        check.verify()

        image = Image.open(io.BytesIO(raw))
        image = ImageOps.exif_transpose(image).convert("RGB")
        image = ImageOps.fit(
            image,
            OUTPUT_SIZE,
            method=Image.Resampling.LANCZOS
        )
    except UnidentifiedImageError as error:
        raise ValueError(
            "The uploaded file is not a valid image."
        ) from error

    filename = f"user_{user_id}_{secrets.token_hex(10)}.webp"
    output_path = _profile_directory() / filename
    image.save(output_path, format="WEBP", quality=88, method=6)
    return filename


def delete_profile_picture(filename):
    if not filename:
        return
    safe_name = Path(filename).name
    if safe_name != filename:
        return
    try:
        (_profile_directory() / safe_name).unlink()
    except FileNotFoundError:
        pass
