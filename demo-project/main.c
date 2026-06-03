#include "session.h"
#include <stdio.h>
int handle_session(void);   /* forward decl; the body is built by a macro */

int main(void) {
    Connection conn;

    init_session(&conn, "example.com");

    handle_session();
    printf("fd = %d\n", conn.fd);
    return 0;
}
