import zipfile
import requests
import re
import shutil
from tqdm import tqdm
import os
import time
from pathlib import Path
import json


def verify_file_before_extraction(file_path):
    """
    Perform a thorough verification of a file before extraction

    Args:
        file_path: Path to the file to verify

    Returns:
        bool: True if the file passes all verification checks, False otherwise
    """
    print(f"Performing thorough verification of: {file_path}")

    # Check if file exists
    if not file_path.exists():
        print(f"Error: File does not exist: {file_path}")
        return False

    # Check if file has content
    file_size = file_path.stat().st_size
    if file_size == 0:
        print(f"Error: File is empty: {file_path}")
        return False

    print(f"File size: {file_size / (1024 * 1024):.2f} MB")

    # For ZIP files, perform additional checks
    if file_path.suffix.lower() in (".zip"):
        try:
            # Check file signature/magic bytes
            with open(file_path, "rb") as f:
                magic_bytes = f.read(4)
                if magic_bytes != b"PK\x03\x04":
                    print("Error: Not a valid ZIP file (incorrect signature)")
                    return False

            # Try to open and verify the ZIP file
            with zipfile.ZipFile(file_path, "r") as zipf:
                # Check for CRC errors or other issues
                result = zipf.testzip()
                if result is not None:
                    print(f"Error: Corrupted file in ZIP: {result}")
                    return False

                # Get and check file list
                file_list = zipf.namelist()
                if not file_list:
                    print("Error: ZIP file is empty (contains no files)")
                    return False

                # Check for common executables that should be present
                if file_path.name == "vrf.zip":
                    exes = [f for f in file_list if f.lower().endswith(".exe")]
                    if not exes:
                        print("Error: No executable files found in VRF zip")
                        return False
                    # Look for known VRF executable names with a more flexible approach
                    known_names = ["vrf.exe", "source2viewer-cli.exe"]
                    vrf_exe = any(
                        any(known.lower() in f.lower() for known in known_names)
                        for f in exes
                    )
                    if not vrf_exe:
                        print(
                            "Warning: Known VRF executables not found in expected format"
                        )
                        print("Found executables: ", [f for f in exes])
                        # Continue anyway as we have fallbacks

                elif file_path.name == "vpkedit.zip":
                    exes = [f for f in file_list if f.lower().endswith(".exe")]
                    if not exes:
                        print("Error: No executable files found in VPKEdit zip")
                        return False
                    vpkedit_exe = any(
                        "vpkedit" in f.lower() and "cli" in f.lower() for f in exes
                    )
                    if not vpkedit_exe:
                        print("Warning: VPKEdit-cli.exe not found in expected format")
                        # Continue anyway as we have fallbacks

                # Calculate total size of files in the archive
                total_size = sum(zipf.getinfo(name).file_size for name in file_list)
                print(
                    f"ZIP contains {len(file_list)} files, total uncompressed size: {total_size / (1024 * 1024):.2f} MB"
                )

                # Success - all checks passed
                print("✅ ZIP file verification successful")
                return True

        except zipfile.BadZipFile as e:
            print(f"Error: Invalid ZIP file format: {e}")
            return False
        except Exception as e:
            print(f"Error during ZIP verification: {e}")
            return False

    # For non-ZIP files or if we get here, assume the file is valid
    print("✅ File verification successful")
    return True


