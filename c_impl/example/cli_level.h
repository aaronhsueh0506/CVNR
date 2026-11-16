/* cli_level.h -- strict --nr-level argument of the example and test programs. */
#ifndef ANR_EXAMPLE_CLI_LEVEL_H
#define ANR_EXAMPLE_CLI_LEVEL_H

#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>

#include "anr_types.h"

/* The accepted level numbers, as the example and test programs print them in a bad-level error. */
#define ANR_CLI_LEVELS "0 mild, 1 moderate, 2 balanced, 3 aggressive"

/* Parses the whole string as a decimal AnrLevel number (0 mild, 1 moderate, 2 balanced,
 * 3 aggressive). Returns 0 and writes *out, or -1 (nothing written) for NULL, an empty or padded
 * string, trailing characters, or a value outside 0..3. */
static inline int anr_cli_parse_level(const char* text, AnrLevel* out) {
    char* end = NULL;
    long v;
    if (!text || *text == '\0' || isspace((unsigned char)*text)) return -1;
    errno = 0;
    v = strtol(text, &end, 10);
    if (errno != 0 || *end != '\0' || v < 0 || v > 3) return -1;
    *out = (AnrLevel)v;
    return 0;
}

/* Option argv[i] takes the next token as its value unless that is missing or starts with "--" (a
 * lone "-" or "-5" is a value). Returns 1 and prints "<prog>: <option> needs a value" when it has none. */
static inline int anr_cli_value_missing(int argc, char* argv[], int i) {
    if (i + 1 < argc && !(argv[i + 1][0] == '-' && argv[i + 1][1] == '-')) return 0;
    fprintf(stderr, "%s: %s needs a value\n", argv[0], argv[i]);
    return 1;
}

#endif
