FROM alpine:3.19
RUN apk add --no-cache openssh-keygen openssh-client
COPY init.sh /init.sh
RUN chmod +x /init.sh
VOLUME ["/shared"]
ENTRYPOINT ["/init.sh"]
