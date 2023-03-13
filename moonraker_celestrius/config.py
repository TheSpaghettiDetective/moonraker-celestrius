import configparser
import os
import argparse

CYAN='\033[0;96m'
RED='\033[0;31m'
NC='\033[0m' # No Color

def configure(config_path):

    # Create a ConfigParser object and read the config file
    config = configparser.ConfigParser()
    if os.path.exists(config_path):
        config.read(config_path)

    if "moonraker" not in config:
        config.add_section("moonraker")

    print(CYAN + "Configuring the server info for your Moonraker server.\n" + NC)
    mr_host = config.get("moonraker", "host", fallback="127.0.0.1")
    mr_host = input(f"Moonraker IP address or hostname (current: {mr_host}): ") or mr_host
    config.set("moonraker", "host", mr_host)

    mr_port = config.get("moonraker", "port", fallback="7125")
    mr_port = input(f"Moonraker port (current: {mr_port}): ") or mr_port
    config.set("moonraker", "port", mr_port)

    if "nozzle_camera" not in config:
        config.add_section("nozzle_camera")

    print(CYAN + """
Configuring the Snapshot URL for the nozzle camera you set up for project Celestrius.
Please note if you have multiple cameras set up, this may NOT be the main camera
you configured for your printer. Be sure to enter the URL for the correct camera.
    """ + NC)

    snapshot_url = config.get("nozzle_camera", "snapshot_url", fallback="")
    snapshot_url = input(f"Nozzle camera snapshot URL (current: {snapshot_url}): ") or snapshot_url
    config.set("nozzle_camera", "snapshot_url", snapshot_url)

    if "celestrius" not in config:
        config.add_section("celestrius")

    print(CYAN + """
Configuring the email you signed up for the Celestrius limited pilot with.
Please make sure the email is correct as this will be used to identify the data
uploaded to the server.
    """ + NC)

    pilot_email = config.get("celestrius", "pilot_email", fallback="")
    pilot_email = input(f"The email you signed up for the pilot program with (current: {pilot_email}): ") or pilot_email
    config.set("celestrius", "pilot_email", pilot_email)

    # Save the updated configuration to the config file
    with open(config_path, "w") as f:
        config.write(f)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-c', '--config', required=True,
        help='Path to config file (cfg)'
    )
    cmd_args = parser.parse_args()
    configure(cmd_args.config)
