#!/bin/bash

set -e

cat <<EOF
===========================================================================================

          Terms and Privacy for Celestrius data collection (in layman's terms)


This plugin collect training data for project Celestrius (limited pilot) by the Obico Team:
https://obico.io/blog/celestrius-limited-pilot/

Please read the following carefully to make sure you understand the privacy and terms of
this limited pilot program:

- When ALL of the following conditions are met, the plugin will take snapshots from the
camera you configured below, and send them to a secure server hosted by the Obico Team.

    - You have accepted the terms by checking the box below;
    - The data collection is enabled by running './celestrius.sh enable'. By default the data
      collection is disabled. So don't enable it before you start the test prints for the
      pilot program;
    - Your printer is printing.

- The Obico Team won't access your data until 7 days after they are uploaded. This 7-day period
is the grace period for you to request data withdrawal in case you accidentally send the data
for the prints you don't intend to.

- You will find a list of all data that have been sent to the server at:
'~/celestrius-data/uploaded_print_list.csv'. Please check the list periodically. If you find
any data on the list that you don't intend to send to the Obico Team, please email us at
support@obico.io to request data erasure.

- 7 days after your data is uploaded to the server, the Obico Team will access them and use
them for project Celestrius.

===========================================================================================

EOF
