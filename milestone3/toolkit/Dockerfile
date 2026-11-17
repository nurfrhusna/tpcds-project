FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends gcc make bison flex libc6-dev
COPY DSGen-software-code-4.0.0 /opt/tpcds
WORKDIR /opt/tpcds/tools
RUN make -j4 CFLAGS="-g -Wall -fcommon -D_FILE_OFFSET_BITS=64 -D_LARGEFILE_SOURCE -DYYDEBUG -DLINUX" dsdgen dsqgen
ENTRYPOINT ["./dsdgen"]
