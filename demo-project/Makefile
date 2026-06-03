# Build the demo so you can confirm it really compiles (the traps are valid C).
# `make compdb` writes a compile_commands.json via Bear, which makes clangd's
# analysis maximally accurate (compile_flags.txt alone is already enough here).

CC      ?= cc
CFLAGS  ?= -std=c11 -I. -Wall
SOURCES := main.c session.c worker.c log.c handlers.c
OBJECTS := $(SOURCES:.c=.o)

demo: $(OBJECTS)
	$(CC) $(CFLAGS) -o $@ $(OBJECTS)

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

compdb: clean
	bear -- $(MAKE) demo

clean:
	rm -f $(OBJECTS) demo

.PHONY: compdb clean
