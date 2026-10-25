#!/bin/sh
set -e
passwords=/mosquitto/config/passwd
: > "$passwords"
for role in server dashboard device; do
    variable="MQTT_$(echo "$role" | tr a-z A-Z)_PASSWORD"
    eval "secret=\${$variable:?$variable is required}"
    mosquitto_passwd -b "$passwords" "$role" "$secret"
done
chown mosquitto:mosquitto "$passwords"
chmod 0700 "$passwords"
exec mosquitto -c /mosquitto/config/mosquitto.conf