def download_file(url, file_path):
    """
    Download a file with progress bar and resume capability

    This implementation addresses the 'flush of closed file' issue by properly
    managing file resources and ensuring safe flushing before closing files.
    It also adds resume capability for interrupted downloads.
    """
    # Set proper headers to handle redirects and mimic a browser
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml,application/octet-stream",
    }

    print(f"Starting download from: {url}")
    print(f"Saving to: {file_path}")

    # Create parent directories if they don't exist
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Use a temp file for downloading to avoid corruption if the process fails
    temp_file_path = file_path.with_suffix(".part")
    resume_download = False
    downloaded_bytes = 0

    # Check if partial download exists and get its size
    if temp_file_path.exists() and temp_file_path.stat().st_size > 0:
        downloaded_bytes = temp_file_path.stat().st_size
        resume_download = True
        print(
            f"Found partial download ({downloaded_bytes:,} bytes). Attempting to resume..."
        )

    response = None

    try:
        # Initialize response outside the try block to ensure we can close it
        response = None

        # First, make a HEAD request to check content info
        try:
            head_response = requests.head(
                url, headers=headers, allow_redirects=True, timeout=30
            )
            head_response.raise_for_status()

            # Get expected content size from headers
            expected_size = int(head_response.headers.get("content-length", 0))
            content_type = head_response.headers.get("content-type", "unknown")
            print(f"Content-Type: {content_type}")
            print(f"Expected Content-Length: {expected_size:,} bytes")
        except Exception as e:
            print(f"Warning: Failed to get HEAD information: {e}")
            expected_size = 0
            content_type = "unknown"

        # Add Range header if resuming download
        if resume_download:
            headers["Range"] = f"bytes={downloaded_bytes}-"
            print(f"Resuming download from byte position {downloaded_bytes:,}")

        # Now perform the actual download
        response = requests.get(
            url, stream=True, headers=headers, allow_redirects=True, timeout=30
        )

        # Handle 416 Range Not Satisfiable error, which means the file might already be complete
        if response.status_code == 416:
            print("Server doesn't support partial content or file is already complete")
            if (
                temp_file_path.exists()
                and expected_size == temp_file_path.stat().st_size
            ):
                print(f"Partial file is already complete ({expected_size:,} bytes)")
                # Just copy the partial file to the destination
                if file_path.exists():
                    file_path.unlink()
                shutil.copy2(temp_file_path, file_path)
                return True
            else:
                # Start fresh download
                resume_download = False
                downloaded_bytes = 0
                headers.pop("Range", None)
                response = requests.get(
                    url,
                    stream=True,
                    headers=headers,
                    allow_redirects=True,
                    timeout=30,
                )

        response.raise_for_status()

        # Print detailed information about redirects for debugging
        if response.history:
            print(f"Request was redirected {len(response.history)} times:")
            for i, resp in enumerate(response.history):
                print(f"  Redirect {i + 1}: {resp.status_code} - {resp.url}")
            print(f"Final URL: {response.url}")

        # Get content size for progress bar (use expected_size as fallback)
        # If we're resuming a download and got a 206 Partial Content response
        if resume_download and response.status_code == 206:
            content_range = response.headers.get("Content-Range", "")
            match = re.search(r"bytes\s+\d+-\d+/(\d+)", content_range)
            if match:
                total_size = int(match.group(1))
            else:
                total_size = downloaded_bytes + int(
                    response.headers.get("content-length", 0)
                )
            print(f"Server supports resume, total size: {total_size:,} bytes")
        else:
            total_size = int(response.headers.get("content-length", expected_size))
            if resume_download:
                print("Server doesn't support resume. Starting a fresh download.")
                downloaded_bytes = 0  # Reset downloaded bytes counter

        if total_size == 0:
            print("Warning: Content-Length header is missing or zero")

        block_size = 8192  # 8 KB for better performance

        # Open the file in append mode if resuming, otherwise write mode
        file_mode = "ab" if resume_download else "wb"

        # Use closing() from contextlib to ensure proper resource cleanup
        # This fixes the "flush of closed file" issue
        try:
            # Open the file and create the progress bar
            with open(temp_file_path, file_mode) as f:
                with tqdm(
                    desc=file_path.name,
                    initial=downloaded_bytes,
                    total=total_size,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                ) as progress_bar:
                    # Download and write in chunks
                    for data in response.iter_content(block_size):
                        if not data:  # Skip keep-alive chunks
                            continue

                        # Write data and update counters in one block to keep them in sync
                        data_len = len(data)
                        f.write(data)
                        downloaded_bytes += data_len
                        progress_bar.update(data_len)

                        # Periodically flush to disk (every ~1MB)
                        if downloaded_bytes % (1024 * 1024) < block_size:
                            f.flush()

                # Final flush before closing - this is now inside the same with block
                # so the file is still open when we flush
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            print(f"Error during file writing: {e}")
            # Keep the partial download for future resume attempts
            print(f"Partial download saved at {temp_file_path}")
            raise

        # Verify the downloaded file integrity before proceeding
        if expected_size > 0 and downloaded_bytes != expected_size:
            print(
                f"Warning: Downloaded {downloaded_bytes:,} bytes, but expected {expected_size:,} bytes"
            )
            if downloaded_bytes < expected_size:
                print("Download appears incomplete. Consider retrying.")
                # Don't proceed with renaming in case of obviously incomplete file
                if downloaded_bytes < expected_size * 0.99:  # If less than 99% complete
                    return False

        # Only after successful download and verification, rename the temp file
        if temp_file_path.exists():
            if file_path.exists():
                file_path.unlink()
            temp_file_path.rename(file_path)
        else:
            print(f"Error: Temporary file {temp_file_path} does not exist")
            return False

        # Final verification
        if not file_path.exists():
            raise FileNotFoundError(f"Downloaded file does not exist at {file_path}")

        file_size = file_path.stat().st_size
        if file_size == 0:
            raise ValueError(f"Downloaded file is empty (0 bytes): {file_path}")

        print(f"✅ Download completed: {file_path} ({file_size:,} bytes)")
        return True

    except requests.RequestException as e:
        print(f"❌ Download error: {e}")
        # Keep the partial file for potential resume
        if "temp_file_path" in locals() and temp_file_path.exists():
            print(f"Keeping partial download at {temp_file_path} for future resume")
        raise
    except Exception as e:
        print(f"❌ Error during download: {e}")
        # Keep the partial file for potential resume
        if "temp_file_path" in locals() and temp_file_path.exists():
            print(f"Keeping partial download at {temp_file_path} for future resume")
        raise
    finally:
        # Ensure the response is closed to free resources
        if response:
            response.close()


