#include "session.h"
#include <stdio.h>
#include <string.h>

int init_session(Connection *conn, const char *host) {
    conn->fd = -1;
    conn->host = host;
    printf("connected to %s on fd %d\n", host, conn->fd);
    return conn->fd;
}
