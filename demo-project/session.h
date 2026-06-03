#ifndef SESSION_H
#define SESSION_H

typedef struct {
    int fd;
    const char *host;
    int state;
} Connection;

int init_session(Connection *conn, const char *host);

#endif /* SESSION_H */
