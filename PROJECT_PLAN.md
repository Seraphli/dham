# Dota2 Hero Alias Modifier: Implementation Plan

## 1. Project Overview and Goals

The Dota2 Hero Alias Modifier is a Python application designed to enhance the Dota 2 gameplay experience by enabling users to create custom aliases for hero selection. This application allows players to define their own shorthand names or alternative names for heroes, which can significantly improve the hero selection process during the draft phase.

### Primary Goals

1. **Accessibility**: Make hero selection faster and more intuitive by allowing users to define custom aliases in any language or notation system.
2. **Ease of Use**: Create a straightforward, user-friendly system for configuring and applying hero aliases.
3. **Non-Invasive Modification**: Implement changes in a way that doesn't interfere with game updates or risk VAC bans.
4. **Automation**: Minimize manual steps required by the user to apply their custom aliases.

## 2. Step-by-Step Implementation Process

### 2.1 Downloading Required CLI Tools

#### ValveResourceFormat (VRF)

1. Check if the ValveResourceFormat tool is already installed in the `tools/vrf` directory.
2. Look for multiple possible executables in order of preference: `Source2Viewer-CLI.exe`, `VRF.exe`
3. If not present:
   - Use the GitHub API to fetch metadata for the latest release from ValveResourceFormat/ValveResourceFormat
   - Download the latest release of the CLI tool for Windows
   - Implement retry mechanism with exponential backoff for reliable downloads
   - Validate the downloaded zip file before extraction (check signature, file size, content)
   - Extract the contents to the `tools/vrf` directory.
   - Perform flexible executable detection to handle naming variations in different releases
   - Verify that a suitable executable is found and usable

#### VPKEdit

1. Check if VPKEdit is already installed in the `tools/vpkedit` directory.
2. If not present:
   - Use the GitHub API to fetch metadata for the latest release from craftablescience/VPKEdit
   - Download the latest release of windows-cli-portable.zip from GitHub
   - Implement retry mechanism with exponential backoff for reliable downloads
   - Validate the downloaded zip file before extraction
   - Extract the contents to the `tools/vpkedit` directory.
   - Verify that `VPKEdit-cli.exe` or an alternative CLI executable is present

### 2.2 Finding Dota 2 Installation Path

1. Check the Windows registry at `SOFTWARE\WOW6432Node\Valve\Steam` for the Steam installation path.
2. Look for Dota 2 in common Steam library locations:
   - `[SteamPath]/steamapps/common/dota 2 beta`
   - `[SteamPath]/SteamApps/common/dota 2 beta`
3. Parse the Steam libraryfolders.vdf file to identify additional library locations.
4. Check each potential path to verify it contains the Dota 2 game directory.
5. If automatic detection fails, prompt the user to provide the path manually or through command-line arguments.

### 2.3 Extracting npc_heroes.txt from VPK

1. Identify the source VPK file at `[DotaPath]/game/dota/pak01_dir.vpk`.
2. Create a temporary directory to store extracted files.
3. Use ValveResourceFormat (Source2Viewer-CLI.exe or VRF.exe) to extract `scripts/npc/npc_heroes.txt` from the VPK.
4. Try multiple command-line formats to handle different VRF tool versions:
   ```
   # For Source2Viewer-CLI.exe
   Source2Viewer-CLI.exe -i [VPKPath] -o [ExtractDir] -f scripts/npc/npc_heroes.txt
   
   # For VRF.exe
   VRF.exe -i [VPKPath] -o [ExtractDir] -e scripts/npc/npc_heroes.txt
   ```
5. Implement fallback strategies if extraction fails:
   - Try alternative command formats
   - Try full extraction as a last resort
   - Search for the file in different possible locations after extraction
6. Verify that the file was extracted successfully to `[ExtractDir]/scripts/npc/npc_heroes.txt`.

### 2.4 Modifying Hero Aliases Based on Config File

1. Parse the alias configuration file (`alias.yaml`) to load hero-to-aliases mappings.
2. Create a backup of the original `npc_heroes.txt` file.
3. For each hero defined in the configuration:
   - Find the hero section in `npc_heroes.txt` (handling potential naming variations).
   - Check if the hero already has a `NameAliases` property:
     - If yes: Append new aliases to the existing ones.
     - If no: Add a new `NameAliases` property with the specified aliases.