def retry_with_backoff(func, max_retries=3, initial_delay=1):
    """
    Retry a function with exponential backoff

    Args:
        func: Function to retry
        max_retries: Maximum number of retries
        initial_delay: Initial delay in seconds

    Returns:
        The result of the function if successful

    Raises:
        The last exception if all retries fail
    """
    delay = initial_delay
    last_exception = None

    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            last_exception = e
            if attempt < max_retries - 1:
                wait_time = delay * (2**attempt)
                print(
                    f"Attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {wait_time} seconds..."
                )
                time.sleep(wait_time)
            else:
                print(f"All {max_retries} attempts failed.")
                break

    # If we get here, all retries failed
    raise last_exception


def get_latest_github_release_asset(repo_owner, repo_name, asset_pattern):
    """
    Fetch the latest release info from GitHub API and find the specified asset

    Args:
        repo_owner: GitHub repository owner (e.g., 'ValveResourceFormat')
        repo_name: GitHub repository name (e.g., 'ValveResourceFormat')
        asset_pattern: Pattern to match the desired asset name (e.g., 'cli-windows-x64.zip')

    Returns:
        URL of the matching asset from the latest release
    """
    api_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/releases/latest"

    # Set proper headers for GitHub API
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Dota2-Alias-Modifier-Script",
    }

    print(f"Fetching latest release info from GitHub API: {api_url}")
    print(f"Looking for asset matching pattern: '{asset_pattern}' (case-insensitive)")

    def fetch_release_info():
        response = requests.get(api_url, headers=headers, timeout=10)
        response.raise_for_status()

        # Save the raw response for debugging
        debug_dir = Path("debug")
        debug_dir.mkdir(exist_ok=True)
        debug_file = debug_dir / f"{repo_owner}_{repo_name}_latest.json"
        with open(debug_file, "w", encoding="utf-8") as f:
            json.dump(response.json(), f, indent=2)
            print(f"Saved API response to {debug_file} for debugging")

        return response.json()

    # Use the retry mechanism to fetch the release info
    try:
        release_data = retry_with_backoff(fetch_release_info)
        print(
            f"✅ Found latest release: {release_data['tag_name']} ({release_data['name']})"
        )

        # Find the matching asset using case-insensitive matching
        asset_pattern_lower = asset_pattern.lower()
        exact_matches = []
        partial_matches = []

        available_assets = []
        for asset in release_data["assets"]:
            available_assets.append(asset["name"])
            asset_name_lower = asset["name"].lower()

            # Check for exact match (case-insensitive)
            if asset_pattern_lower == asset_name_lower:
                exact_matches.append(asset)
                print(
                    f"Found exact match: {asset['name']} ({asset['browser_download_url']})"
                )
            # Check for partial match (case-insensitive)
            elif asset_pattern_lower in asset_name_lower:
                partial_matches.append(asset)
                print(
                    f"Found partial match: {asset['name']} ({asset['browser_download_url']})"
                )

        # Logic to select the best match
        if exact_matches:
            chosen_asset = exact_matches[0]
            match_type = "exact"
        elif partial_matches:
            chosen_asset = partial_matches[0]
            match_type = "partial"
        else:
            # No match found, try more aggressive fallback matching
            for asset in release_data["assets"]:
                # Split the pattern and asset name into parts and check for key components
                pattern_parts = set(
                    asset_pattern_lower.replace("-", " ").replace("_", " ").split()
                )
                asset_parts = set(
                    asset["name"].lower().replace("-", " ").replace("_", " ").split()
                )

                # If there's significant overlap in the parts
                if len(pattern_parts.intersection(asset_parts)) >= 2:
                    partial_matches.append(asset)
                    print(
                        f"Found fallback match: {asset['name']} ({asset['browser_download_url']})"
                    )

            if partial_matches:
                chosen_asset = partial_matches[0]
                match_type = "fallback"
            else:
                # If we reach here, no matching asset was found
                error_msg = (
                    f"No asset matching '{asset_pattern}' found in latest release of {repo_owner}/{repo_name}. "
                    f"Available assets: {', '.join(available_assets)}"
                )
                print(f"❌ Error: {error_msg}")
                raise ValueError(error_msg)

        # Use the chosen asset
        print(f"✅ Selected asset ({match_type} match): {chosen_asset['name']}")
        return chosen_asset["browser_download_url"]

    except Exception as e:
        raise RuntimeError(f"Failed to fetch release info from GitHub API: {e}")
