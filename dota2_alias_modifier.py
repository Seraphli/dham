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
import logging
from pathlib import Path
from utils import (
    verify_file_before_extraction,
    download_file,
    get_latest_github_release_asset,
)

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
        finally:
            # Clean up temp directory
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            input("Press Enter to exit...")  # Keep the console open until user input

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
            vrf_url = get_latest_github_release_asset(
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
                download_file(vrf_url, vrf_zip_path)

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
            if not verify_file_before_extraction(vrf_zip_path):
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
            vpkedit_url = get_latest_github_release_asset(
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
                download_file(vpkedit_url, vpkedit_zip_path)

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
            if not verify_file_before_extraction(vpkedit_zip_path):
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
        extracted_file = extract_dir / target_file

        cmd = [
            str(self.vrf_exe_path),
            "-i",
            str(vpk_path),
            "-o",
            str(extract_dir),
            "-f",
            target_file,
        ]

        logger.info(f"Attempting extraction with command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        # Collect output for debugging
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        # Check if command succeeded and file exists
        if result.returncode == 0 and (extracted_file.exists() or stdout):
            # If the file exists directly, we're successful
            if extracted_file.exists():
                logger.info(
                    f"✅ Successfully extracted npc_heroes.txt to {extracted_file}"
                )
                return extracted_file

        raise RuntimeError(
            f"Failed to extract npc_heroes.txt from VPK. Command output: {stdout}\nError: {stderr}"
        )

    def extract_hero_section(self, lines, hero_name):
        """
        Locate hero section in lines by finding the line matching ^\t"npc_dota_hero_{hero_name}" and
        the first following line matching ^\t} as the closing of this section.
        Returns (start_idx, end_idx) inclusive, or (None, None) if not found.
        """
        start_pattern = re.compile(rf'^\t"npc_dota_hero_{re.escape(hero_name)}"')
        end_pattern = re.compile(r"^\t\}")
        start_idx = None
        # find start
        for i, line in enumerate(lines):
            if start_pattern.match(line):
                start_idx = i
                break
        if start_idx is None:
            if self.verbose:
                logger.debug(f"Hero '{hero_name}' start line not found.")
            return None, None

        # find end
        end_idx = None
        for i in range(start_idx + 1, len(lines)):
            if end_pattern.match(lines[i]):
                end_idx = i
                break
        if end_idx is None:
            if self.verbose:
                logger.debug(f"Hero '{hero_name}' closing brace not found.")
            return start_idx, None

        return start_idx, end_idx

    def modify_aliases(self):
        """Read npc_heroes.txt, update NameAliases for each hero, and write back."""
        npc_path = self.temp_dir / "extract" / "scripts" / "npc" / "npc_heroes.txt"
        # Load lines
        with open(npc_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for hero_name, aliases in self.config.items():
            if hero_name == "path":
                continue
            if self.verbose:
                logger.info(f"Processing hero: {hero_name}")

            # Find section boundaries in current lines
            start, end = self.extract_hero_section(lines, hero_name)
            if start is None or end is None:
                logger.warning(
                    f"Skipping {hero_name}: section not found or incomplete."
                )
                continue

            # Search for existing NameAliases within section
            alias_pattern = re.compile(r'^\t\t"NameAliases"\s+"([^"]*)"')
            alias_idx = None
            existing_aliases = []
            alias_found = 0
            for i in range(start, end + 1):
                m = alias_pattern.match(lines[i])
                if m:
                    alias_found += 1
                    alias_idx = i
                    existing_aliases.extend(
                        [a.strip() for a in re.split(r"[;,]", m.group(1)) if a.strip()]
                    )
                    if self.verbose:
                        logger.debug(
                            f"Found existing aliases for {hero_name}: {existing_aliases}"
                        )
            if alias_found > 1:
                logger.warning(
                    f"⚠️ Warning: Multiple NameAliases found for {hero_name}."
                )

            # Build merged alias list
            merged = existing_aliases.copy()
            for alias in aliases:
                val = alias.strip()
                if val and val.lower() not in [a.lower() for a in merged]:
                    merged.append(val)
                    if self.verbose:
                        logger.info(f"Added alias '{val}' for {hero_name}")
                else:
                    if self.verbose:
                        logger.info(f"Skipped alias '{val}' for {hero_name}")

            new_alias_str = ",".join(merged)

            # Prepare new NameAliases line with proper indent
            if alias_idx is not None:
                indent = "\t\t"
                lines[alias_idx] = f'{indent}"NameAliases"\t"{new_alias_str}"\n'
                if self.verbose:
                    logger.debug(f"Replaced alias line at {alias_idx} for {hero_name}")
            else:
                # insert before closing brace
                indent = "\t\t"
                insert_idx = end
                lines.insert(insert_idx, f'{indent}"NameAliases"\t"{new_alias_str}"\n')
                if self.verbose:
                    logger.debug(f"Inserted alias line at {insert_idx} for {hero_name}")

        # Write back updated lines
        with open(npc_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        logger.info("✅ Hero aliases successfully modified.")

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