4. Save the modified `npc_heroes.txt` file.

### 2.5 Creating a New VPK with Modified Files

1. Create a directory structure matching the original VPK structure:
   ```
   [TempDir]/vpk_content/scripts/npc/
   ```
2. Copy the modified `npc_heroes.txt` to this directory structure.
3. Use VPKEdit to create a new VPK file with proper Valve format (including both directory and content files):
   ```
   # Try multiple formats to ensure proper creation of both _dir.vpk and _000.vpk files
   VPKEdit-cli.exe --output [OutputBase] --format valve [ContentDir]
   ```
4. Try multiple command formats with different options if the first attempt fails:
   - Try with `--split` option
   - Try with `--max-size` option
   - Try with `--version 2` option
   - Fall back to default command if needed
5. Implement post-processing if necessary to ensure both directory (_dir.vpk) and content (_000.vpk) files are created
6. Verify that both VPK components were created successfully

### 2.6 Placing the VPK in the Correct Game Directory

1. Determine the target directory based on the language path specified in the configuration:
   ```
   [DotaPath]/game/[LanguagePath]
   ```
   For example: `[DotaPath]/game/dota_lv` for Latvian.
2. Create the target directory if it doesn't exist.
3. Check if VPK files already exist at the target location:
   - If yes: Create backups of the existing files.
4. Copy all newly created VPK files (both _dir.vpk and content files like _000.vpk) to the target location.
5. Verify that all files were copied successfully.

## 3. File Structure and Components

```
dota2-hero-alias-modifier/
│
├── dota2_alias_modifier.py     # Main application script
├── alias.yaml                  # User configuration file
├── requirements.txt            # Python dependencies
├── README.md                   # Documentation
├── PROJECT_PLAN.md             # This implementation plan
│
└── tools/                      # Directory for external tools
    ├── vrf/                    # ValveResourceFormat files
    │   ├── Source2Viewer-CLI.exe  # Primary VRF executable
    │   ├── libSkiaSharp.dll    # VRF dependencies
    │   └── TinyEXR.Native.dll  # VRF dependencies
    │
    └── vpkedit/                # VPKEdit files
        ├── VPKEdit-cli.exe     # VPKEdit CLI executable
        ├── vpkeditcli.exe      # Alternative name for VPKEdit CLI
        ├── CREDITS.md          # Credits file
        └── LICENSE             # License file
```

### 3.1 Component Descriptions

#### Main Script (`dota2_alias_modifier.py`)
This is the core of the application, containing the `Dota2AliasModifier` class that orchestrates the entire process. It handles tool preparation, file extraction, modification, and packaging.

#### Configuration File (`alias.yaml`)
A YAML file containing user-defined hero aliases. It includes:
- `path`: Target language directory (e.g., `dota_lv`)
- Hero mappings: Internal hero names mapped to lists of aliases

#### External Tools
- **ValveResourceFormat**: Used to extract files from Dota 2's VPK archives
- **VPKEdit**: Used to create new VPK archives with modified files

## 4. Error Handling Considerations

### 4.1 File Access Errors

- Handle cases where files cannot be read or written due to permission issues
- Create appropriate backup files before making modifications
- Implement proper cleanup of temporary files, especially after errors
- Handle file validation failures with detailed error reporting

### 4.2 Tool Execution Errors

- Handle cases where external tools (Source2Viewer-CLI, VPKEdit) fail to execute
- Try multiple command formats to accommodate different tool versions
- Implement fallback strategies when the preferred command format fails
- Provide meaningful error messages with suggestions for resolution
- Capture and display tool output for debugging purposes

### 4.3 Dota 2 Path Detection Failures

- Implement multiple detection strategies (registry keys, Steam library folders)
- Parse Steam's libraryfolders.vdf to find additional installation locations
- Provide clear instructions for manual path specification
- Support both command-line arguments and environment variables for path specification

### 4.4 Configuration Errors

- Validate the configuration file structure
- Check for required keys (`path`)
- Verify that hero names exist in the Dota 2 files
- Handle different formats of hero names in the game files
- Provide meaningful error messages for configuration issues

### 4.5 Network and Download Errors

