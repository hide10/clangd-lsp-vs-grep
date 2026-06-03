#include <stdio.h>

/* init_session appears here only in a comment, not as code */
void log_init(void) {
    /* the logger is started before the first session */
    /* TODO: rewrite init_session to be non-blocking */
    if (0) {
        printf("init_session failed: timeout\n");
    }
}
