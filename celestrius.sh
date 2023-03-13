#!/bin/bash

set -e

CEL_DIR=$(realpath $(dirname "$0"))

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

welcome
ensure_deps

report_status "Making sure all dependencies are properly installed..."
