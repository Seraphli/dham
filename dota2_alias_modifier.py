#!/usr/bin/env python3
"""
Dota2 Hero Alias Modifier
-------------------------
This script modifies Dota 2 hero aliases based on a configuration file (alias.yaml)
and packages the changes into a VPK file to be placed in the game directory.
"""

import os
import sys
import yaml
import subprocess
import re
import zipfile
import shutil
import tempfile
import winreg
import requests
import time
import json
import logging
from pathlib import Path
from tqdm import tqdm

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
logger = logging.getLogger(__name__)


class Dota2AliasModifier:
    def __init__(self, config_path="alias.yaml", verbose=False):
        self.config_path = config_path
        self.tools_dir = Path("tools")
        self.temp_dir = Path(tempfile.mkdtemp())
        self.vrf_path = self.tools_dir / "vrf"
        self.vpkedit_path = self.tools_dir / "vpkedit"
        self.dota_path = None
        self.config = None
        self.verbose = verbose

        # Set logging level based on verbose flag
        if self.verbose:
            logger.setLevel(logging.DEBUG)
        else:
            logger.setLevel(logging.INFO)

        # Create tools directory if it doesn't exist
        self.tools_dir.mkdir(exist_ok=True)

    def run(self):
        """Main execution method"""
        try:
            logger.info("Starting Dota2 Hero Alias Modifier")

            # Load the configuration
            self.load_config()

            # Ensure all required tools are available
            self.prepare_tools()

            # Find the Dota 2 installation path
            self.find_dota_path()

            # Extract the npc_heroes.txt file
            self.extract_npc_heroes()

            # Modify the hero aliases
            self.modify_aliases()

            # Create a new VPK file
            vpk_files = self.create_vpk()

            # Store the created VPK files
            self._vpk_files = vpk_files

            # Place the VPK file in the appropriate game directory
            self.place_vpk()

            logger.info("✅ All done! Hero aliases have been successfully modified.")
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            sys.exit(1)
        finally:
            # Clean up temp directory
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def load_config(self):
        """Load the alias configuration file"""
        try:
            logger.info(f"Loading configuration from {self.config_path}")
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f)

            if not self.config:
                raise ValueError("Configuration file is empty")

            if "path" not in self.config:
                raise ValueError("Configuration file is missing 'path' key")

            logger.info(
                f"✅ Configuration loaded successfully (target path: {self.config['path']})"
            )
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Configuration file '{self.config_path}' not found"
            )
        except yaml.YAMLError:
            raise ValueError(
                f"Error parsing the YAML configuration file: {self.config_path}"
            )

    def prepare_tools(self):
        """Download and prepare all required tools"""
        logger.info("Preparing required tools...")
        self.prepare_vrf()
        self.prepare_vpkedit()
        logger.info("✅ All required tools are ready")

    def _retry_with_backoff(self, func, max_retries=3, initial_delay=1):
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
                    logger.debug(
                        f"Attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {wait_time} seconds..."
                    )
                    time.sleep(wait_time)
                else:
                    logger.debug(f"All {max_retries} attempts failed.")
                    break

        # If we get here, all retries failed
        raise last_exception

    def _get_latest_github_release_asset(self, repo_owner, repo_name, asset_pattern):
        """
        Fetch the latest release info from GitHub API and find the specified asset

        Args:
            repo_owner: GitHub repository owner (e.g., 'ValveResourceFormat')
            repo_name: GitHub repository name (e.g., 'ValveResourceFormat')
            asset_pattern: Pattern to match the desired asset name (e.g., 'cli-windows-x64.zip')

        Returns:
            URL of the matching asset from the latest release
        """
        api_url = (
            f"https://api.github.com/repos/{repo_owner}/{repo_name}/releases/latest"
        )

        # Set proper headers for GitHub API
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Dota2-Alias-Modifier-Script",
        }

        print(f"Fetching latest release info from GitHub API: {api_url}")
        print(
            f"Looking for asset matching pattern: '{asset_pattern}' (case-insensitive)"
        )

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
            release_data = self._retry_with_backoff(fetch_release_info)
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
                        asset["name"]
                        .lower()
                        .replace("-", " ")
                        .replace("_", " ")
                        .split()
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

    def prepare_vrf(self):
        """Download and prepare ValveResourceFormat (VRF) if needed"""
        # Define possible executable names in order of preference
        vrf_exe_names = ["VRF.exe", "Source2Viewer-CLI.exe"]

        # Store the actual executable path once found
        self.vrf_exe_path = None

        # Check if any of the known executable names already exist
        for exe_name in vrf_exe_names:
            # Check both directly in vrf_path and in possible subdirectories
            possible_paths = [
                self.vrf_path / exe_name,
                self.vrf_path / "ValveResourceFormat" / exe_name,
            ]

            for path in possible_paths:
                if path.exists():
                    self.vrf_exe_path = path
                    print(f"✅ VRF is already installed at {path}")
                    return

        # If we get here, need to download and install VRF
        print("Downloading ValveResourceFormat...")

        try:
            # Get the latest release URL from GitHub API
            vrf_url = self._get_latest_github_release_asset(
                repo_owner="ValveResourceFormat",
                repo_name="ValveResourceFormat",
                asset_pattern="cli-windows-x64.zip",  # Lowercase version of the asset name
            )
            print(f"Download URL: {vrf_url}")
        except Exception as e:
            raise RuntimeError(f"Failed to get ValveResourceFormat download URL: {e}")

        vrf_zip_path = self.tools_dir / "vrf.zip"

        # Remove any existing zip file to ensure a clean download
        if vrf_zip_path.exists():
            print("Removing existing vrf.zip file...")
            vrf_zip_path.unlink()

        # Try to download the file with retries
        max_retries = 5  # Increased retry count
        for attempt in range(max_retries):
            try:
                print(f"Download attempt {attempt + 1}/{max_retries}...")
                self._download_file(vrf_url, vrf_zip_path)

                # Validate the downloaded file is a valid zip
                if not self._is_valid_zip(vrf_zip_path):
                    if attempt < max_retries - 1:
                        print(
                            "Downloaded file is not a valid zip. Waiting before retrying..."
                        )
                        time.sleep(3)  # Add a delay between attempts
                        continue
                    else:
                        raise ValueError(
                            "Downloaded file is not a valid zip file after multiple attempts"
                        )
                break
            except (requests.RequestException, IOError) as e:
                if attempt < max_retries - 1:
                    wait_time = 5 * (attempt + 1)  # Progressive backoff
                    print(f"Download failed: {e}. Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    raise RuntimeError(
                        f"Failed to download ValveResourceFormat after {max_retries} attempts: {e}"
                    )

        print("Extracting ValveResourceFormat...")
        self.vrf_path.mkdir(exist_ok=True)
        try:
            # Verify file integrity before extraction
            if not self._verify_file_before_extraction(vrf_zip_path):
                raise ValueError("ZIP file verification failed before extraction")

            # Print zip file info for debugging
            with zipfile.ZipFile(vrf_zip_path, "r") as zip_ref:
                file_list = zip_ref.namelist()
                print(f"ZIP file contains {len(file_list)} files.")
                print(
                    f"Top-level entries: {[name for name in file_list if '/' not in name or name.count('/') == 1][:5]}..."
                )

                # Extract all files to a temporary directory first
                temp_extract_dir = self.temp_dir / "vrf_extract"
                temp_extract_dir.mkdir(exist_ok=True)
                print(f"Extracting to temporary directory: {temp_extract_dir}")
                zip_ref.extractall(temp_extract_dir)

                # Verify extraction was successful
                extracted_files = list(temp_extract_dir.glob("**/*"))
                print(
                    f"Successfully extracted {len(extracted_files)} files/directories"
                )

                # Move files to final destination
                for item in temp_extract_dir.iterdir():
                    target_path = self.vrf_path / item.name
                    # Remove target if it exists
                    if target_path.exists():
                        if target_path.is_dir():
                            shutil.rmtree(target_path)
                        else:
                            target_path.unlink()
                    # Move from temp to final location
                    shutil.move(str(item), str(self.vrf_path))

            # Delete the zip file after successful extraction
            if vrf_zip_path.exists():
                vrf_zip_path.unlink()

            # Search for the executable with a more flexible approach
            exes = list(self.vrf_path.glob("**/*.exe"))
            if exes:
                print(f"Found these executables instead: {[exe.name for exe in exes]}")

                # First, look for exact matches with our known executable names
                for exe_name in vrf_exe_names:
                    for exe in exes:
                        if exe.name.lower() == exe_name.lower():
                            self.vrf_exe_path = exe
                            print(f"Using exact match: {exe.name} as VRF executable")
                            break
                    if self.vrf_exe_path:
                        break

                # If no exact match, try partial matches
                if not self.vrf_exe_path:
                    for exe in exes:
                        # Check for likely VRF-related executables
                        name_lower = exe.name.lower()
                        if any(
                            term in name_lower
                            for term in [
                                "vrf",
                                "valve",
                                "resource",
                                "source2",
                                "viewer",
                            ]
                        ):
                            self.vrf_exe_path = exe
                            print(f"Using partial match: {exe.name} as VRF executable")
                            break

                # If still no match, just use the first executable
                if not self.vrf_exe_path and exes:
                    self.vrf_exe_path = exes[0]
                    print(f"Using fallback: {self.vrf_exe_path.name} as VRF executable")

            if not self.vrf_exe_path or not self.vrf_exe_path.exists():
                raise FileNotFoundError(
                    "No suitable executable found in the VRF package"
                )

            print(f"✅ VRF installed successfully (using {self.vrf_exe_path.name})")
        except zipfile.BadZipFile:
            raise ValueError("The downloaded file is not a valid zip archive")

    def prepare_vpkedit(self):
        """Download and prepare VPKEdit if needed"""
        vpkedit_exe = self.vpkedit_path / "VPKEdit-cli.exe"

        if vpkedit_exe.exists():
            print("✅ VPKEdit is already installed")
            return

        print("Downloading VPKEdit...")

        try:
            # Get the latest release URL from GitHub API
            vpkedit_url = self._get_latest_github_release_asset(
                repo_owner="craftablescience",
                repo_name="VPKEdit",
                asset_pattern="windows-cli-portable.zip",
            )
            print(f"Download URL: {vpkedit_url}")
        except Exception as e:
            raise RuntimeError(f"Failed to get VPKEdit download URL: {e}")

        vpkedit_zip_path = self.tools_dir / "vpkedit.zip"

        # Remove any existing zip file to ensure a clean download
        if vpkedit_zip_path.exists():
            print("Removing existing vpkedit.zip file...")
            vpkedit_zip_path.unlink()

        # Try to download the file with retries
        max_retries = 5  # Increased retry count
        for attempt in range(max_retries):
            try:
                print(f"Download attempt {attempt + 1}/{max_retries}...")
                self._download_file(vpkedit_url, vpkedit_zip_path)

                # Validate the downloaded file is a valid zip
                if not self._is_valid_zip(vpkedit_zip_path):
                    if attempt < max_retries - 1:
                        print(
                            "Downloaded file is not a valid zip. Waiting before retrying..."
                        )
                        time.sleep(3)  # Add a delay between attempts
                        continue
                    else:
                        raise ValueError(
                            "Downloaded file is not a valid zip file after multiple attempts"
                        )
                break
            except (requests.RequestException, IOError) as e:
                if attempt < max_retries - 1:
                    wait_time = 5 * (attempt + 1)  # Progressive backoff
                    print(f"Download failed: {e}. Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    raise RuntimeError(
                        f"Failed to download VPKEdit after {max_retries} attempts: {e}"
                    )

        print("Extracting VPKEdit...")
        self.vpkedit_path.mkdir(exist_ok=True)
        try:
            # Verify file integrity before extraction
            if not self._verify_file_before_extraction(vpkedit_zip_path):
                raise ValueError("ZIP file verification failed before extraction")

            # Print zip file info for debugging
            with zipfile.ZipFile(vpkedit_zip_path, "r") as zip_ref:
                file_list = zip_ref.namelist()
                print(f"ZIP file contains {len(file_list)} files.")
                print(
                    f"Top-level entries: {[name for name in file_list if '/' not in name or name.count('/') == 1][:5]}..."
                )

                # Extract all files to a temporary directory first
                temp_extract_dir = self.temp_dir / "vpkedit_extract"
                temp_extract_dir.mkdir(exist_ok=True)
                print(f"Extracting to temporary directory: {temp_extract_dir}")
                zip_ref.extractall(temp_extract_dir)

                # Verify extraction was successful
                extracted_files = list(temp_extract_dir.glob("**/*"))
                print(
                    f"Successfully extracted {len(extracted_files)} files/directories"
                )

                # Move files to final destination
                for item in temp_extract_dir.iterdir():
                    target_path = self.vpkedit_path / item.name
                    # Remove target if it exists
                    if target_path.exists():
                        if target_path.is_dir():
                            shutil.rmtree(target_path)
                        else:
                            target_path.unlink()
                    # Move from temp to final location
                    shutil.move(str(item), str(self.vpkedit_path))

            # Delete the zip file after successful extraction
            if vpkedit_zip_path.exists():
                vpkedit_zip_path.unlink()

            # Verify the executable exists
            if not vpkedit_exe.exists():
                # Search for any executable that might have a different name
                exes = list(self.vpkedit_path.glob("**/*.exe"))
                if exes:
                    print(
                        f"Found these executables instead: {[exe.name for exe in exes]}"
                    )
                    # Attempt to determine the correct executable
                    for exe in exes:
                        if "vpk" in exe.name.lower() and "cli" in exe.name.lower():
                            print(f"Using {exe.name} as VPKEdit executable")
                            # Copy the executable to the expected location if needed
                            if exe.name != "VPKEdit-cli.exe":
                                shutil.copy2(exe, vpkedit_exe)
                            break
                if not vpkedit_exe.exists():
                    raise FileNotFoundError(
                        f"VPKEdit-cli.exe not found at expected location: {vpkedit_exe}"
                    )

            print("✅ VPKEdit installed successfully")
        except zipfile.BadZipFile:
            raise ValueError("The downloaded VPKEdit file is not a valid zip archive")

    def _verify_file_before_extraction(self, file_path):
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
                            print(
                                "Warning: VPKEdit-cli.exe not found in expected format"
                            )
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

    def _is_valid_zip(self, file_path):
        """
        Check if a file is a valid zip archive with more detailed validation

        Returns:
            bool: True if valid zip file, False otherwise
        """
        try:
            # Check if file exists and has content
            if not file_path.exists():
                print(f"Error: Zip file does not exist: {file_path}")
                return False

            if file_path.stat().st_size == 0:
                print(f"Error: Zip file is empty (0 bytes): {file_path}")
                return False

            file_size_mb = file_path.stat().st_size / (1024 * 1024)
            print(f"Validating zip file: {file_path} ({file_size_mb:.2f} MB)")

            # First check the file signature/magic bytes
            with open(file_path, "rb") as f:
                magic_bytes = f.read(4)
                # ZIP signature is 'PK\x03\x04'
                if magic_bytes != b"PK\x03\x04":
                    print("Error: File is not a valid ZIP file (incorrect signature)")
                    return False

            with zipfile.ZipFile(file_path, "r") as zipf:
                # Test if any files in the archive are corrupted
                bad_file = zipf.testzip()
                if bad_file:
                    print(f"Error: Corrupted file found in zip: {bad_file}")
                    return False

                # Check if the zip has any content
                file_list = zipf.namelist()
                if not file_list:
                    print(f"Error: Zip file is empty (no files inside): {file_path}")
                    return False

                # Calculate and print total size of extracted files
                total_size = sum(info.file_size for info in zipf.infolist())
                print(
                    f"Zip validation successful. Contains {len(file_list)} files, "
                    f"total uncompressed size: {total_size / (1024 * 1024):.2f} MB"
                )
                return True

        except zipfile.BadZipFile as e:
            print(f"Error: Invalid zip file format: {e}")
            return False
        except Exception as e:
            print(f"Error validating zip file: {e}")
            return False

    def _download_file(self, url, file_path):
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
                print(
                    "Server doesn't support partial content or file is already complete"
                )
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
                    if (
                        downloaded_bytes < expected_size * 0.99
                    ):  # If less than 99% complete
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
                raise FileNotFoundError(
                    f"Downloaded file does not exist at {file_path}"
                )

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

    def find_dota_path(self):
        """Find the Dota 2 installation path using Steam registry or common locations"""
        logger.info("Looking for Dota 2 installation...")

        # First try to find via Steam registry
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"
            ) as key:
                steam_path = winreg.QueryValueEx(key, "InstallPath")[0]
                steam_path = Path(steam_path)

                # Try common library locations
                potential_paths = [
                    steam_path / "steamapps" / "common" / "dota 2 beta",
                    steam_path / "SteamApps" / "common" / "dota 2 beta",
                ]

                # Check library folders config for additional Steam libraries
                library_config = steam_path / "steamapps" / "libraryfolders.vdf"
                if library_config.exists():
                    with open(library_config, "r", encoding="utf-8") as f:
                        content = f.read()
                        # Extract library paths using regex
                        paths = re.findall(r'"path"\s+"([^"]+)"', content)
                        for path in paths:
                            path = Path(path.replace("\\\\", "\\"))
                            potential_paths.append(
                                path / "steamapps" / "common" / "dota 2 beta"
                            )

                # Check if any potential path exists
                for path in potential_paths:
                    if path.exists() and (path / "game" / "dota").exists():
                        self.dota_path = path
                        break

        except (FileNotFoundError, PermissionError, WindowsError):
            pass

        # If still not found, ask the user for the path
        if not self.dota_path:
            raise FileNotFoundError(
                "Could not automatically find Dota 2 installation path. "
                "Please provide the path manually by setting the DOTA2_PATH environment variable "
                'or running the script with: --dota-path "path/to/dota 2 beta"'
            )

        logger.info(f"✅ Found Dota 2 installation at: {self.dota_path}")

    def extract_npc_heroes(self):
        """Extract npc_heroes.txt from the Dota 2 VPK"""
        logger.info("Extracting npc_heroes.txt from VPK...")

        vpk_path = self.dota_path / "game" / "dota" / "pak01_dir.vpk"
        target_file = "scripts/npc/npc_heroes.txt"
        extract_dir = self.temp_dir / "extract"
        extract_dir.mkdir(exist_ok=True)

        # Make sure we have a valid executable path
        if (
            not hasattr(self, "vrf_exe_path")
            or not self.vrf_exe_path
            or not self.vrf_exe_path.exists()
        ):
            # Fallback: Try to find any suitable executable
            exes = list(self.vrf_path.glob("**/*.exe"))
            if exes:
                self.vrf_exe_path = exes[0]
                logger.info(f"Using fallback executable: {self.vrf_exe_path.name}")
            else:
                raise FileNotFoundError(
                    "No VRF executable found. Please run the script again or install manually."
                )

        logger.info(f"Using VRF executable: {self.vrf_exe_path}")

        # Get the executable name for determining command syntax
        exe_name = self.vrf_exe_path.name.lower()
        extracted_file = extract_dir / target_file
        success = False
        error_messages = []

        # Define the appropriate command based on the tool
        if "source2viewer" in exe_name:
            # Source2Viewer-CLI has specific command format based on its help output
            # It uses -i/--input, -o/--output, and -f/--vpk_filepath
            # First try with long form arguments
            cmd1 = [
                str(self.vrf_exe_path),
                "--input",
                str(vpk_path),
                "--output",
                str(extract_dir),
                "--vpk_filepath",
                target_file,
            ]

            # Alternative with short form arguments
            cmd2 = [
                str(self.vrf_exe_path),
                "-i",
                str(vpk_path),
                "-o",
                str(extract_dir),
                "-f",
                target_file,
            ]

            # Try file list option first with extraction
            cmd3 = [
                str(self.vrf_exe_path),
                "-i",
                str(vpk_path),
                "-o",
                str(extract_dir),
                "-f",
                target_file,
                "-l",  # List files that match filter
            ]

            commands = [cmd2, cmd1, cmd3]
        else:
            # Original VRF.exe format
            cmd1 = [
                str(self.vrf_exe_path),
                "-i",
                str(vpk_path),
                "-o",
                str(extract_dir),
                "-e",
                target_file,
            ]

            cmd2 = [
                str(self.vrf_exe_path),
                "extract",
                "-i",
                str(vpk_path),
                "-o",
                str(extract_dir),
                "-f",
                target_file,
            ]

            commands = [cmd1, cmd2]

        # Try each command until one succeeds
        for i, cmd in enumerate(commands):
            try:
                logger.info(f"Attempting extraction with command: {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

                # Collect output for debugging
                stdout = result.stdout.strip()
                stderr = result.stderr.strip()
                output = f"STDOUT:\n{stdout}\n\nSTDERR:\n{stderr}"

                # Check if command succeeded and file exists
                if result.returncode == 0 and (extracted_file.exists() or stdout):
                    # If the file exists directly, we're successful
                    if extracted_file.exists():
                        success = True
                        logger.info("✅ Command succeeded and file was extracted!")
                        break

                    # If we got output but no file, it might be listing mode
                    # or we need additional steps
                    logger.info(
                        "Command succeeded but file not found directly. Checking output..."
                    )
                    if self.verbose:
                        logger.debug(f"Output: {stdout}")

                    # Check if we need to run a follow-up command to actually extract
                    if "scripts/npc/npc_heroes.txt" in stdout:
                        print("File found in output. Attempting direct extraction...")
                        # Try direct extraction without listing flag
                        if "-l" in cmd:
                            extract_cmd = [c for c in cmd if c != "-l"]
                            print(
                                f"Attempting direct extraction with: {' '.join(extract_cmd)}"
                            )
                            extract_result = subprocess.run(
                                extract_cmd, capture_output=True, text=True
                            )
                            if (
                                extract_result.returncode == 0
                                and extracted_file.exists()
                            ):
                                success = True
                                print("✅ Follow-up extraction successful!")
                                break
                else:
                    error_message = f"Command failed with return code {result.returncode}:\n{output}"
                    error_messages.append(error_message)
                    print("Command failed, trying next format...")
            except subprocess.TimeoutExpired:
                error_messages.append("Command timed out after 60 seconds")
                print("Command timed out, trying next format...")
            except Exception as e:
                error_messages.append(f"Exception during extraction: {str(e)}")
                print(f"Exception: {str(e)}, trying next format...")

        # Check if extraction was successful by verifying file exists
        if success and extracted_file.exists():
            print(f"✅ Successfully extracted npc_heroes.txt to {extracted_file}")
            # Successfully extracted the file
            return extracted_file
        else:
            # Try to find the file with a more flexible approach if extraction commands failed
            potential_files = list(extract_dir.glob("**/npc_heroes.txt"))
            if potential_files:
                print(
                    f"Found potential npc_heroes.txt at alternative location: {potential_files[0]}"
                )
                return potential_files[0]

            # As a last resort, try extracting the entire VPK and then look for our file
            try:
                print("Trying to extract all files from VPK as a last resort...")
                # Choose the most likely command format for full extraction
                if "source2viewer" in exe_name:
                    full_extract_cmd = [
                        str(self.vrf_exe_path),
                        "extract",
                        "-i",
                        str(vpk_path),
                        "-o",
                        str(extract_dir),
                    ]
                else:
                    full_extract_cmd = [
                        str(self.vrf_exe_path),
                        "-i",
                        str(vpk_path),
                        "-o",
                        str(extract_dir),
                    ]

                print(
                    f"Attempting full extraction with command: {' '.join(full_extract_cmd)}"
                )
                result = subprocess.run(
                    full_extract_cmd, capture_output=True, text=True, timeout=300
                )

                # Check if extraction succeeded by looking for our file
                potential_files = list(extract_dir.glob("**/npc_heroes.txt"))
                if potential_files:
                    print(
                        f"Found npc_heroes.txt after full extraction at: {potential_files[0]}"
                    )
                    return potential_files[0]
            except Exception as e:
                error_messages.append(f"Full extraction attempt failed: {str(e)}")

            # If nothing worked, raise an error with detailed error messages
            error_detail = "\n".join(error_messages)
            raise RuntimeError(
                f"Failed to extract {target_file} from VPK. Errors:\n{error_detail}"
            )

    def extract_hero_section(self, content, hero_name):
        """
        Extract a hero section from the content while properly handling nested braces.

        Args:
            content: The entire file content
            hero_name: The name of the hero to extract

        Returns:
            The extracted hero section including all nested structures, or None if not found
        """
        if self.verbose:
            logger.debug(f"Extracting section for hero '{hero_name}'")

        # Find the starting position of the hero section
        hero_pattern = rf'"npc_dota_hero_{re.escape(hero_name)}"'
        match = re.search(hero_pattern, content)

        if not match:
            if self.verbose:
                logger.debug(f"Hero pattern '{hero_pattern}' not found in content")
            return None

        start_pos = match.start()

        # Find the opening brace after the hero name
        opening_brace_pos = content.find("{", start_pos)
        if opening_brace_pos == -1:
            if self.verbose:
                logger.debug(
                    f"Opening brace not found after hero name position {start_pos}"
                )
            return None

        # Check if we have some reasonable distance between hero name and opening brace
        if (
            opening_brace_pos - start_pos > 200
        ):  # If more than 200 chars between name and brace
            if self.verbose:
                logger.debug(
                    f"Warning - Unusually large gap ({opening_brace_pos - start_pos} chars) between hero name and opening brace"
                )

        # Log some context around the hero name for debugging
        if self.verbose:
            name_context = content[
                max(0, start_pos - 20) : min(len(content), start_pos + 50)
            ]
            logger.debug(
                f"Found hero name context: {name_context.strip().replace('\n', ' ')}"
            )

        # Now track nested braces to find the proper closing brace
        brace_count = 1
        pos = opening_brace_pos + 1
        max_length = min(
            100000, len(content) - opening_brace_pos
        )  # Set a reasonable limit to prevent infinite loops

        # Debug counters to track brace matching
        open_braces_found = 1  # We already found the first opening brace
        close_braces_found = 0

        while (
            brace_count > 0
            and pos < len(content)
            and pos - opening_brace_pos < max_length
        ):
            char = content[pos]
            if char == "{":
                brace_count += 1
                open_braces_found += 1
            elif char == "}":
                brace_count -= 1
                close_braces_found += 1

            pos += 1

            # Print progress for very large sections to show we're not stuck
            if self.verbose and pos % 10000 == 0:
                logger.debug(
                    f"Still processing braces at position {pos}, current nesting level: {brace_count}"
                )

        if brace_count != 0:
            if self.verbose:
                logger.debug(
                    f"Unbalanced braces - found {open_braces_found} opening and {close_braces_found} closing braces"
                )

            # Try to recover by finding the closest reasonable end point
            if brace_count > 0:  # We have unclosed braces
                if self.verbose:
                    logger.debug(
                        "Attempting to recover by finding nearest reasonable ending position"
                    )
                # Look for potential ending pattern like multiple closing braces
                recovery_pos = content.find("}}", pos)
                if (
                    recovery_pos != -1 and recovery_pos - pos < 1000
                ):  # Only try recovery if reasonably close
                    pos = recovery_pos + 2  # +2 to include both closing braces
                else:
                    return None  # Can't recover
            else:
                return None

        # Extract the complete hero section including all nested structures
        end_pos = pos
        hero_section = content[start_pos:end_pos]

        # Additional validations on the extracted content
        validation_errors = []

        # Check if the section ends with a closing brace
        if not hero_section.strip().endswith("}"):
            validation_errors.append("Section does not end with closing brace")

        # Check if the section has balanced braces
        if hero_section.count("{") != hero_section.count("}"):
            validation_errors.append(
                f"Unbalanced braces: {hero_section.count('{')} opening vs {hero_section.count('}')} closing"
            )

        # Check if the section is too short (likely truncated)
        if len(hero_section) < 50:
            validation_errors.append(
                f"Section suspiciously short ({len(hero_section)} chars)"
            )

        if validation_errors:
            if self.verbose:
                logger.debug(
                    f"Validation failed for extracted hero section: {', '.join(validation_errors)}"
                )
                # Log more details about the problematic section
                logger.debug(
                    f"Section preview: {hero_section[:100]}...{hero_section[-100:]}"
                )
            return None

        if self.verbose:
            logger.debug(
                f"Successfully extracted hero section of length {len(hero_section)}"
            )
            logger.debug(f"Section starts with: {hero_section[:60]}...")
            logger.debug(f"Section ends with: ...{hero_section[-60:]}")

        # Final verification - check for key elements we expect to find in a hero section
        expected_patterns = [
            '"npc_dota_hero_',  # Hero name reference
            '"BaseClass"',  # Common property in hero definitions
        ]

        missing_patterns = [
            pattern for pattern in expected_patterns if pattern not in hero_section
        ]
        if missing_patterns and self.verbose:
            logger.debug(
                f"Warning - Expected patterns missing from hero section: {missing_patterns}"
            )

        return hero_section

    def modify_aliases(self):
        """Modify the hero aliases in npc_heroes.txt"""
        logger.info("Modifying hero aliases...")
        if self.verbose:
            logger.debug("Starting hero alias modification process")

        # Path to the extracted npc_heroes.txt
        npc_heroes_path = (
            self.temp_dir / "extract" / "scripts" / "npc" / "npc_heroes.txt"
        )

        # Read the file content
        with open(npc_heroes_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Create a backup of the original file
        with open(npc_heroes_path.with_suffix(".txt.bak"), "w", encoding="utf-8") as f:
            f.write(content)

        # Process each hero in the config
        for hero_name, aliases in self.config.items():
            if hero_name == "path":  # Skip the path key
                continue

            logger.info(f"Processing aliases for {hero_name}...")

            # Use the more robust extraction method that handles nested braces
            hero_section = self.extract_hero_section(content, hero_name)

            if not hero_section:
                logger.warning(
                    f"⚠️ Warning: Hero '{hero_name}' not found in npc_heroes.txt or has invalid structure. Skipping..."
                )
                continue

            new_hero_section = hero_section

            # Check if the hero section already has NameAliases
            name_aliases_match = re.search(r'"NameAliases"\s+"([^"]*)"', hero_section)

            # Validate that the hero section contains expected elements
            if not re.search(r'"npc_dota_hero_\w+"', hero_section):
                logger.error(
                    f"Error: Extracted hero section for '{hero_name}' is missing the hero name definition"
                )
                raise ValueError(
                    f"Invalid hero entry detected for '{hero_name}'. This is likely a parsing error that needs to be fixed."
                )

            # Check for unbalanced braces - critical structural issue
            if hero_section.count("{") != hero_section.count("}"):
                logger.error(
                    f"Error: Extracted hero section for '{hero_name}' has unbalanced braces: {hero_section.count('{')} opening and {hero_section.count('}')} closing"
                )
                raise ValueError(
                    f"Structural error in hero entry for '{hero_name}'. This is likely a parsing error that needs to be fixed."
                )

            # Check if hero section has NameAliases field
            if not name_aliases_match:
                if self.verbose:
                    logger.debug(
                        f"No existing NameAliases field found for hero '{hero_name}'. Will create a new one."
                    )
            else:
                if self.verbose:
                    logger.debug(
                        f"Found existing NameAliases: '{name_aliases_match.group(1)}'"
                    )

            if name_aliases_match:
                # Get existing aliases, supporting both space and semicolon separators
                existing_aliases_str = name_aliases_match.group(1)

                # Handle different separator cases
                if ";" in existing_aliases_str:
                    existing_aliases = [
                        a.strip() for a in existing_aliases_str.split(";")
                    ]
                elif " " in existing_aliases_str.strip():
                    existing_aliases = [a.strip() for a in existing_aliases_str.split()]
                else:
                    # Single alias case with no separators
                    existing_aliases = [existing_aliases_str.strip()]

                # Add new aliases
                all_aliases = [
                    a for a in existing_aliases if a.strip()
                ]  # Remove empty entries

                for alias in aliases:
                    # Normalize the alias (strip whitespace and convert to lowercase for comparison)
                    normalized_alias = alias.strip().lower()
                    # Check if the normalized alias already exists (case-insensitive)
                    if not any(
                        existing.strip().lower() == normalized_alias
                        for existing in all_aliases
                    ):
                        all_aliases.append(alias)
                        logger.info(f"    Added alias '{alias}' for {hero_name}")
                    else:
                        logger.info(
                            f"    Skipped alias '{alias}' for {hero_name} (already exists)"
                        )

                # Create new NameAliases string with semicolons, ensuring no empty entries
                new_aliases_str = ";".join(a for a in all_aliases if a.strip())

                # Replace the existing NameAliases
                new_hero_section = re.sub(
                    r'"NameAliases"\s+"([^"]*)"',
                    f'"NameAliases" "{new_aliases_str}"',
                    hero_section,
                )
            else:
                # NameAliases doesn't exist, add it with semicolon separator
                # Ensure no duplicates when creating the initial set of aliases
                unique_aliases = []
                for alias in aliases:
                    normalized_alias = alias.strip().lower()
                    if not any(
                        existing.strip().lower() == normalized_alias
                        for existing in unique_aliases
                    ):
                        unique_aliases.append(alias)
                        logger.info(f"    Added alias '{alias}' for {hero_name}")
                    else:
                        logger.info(
                            f"    Skipped duplicate alias '{alias}' for {hero_name}"
                        )

                aliases_str = ";".join(a for a in unique_aliases if a.strip())

                # Find a good location to insert - after the hero name and before the closing brace
                new_hero_section = re.sub(
                    r'((?:"npc_dota_hero_[^"]*"[\s\S]*?))(}})',
                    f'\\1\t"NameAliases" "{aliases_str}"\n\t\\2',
                    hero_section,
                )

            # Update the content with the modified hero section
            # Use a more careful approach to ensure we're replacing the exact hero section
            if hero_section != new_hero_section:
                if self.verbose:
                    logger.debug("Hero section modified, updating in content")

                # Find the exact position to replace
                hero_pattern = rf'"npc_dota_hero_{re.escape(hero_name)}"'
                match = re.search(hero_pattern, content)

                if match:
                    start_pos = match.start()
                    # Verify we're replacing the correct section by checking for exact match
                    check_section = self.extract_hero_section(content, hero_name)
                    if check_section == hero_section:
                        # Find the end position of the hero section
                        # This is more reliable than using content.replace() which might
                        # replace unrelated text if there are duplicate sections
                        end_pos = start_pos + len(hero_section)

                        # Create new content by replacing just this section
                        content = (
                            content[:start_pos] + new_hero_section + content[end_pos:]
                        )
                        if self.verbose:
                            logger.debug(
                                f"Successfully updated hero section at position {start_pos}"
                            )
                    else:
                        if self.verbose:
                            logger.debug(
                                "Warning - Hero section verification failed, using simple replace"
                            )
                        # Fall back to simple replace as last resort
                        content = content.replace(hero_section, new_hero_section)
                else:
                    if self.verbose:
                        logger.debug(
                            f"Warning - Could not find hero pattern '{hero_pattern}' for replacement"
                        )
                    # Fall back to simple replace
                    content = content.replace(hero_section, new_hero_section)

        # Write the modified content back to the file
        with open(npc_heroes_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info("✅ Hero aliases successfully modified")

    def create_vpk(self):
        """Create a new VPK file with the modified npc_heroes.txt"""
        logger.info("Creating new VPK file...")

        vpk_content_dir = self.temp_dir / "vpk_content"
        vpk_content_dir.mkdir(exist_ok=True)

        # Create directories to match the original structure
        scripts_npc_dir = vpk_content_dir / "scripts" / "npc"
        scripts_npc_dir.mkdir(parents=True, exist_ok=True)

        # Copy the modified file to the VPK content directory
        src_file = self.temp_dir / "extract" / "scripts" / "npc" / "npc_heroes.txt"
        dst_file = scripts_npc_dir / "npc_heroes.txt"
        shutil.copy2(src_file, dst_file)

        # Create the VPK file using VPKEdit
        # First check which executable exists - it could be named VPKEdit-cli.exe or vpkeditcli.exe
        vpkedit_exe = self.vpkedit_path / "VPKEdit-cli.exe"
        vpkeditcli_exe = self.vpkedit_path / "vpkeditcli.exe"

        # Use whichever executable exists
        if vpkeditcli_exe.exists():
            vpkedit_exe = vpkeditcli_exe

        # Create a simple output filename with the full path including the _dir.vpk suffix
        # This ensures we directly create the correct file name instead of using a base name
        output_vpk = self.temp_dir / "pak02_dir.vpk"

        # Simple command to create a single VPK file
        # Using --single-file flag to pack all files into a single VPK file
        cmd = [
            str(vpkedit_exe),
            "--output",
            str(output_vpk),
            "--single-file",  # Pack everything into a single file
            str(vpk_content_dir),
        ]

        logger.info(f"Creating VPK with command: {' '.join(cmd)}")

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            if self.verbose:
                logger.debug(f"Command output: {result.stdout}")

            if output_vpk.exists():
                logger.info(f"✅ Successfully created VPK file: {output_vpk}")
                return [output_vpk]
            else:
                # Check if a file with a similar name was created
                vpk_files = list(self.temp_dir.glob("*.vpk"))
                if vpk_files:
                    logger.info(
                        f"Found VPK files with different names: {[f.name for f in vpk_files]}"
                    )
                    return vpk_files
                else:
                    raise RuntimeError("VPK file was not created successfully")

        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {e.stderr}")
            raise RuntimeError(f"Failed to create VPK file: {e}")

    def place_vpk(self):
        """Place all VPK files in the appropriate game directory"""
        # Determine the target path based on the config
        target_dir = self.dota_path / "game" / self.config["path"]
        target_dir.mkdir(parents=True, exist_ok=True)

        # Get all VPK files created in the temp directory
        vpk_files = (
            self.create_vpk() if not hasattr(self, "_vpk_files") else self._vpk_files
        )

        if isinstance(vpk_files, (list, tuple)):
            source_vpks = vpk_files
        else:
            # If only a single file is returned, wrap it in a list
            source_vpks = [vpk_files]

        # Store the files for potential later use
        self._vpk_files = source_vpks

        logger.info(f"Placing {len(source_vpks)} VPK files in {target_dir}...")

        for source_vpk in source_vpks:
            if not isinstance(source_vpk, Path):
                source_vpk = Path(source_vpk)

            target_vpk = target_dir / source_vpk.name

            logger.info(f"Placing {source_vpk.name} at {target_vpk}...")

            # Check if the target file already exists
            if target_vpk.exists():
                logger.warning(
                    f"⚠️ Warning: {target_vpk} already exists. Creating backup..."
                )
                backup_path = target_vpk.with_suffix(".vpk.bak")
                shutil.copy2(target_vpk, backup_path)
                target_vpk.unlink()

            # Copy the VPK file to the target directory
            shutil.copy2(source_vpk, target_vpk)
            logger.info(f"✅ Successfully placed {source_vpk.name} at {target_vpk}")

        logger.info(f"✅ All VPK files placed successfully in {target_dir}")


def parse_args():
    """Parse command-line arguments"""
    import argparse

    parser = argparse.ArgumentParser(description="Dota2 Hero Alias Modifier")
    parser.add_argument(
        "--config", default="alias.yaml", help="Path to the alias configuration file"
    )
    parser.add_argument("--dota-path", help="Path to the Dota 2 installation directory")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output with detailed debugging information",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    # Set environment variables from arguments
    if args.dota_path:
        os.environ["DOTA2_PATH"] = args.dota_path

    modifier = Dota2AliasModifier(config_path=args.config, verbose=args.verbose)
    modifier.run()
