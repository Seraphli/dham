# Dota2 Hero Alias Modifier

This tool modifies Dota 2 hero aliases based on a configuration file (alias.yaml) and packages the changes into a VPK file to be placed in the game directory.

## IMPORTANT

You need to add `-language $language` to your Dota 2 launch options for the changes to take effect. `$language` should match the `path` specified in your `alias.yaml` file (e.g., `-language schinese` for `dota_schinese` in `alias.yaml`).

## Features

- Automatically downloads required CLI tools if they don't exist:
  - [ValveResourceFormat (VRF)](https://github.com/ValveResourceFormat/ValveResourceFormat/releases) for unpacking VPK files
  - [VPKEdit](https://github.com/craftablescience/VPKEdit/releases) for packing VPK files
- Automatically finds the Dota 2 installation path
- Extracts npc_heroes.txt from the game's VPK files
- Modifies hero aliases based on your configuration
- Creates a new VPK file with the modifications
- Places the VPK file in the appropriate game directory

## Requirements

- Python 3.6 or higher
- Required Python packages (automatically installed if using pip):
  - pyyaml
  - requests
  - tqdm

## Installation

1. Clone or download this repository
2. Install the required packages:

```
pip install -r requirements.txt
```

## Usage

1. Configure your desired hero aliases in `alias.yaml`:

```yaml
path: dota_lv
faceless_void:
  - jbl
  - jb
  - xukongjiamian
crystal_maiden:
  - bingnv
```

2. Run the script:

```
python dota2_alias_modifier.py
```

3. The script will:
   - Download required tools (if needed)
   - Find your Dota 2 installation
   - Extract and modify the hero aliases
   - Create a new VPK file
   - Place it in the appropriate game directory

## Configuration File Format

The `alias.yaml` file should be structured as follows:

```yaml
path: dota_language_path
hero_name:
  - alias1
  - alias2
  - alias3
another_hero:
  - alias1
  - alias2
```

Where:
- `path`: The language-specific folder in the Dota 2 directory (e.g., `dota_lv` for Latvian)
- `hero_name`: The internal name of the hero (as used in the game files)
- Aliases: A list of alternative names you want to use to select this hero

## Command-Line Options

```
usage: dota2_alias_modifier.py [-h] [--config CONFIG] [--dota-path DOTA_PATH]

Dota2 Hero Alias Modifier

optional arguments:
  -h, --help           show this help message and exit
  --config CONFIG      Path to the alias configuration file
  --dota-path DOTA_PATH  Path to the Dota 2 installation directory
```

## Troubleshooting

If the script cannot automatically find your Dota 2 installation, you can specify it manually:

```
python dota2_alias_modifier.py --dota-path "C:\Program Files (x86)\Steam\steamapps\common\dota 2 beta"
```

Or set the `DOTA2_PATH` environment variable.

## How It Works

1. The script downloads the necessary tools (VRF and VPKEdit) if they're not already present
2. It searches for your Dota 2 installation directory
3. Using VRF, it extracts `npc_heroes.txt` from the game files
4. It modifies the hero aliases in the extracted file
5. Using VPKEdit, it creates a new VPK file containing the modified file
6. It places the new VPK in the appropriate game directory based on your configuration