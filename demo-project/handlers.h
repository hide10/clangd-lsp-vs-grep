#ifndef HANDLERS_H
#define HANDLERS_H

/* DEFINE_HANDLER(name) builds a function called handle_<name> at compile
 * time. The "##" token-pastes "handle_" onto whatever name you pass, so
 * DEFINE_HANDLER(session) produces a function named handle_session even
 * though that exact text is never written anywhere. */
#define DEFINE_HANDLER(name)            \
    int handle_##name(void) {           \
        printf("handling %s\n", #name); \
        return 0;                       \
    }

#endif /* HANDLERS_H */
