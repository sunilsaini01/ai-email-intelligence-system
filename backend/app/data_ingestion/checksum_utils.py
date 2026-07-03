import hashlib
from pathlib import Path


def generate_sha256(file_path: str) -> str:
    """
    Generate SHA-256 checksum for a file.
    """
    sha256 = hashlib.sha256()

    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


def save_checksum(file_path: str, output_path: str):
    """
    Generate checksum and save to CHECKSUM.sha256 file.
    """
    checksum = generate_sha256(file_path)

    with open(output_path, "w") as f:
        f.write(checksum)

    print(f"[OK] Checksum saved to: {output_path}")
    print(f"SHA256: {checksum}")


def verify_checksum(file_path: str, checksum_file: str) -> bool:
    """
    Verify file integrity using stored checksum.
    """

    expected_checksum = Path(checksum_file).read_text().strip()

    actual_checksum = generate_sha256(file_path)

    if actual_checksum != expected_checksum:
        raise ValueError(
            f"\nChecksum mismatch!\n"
            f"Expected: {expected_checksum}\n"
            f"Got:      {actual_checksum}\n"
        )

    print("[OK] Checksum verified successfully.")
    return True

