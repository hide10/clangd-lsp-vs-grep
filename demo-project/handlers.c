#include <stdio.h>
#include "handlers.h"

/* Each line below expands to a full function definition. grep for
 * "handle_session" will never find the body, because the name is
 * assembled by the preprocessor. clangd resolves it after expansion. */
DEFINE_HANDLER(session)
DEFINE_HANDLER(login)
