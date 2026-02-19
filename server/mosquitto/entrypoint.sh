#!/bin/sh
# Initialize Dynamic Security plugin JSON if it doesn't exist.
# Creates the admin user that Django uses to provision clients/roles.

DYNSEC_FILE="/mosquitto/data/dynamic-security.json"

if [ ! -f "$DYNSEC_FILE" ]; then
    echo "Initializing Dynamic Security plugin..."
    mosquitto_ctrl dynsec init "$DYNSEC_FILE" "$MOSQUITTO_DYNSEC_USERNAME" "$MOSQUITTO_DYNSEC_PASSWORD"
    chown mosquitto:mosquitto "$DYNSEC_FILE"
    echo "Dynamic Security initialized with admin user: $MOSQUITTO_DYNSEC_USERNAME"
fi

exec mosquitto -c /mosquitto/config/mosquitto.conf