- Use GitHub API to reliably fetch the latest tool releases
- Handle download failures with intelligent retries and exponential backoff
- Support resuming interrupted downloads where possible
- Validate downloaded files before extraction (file size, zip integrity, content)
- Implement multiple fallback strategies for file download and extraction
- Display detailed progress information during downloads using tqdm
- Save API responses for debugging purposes

## 5. Testing Plan

### 5.1 Component Testing

1. **Configuration Parsing**:
   - Test parsing valid YAML files
   - Test handling of malformed YAML files
   - Test handling of missing required keys
   - Test handling of empty alias lists

2. **Tool Management**:
   - Test detection of existing tools
   - Test downloading and extraction of tools
   - Test handling of download failures

3. **Dota 2 Path Detection**:
   - Test registry-based detection
   - Test handling of multiple Steam libraries
   - Test handling of manual path specification

4. **File Extraction**:
   - Test extraction of files from VPK
   - Test handling of extraction failures

5. **Hero Alias Modification**:
   - Test adding aliases to heroes without existing aliases
   - Test adding aliases to heroes with existing aliases
   - Test handling of heroes not found in the file

6. **VPK Creation**:
   - Test creation of new VPK files
   - Test handling of VPK creation failures

7. **VPK Placement**:
   - Test creating destination directories
   - Test handling of existing VPK files
   - Test backup creation

### 5.2 End-to-End Testing

1. **Basic Functionality**:
   - Test the complete workflow with a simple configuration
   - Verify that aliases are correctly applied in-game

2. **Edge Cases**:
   - Test with a large number of heroes and aliases
   - Test with non-ASCII characters in aliases
   - Test with heroes that have special formatting in npc_heroes.txt

3. **Error Recovery**:
   - Test recovery from interruptions during various stages
   - Verify that temporary files are properly cleaned up

### 5.3 Manual Testing Checklist

- [ ] Run the script with default configuration
- [ ] Run the script with custom configuration file path
- [ ] Run the script with manual Dota 2 path specification
- [ ] Verify that aliases work in-game for all configured heroes
- [ ] Verify that existing aliases are preserved
- [ ] Test installation with Steam running
- [ ] Test installation with Dota 2 running

## 6. Additional Considerations

### 6.1 Performance Optimization

- Minimize file operations by using efficient I/O patterns
- Use exponential backoff for retries to avoid overwhelming remote servers
- Implement proper progress reporting for long-running operations using tqdm
- Optimize download procedures with proper chunking and buffer sizes
- Support resuming interrupted downloads to avoid unnecessary re-downloads

### 6.2 Future Enhancements

- Support for additional localization paths
- GUI interface for configuration management
- Support for backing up and restoring configurations
- Support for sharing configurations between users

### 6.3 Distribution Considerations

- Package the application as a standalone executable
- Consider creating an installation wizard
- Implement update checking for new versions

## 7. Implementation Details

### 7.1 GitHub API Integration

- Use the GitHub API to fetch metadata for the latest releases of required tools
- Parse API responses to find the correct asset download URLs
- Handle both exact and partial matching for asset names to accommodate changes in naming conventions
- Save API responses to debug directory for troubleshooting
- Implement robust error handling for API calls

### 7.2 File Download and Validation

- Implement sophisticated download mechanism with resume capability
- Use proper HTTP headers for efficient downloads (Range headers, redirects)
- Validate downloaded files using multiple methods:
  - Check file size against expected size
  - Verify ZIP file signatures and headers
  - Test ZIP integrity using built-in testing functions
  - Check for expected content within ZIP files

### 7.3 VPK Creation and Structure

- Create VPK files that match Valve's format requirements:
  - Directory file (_dir.vpk) containing file index and headers
  - Content files (_000.vpk, etc.) containing actual file data
- Implement multiple strategies to ensure proper VPK creation
- Handle various VPKEdit command formats and options
- Implement post-processing if needed to create proper file structure

## 8. Conclusion

This implementation plan provides a comprehensive roadmap for developing the Dota2 Hero Alias Modifier application. The plan reflects the actual implementation with all improvements and fixes made throughout the development process, including GitHub API integration, working with the new Source2Viewer-CLI.exe, and creating proper VPK files with both directory and content components. By following this structured approach, the development process results in a robust and user-friendly tool that enhances the Dota 2 experience for players.