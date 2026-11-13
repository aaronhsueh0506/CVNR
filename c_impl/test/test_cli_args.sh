#!/bin/sh
# Argument handling of the example CLIs (denoise_wav and denoise_mem): --nr-level and its alias --nr-mode need a
# value, a following token that starts with "--" is not one (exit 2, "<prog>: <option> needs a value" on stderr), and
# a lone "-" or "-1" is a value. The value is the level number 0..3 as a whole decimal string: anything else (a level
# name, "-", "-1", "3x", an empty or padded string, 4) is exit 2 with "unknown NR level" and no output file.
# Usage: test_cli_args.sh <denoise_wav> <denoise_mem>   (PYTHON overrides python3; it only writes the input WAV)
set -u
PYTHON="${PYTHON:-python3}"
[ $# -eq 2 ] || { echo "usage: $0 <denoise_wav> <denoise_mem>" >&2; exit 2; }

d="$(mktemp -d "${TMPDIR:-/tmp}/nr_cli_args.XXXXXX")" || exit 1
trap 'rm -rf "$d"' EXIT INT TERM
"$PYTHON" -I - "$d/in.wav" <<'PY' || exit 1
import math, struct, sys, wave
n, rate, seed, s16 = 16000, 16000, 12345, []
for i in range(n):
    seed = (seed * 1103515245 + 12345) & 0x7fffffff
    s16.append(int(6000 * math.sin(2 * math.pi * 440 * i / rate) + (seed % 2001) - 1000))
with wave.open(sys.argv[1], 'wb') as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
    w.writeframes(struct.pack('<%dh' % n, *s16))
PY

fail=0
check() {  # check <description> <condition-exit-status>
    if [ "$2" -eq 0 ]; then echo "  ok   $1"; else echo "  FAIL $1" >&2; fail=1; fi
}
# expect_bad_level <bin> <option> <value>: exit 2, "unknown NR level" on stderr, no output file written.
expect_bad_level() {
    bin=$1; opt=$2; val=$3
    rm -f "$d/out.wav"
    "$bin" "$d/in.wav" "$d/out.wav" "$opt" "$val" >"$d/stdout" 2>"$d/stderr"; rc=$?
    [ "$rc" -eq 2 ] && grep -q "unknown NR level" "$d/stderr" && [ ! -e "$d/out.wav" ]
    check "$(basename "$bin") $opt '$val' -> exit 2, unknown NR level" $?
}
# expect_reject <bin> <option> [following token...]: exit 2, message names the option, no output file written.
expect_reject() {
    bin=$1; shift
    rm -f "$d/out.wav"
    "$bin" "$d/in.wav" "$d/out.wav" "$@" >"$d/stdout" 2>"$d/stderr"; rc=$?
    opt=$1
    [ "$rc" -eq 2 ] && grep -q ": $opt needs a value" "$d/stderr" && [ ! -e "$d/out.wav" ]
    st=$?
    check "$(basename "$bin") $* -> exit 2, '$opt needs a value'" "$st"
}
run_ok() {  # run_ok <bin> <out> [args...]
    bin=$1; out=$2; shift 2
    "$bin" "$d/in.wav" "$out" "$@" >"$d/stdout" 2>"$d/stderr"
}

for bin in "$1" "$2"; do
    name=$(basename "$bin")
    run_ok "$bin" "$d/default.wav"; check "$name default run" $?
    run_ok "$bin" "$d/aggr.wav" --nr-level 3; check "$name --nr-level 3" $?
    run_ok "$bin" "$d/alias.wav" --nr-mode 3; check "$name --nr-mode 3" $?
    cmp -s "$d/aggr.wav" "$d/alias.wav"; check "$name --nr-level 3 == --nr-mode 3" $?
    cmp -s "$d/aggr.wav" "$d/default.wav"; [ $? -ne 0 ]; check "$name level takes effect (3 != default)" $?
    run_ok "$bin" "$d/bal.wav" --nr-level 2; check "$name --nr-level 2" $?
    cmp -s "$d/bal.wav" "$d/default.wav"; check "$name --nr-level 2 is the default" $?
    for v in aggressive balanced - -1 3x 4 +2x ""; do
        expect_bad_level "$bin" --nr-level "$v"
    done
    expect_bad_level "$bin" --nr-mode " 2"
    expect_reject "$bin" --nr-level
    expect_reject "$bin" --nr-mode
    expect_reject "$bin" --nr-level --debug
    expect_reject "$bin" --nr-mode --bypass
done

[ "$fail" -eq 0 ] && echo "test_cli_args: PASS" || { echo "test_cli_args: FAIL" >&2; exit 1; }
