#!/bin/bash

set -e

CEL_DIR=$(realpath $(dirname "$0"))
CEL_CFG_FILE="${CEL_DIR}/moonraker-celestrius.cfg"

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

ensure_deps() {
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
       $0 enable    # Enable the data collection. Default to be disabled.
       $0 disable   # Disable the data collection.
       $0 help      # Show this message
EOF
}

config_incomplete() {
      cat <<EOF
${red}
Configruation interrupted! No data will be sent until the Celestrius data collection program is configured properly.
${default}

To rerun the configuration process at a later time, run:

-------------------------------------------------------------------------------------------------
cd moonraker-celestrius
./celestrius.sh install
-------------------------------------------------------------------------------------------------

EOF
}

configure() {
  if ! PYTHONPATH="${CEL_DIR}:${PYTHONPATH}" ${CEL_ENV}/bin/python3 -m moonraker_celestrius.config -c "${CEL_CFG_FILE}"; then
    config_incomplete
  fi
}

welcome
ensure_deps

case $1 in
   help) usage && exit 0;;
   install) configure;;
    *) usage && exit 1;;
esac
