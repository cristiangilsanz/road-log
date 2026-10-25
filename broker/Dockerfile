FROM eclipse-mosquitto:2.0.20
COPY mosquitto.conf acl /mosquitto/config/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && chown mosquitto:mosquitto /mosquitto/config/acl && chmod 0700 /mosquitto/config/acl
ENTRYPOINT ["/entrypoint.sh"]
