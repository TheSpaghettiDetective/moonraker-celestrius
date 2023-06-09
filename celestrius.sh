#!/bin/bash

set -e

CEL_DIR=$(realpath $(dirname "$0"))
CEL_CFG_FILE="${CEL_DIR}/moonraker-celestrius.cfg"
CEL_SERVICE_NAME="moonraker-celestrius"

green=$(echo -en "\e[92m")
yellow=$(echo -en "\e[93m")
magenta=$(echo -en "\e[35m")
red=$(echo -en "\e[91m")
cyan=$(echo -en "\e[96m")
default=$(echo -en "\e[39m")

report_status() {
  echo -e "${magenta}###### $*\n${default}"
}

welcome() {
  cat <<EOF
${cyan}
======================================================================================================
###                                                                                                ###
###                               Welcome, Celestrius Pilot!                                       ###
###                                                                                                ###
======================================================================================================
${default}
EOF
}

success() {
  echo -e "\n"
  cat <<EOF
${cyan}
====================================================================================================
###                                                                                              ###
###                                       SUCCESS!!!                                             ###
###                             Celestrius data collection program is ready.                     ###
###                                                                                              ###
====================================================================================================
${default}

NOTE: 
${magenta}
- The data collection is disabled so that you won't accidentally upload unintended data. To enable:

./celestrius.sh enable
${default}
- To disable the data collection, run "./celestrius.sh disable".

- To make changes to the configurations, run "./celestrius.sh install" again.

- To update Celestrius to the latest version, run "./celestrius.sh update".

- To uninstall Celestrius,, run "./celestrius.sh uninstall"

EOF

}

ensure_deps() {
  sudo apt install libgeos-dev
  CEL_ENV="${CEL_DIR}/env"
  if [ ! -f "${CEL_ENV}/bin/activate" ] ; then
    report_status "Creating python virtual environment for moonraker-celestrius..."
    mkdir -p "${CEL_ENV}"
    virtualenv -p /usr/bin/python3 --system-site-packages "${CEL_ENV}"
  fi
  report_status "Making sure all dependencies are properly installed..."
  "${CEL_ENV}"/bin/pip3 install -q -r "${CEL_DIR}"/requirements.txt
}

usage() {
  cat <<EOF
Usage: $0 install   # Install/Re-install and configure/re-configure the Celestrius data collection program, including adding a system service.
       $0 update    # Update Celestrius to the latest version
       $0 enable    # Enable the data collection. Default to be disabled.
       $0 disable   # Disable the data collection.
       $0 uninstall # Show instructions for uninstalling elestrius data collection program
       $0 help      # Show this message
EOF
}

config_incomplete() {
      cat <<EOF
${red}
Incomplete Celstrius configuration. No data will be sent until the Celestrius data collection program is configured properly.
${default}

To rerun the configuration process at a later time, run:

-------------------------------------------------------------------------------------------------
cd ~/moonraker-celestrius
./celestrius.sh install
-------------------------------------------------------------------------------------------------

EOF

exit 1
}

recreate_service() {
  echo ""
  echo ""
  report_status "Creating moonraker-celestrius systemctl service... You may need to enter password to run sudo."

  sudo systemctl stop "${CEL_SERVICE_NAME}" 2>/dev/null || true

  sudo /bin/sh -c "cat > /etc/systemd/system/${CEL_SERVICE_NAME}.service" <<EOF
#Systemd service file for moonraker-celestrius
[Unit]
Description=Celestrius data collection service
After=network-online.target moonraker.service

[Install]
WantedBy=multi-user.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=${CEL_DIR}
ExecStart=${CEL_ENV}/bin/python3 -m moonraker_celestrius.app -c ${CEL_CFG_FILE}
Restart=always
RestartSec=5
EOF

  sudo systemctl enable "${CEL_SERVICE_NAME}"
  sudo systemctl daemon-reload
  report_status "Launching ${CEL_SERVICE_NAME} service..."
  sudo systemctl restart "${CEL_SERVICE_NAME}"
}

uninstall() {
  cat <<EOF

To uninstall Celestrius data collection program, please run:

sudo systemctl stop "${CEL_SERVICE_NAME}"
sudo systemctl disable "${CEL_SERVICE_NAME}"
sudo rm "/etc/systemd/system/${CEL_SERVICE_NAME}.service"
sudo systemctl daemon-reload
sudo systemctl reset-failed
rm -rf ~/moonraker-celestrius

EOF

  exit 0
}

configure() {
  welcome
  ensure_deps

  "${CEL_DIR}/moonraker_celestrius/scripts/terms.sh"
  read -p "Do you understand and accept the terms and the privacy policy [Y/n]: " -e -i "Y" accepted
  if [ "${accepted^^}" != "Y" ] ; then
    config_incomplete
  fi

  if ! PYTHONPATH="${CEL_DIR}:${PYTHONPATH}" ${CEL_ENV}/bin/python3 -m moonraker_celestrius.config -c "${CEL_CFG_FILE}" $@; then
    config_incomplete
  fi

  mkdir -p "${CEL_DIR}/logs"
  recreate_service
  success
}

enable() {
  PYTHONPATH="${CEL_DIR}:${PYTHONPATH}" ${CEL_ENV}/bin/python3 -m moonraker_celestrius.config -c "${CEL_CFG_FILE}" -e
  report_status "Restarting moonraker-celestrius systemctl service... You may need to enter password to run sudo."
  sudo systemctl restart "${CEL_SERVICE_NAME}"
  cat <<EOF
${cyan}
Celestrius data collection enabled!
Snapshots will be collected from configured nozzle camera for all subsequent prints until disabled.
${default}

To disable Celestrius data collection:

-------------------------------------------------------------------------------------------------
cd ~/moonraker-celestrius
./celestrius.sh disable
-------------------------------------------------------------------------------------------------

EOF
}


disable() {
  report_status "Restarting moonraker-celestrius systemctl service... You may need to enter password to run sudo."
  sudo systemctl restart "${CEL_SERVICE_NAME}"
  PYTHONPATH="${CEL_DIR}:${PYTHONPATH}" ${CEL_ENV}/bin/python3 -m moonraker_celestrius.config -c "${CEL_CFG_FILE}" -d
     cat <<EOF
${cyan}
Celestrius data collection disabled!
${default}

To enable Celestrius data collection:

-------------------------------------------------------------------------------------------------
cd ~/moonraker-celestrius
./celestrius.sh enable
-------------------------------------------------------------------------------------------------

EOF
}

case $1 in
  help) usage && exit 0;;
  install) configure;;
  update) git pull && ensure_deps;;
  enable) enable;;
  disable) disable;;
  uninstall) uninstall ;;
  *) usage && exit 1;;
esac
