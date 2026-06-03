#include <stdio.h>

/* a worker has its own, unrelated init_session */

static int init_session(int worker_id) {
    printf("worker %d ready\n", worker_id);
    return worker_id;
}

void worker_run(int id) {
    /* call the file-local init_session, not the global one */
    init_session(id);
}
