#!/bin/sh
# parity_runner on an NRP2 file whose header promises more frames than the file holds: exit 1 and no output file (never a full-size
# gain file whose tail was not computed). A complete file still gives exit 0 and a header+n*nf float output of the exact size.
# Usage: test_parity_runner_input.sh <parity_runner>   (PYTHON overrides python3; it only writes the inputs)
set -u
PYTHON="${PYTHON:-python3}"
[ $# -eq 1 ] || { echo "usage: $0 <parity_runner>" >&2; exit 2; }
bin=$1
d="$(mktemp -d "${TMPDIR:-/tmp}/nr_parity_input.XXXXXX")" || exit 1
trap 'rm -rf "$d"' EXIT INT TERM
"$PYTHON" -I - "$d" <<'PY' || exit 1
import struct, sys
d = sys.argv[1]
nf = 129                                   # 16 kHz / fft 256
def frame(i):
    return struct.pack('<%df' % (2 * nf), *[0.01 * ((k * 7 + i) % 13 - 6) for k in range(2 * nf)])
for name, claim, have in (('full.nrp2', 6, 6), ('short.nrp2', 50, 3)):
    with open(d + '/' + name, 'wb') as f:
        f.write(struct.pack('<4i', 0x4E525032, claim, nf, 16000))
        for i in range(have):
            f.write(frame(i))
PY
fail=0
check() { if [ "$2" -eq 0 ]; then echo "  ok   $1"; else echo "  FAIL $1" >&2; fail=1; fi; }

"$bin" "$d/full.nrp2" "$d/full.out" >/dev/null 2>"$d/err"; rc=$?
size=$(wc -c < "$d/full.out" 2>/dev/null | tr -d ' ')
[ "$rc" -eq 0 ] && [ "$size" = "$((8 + 6 * 129 * 4))" ]
check "complete input -> exit 0, output $((8 + 6 * 129 * 4)) bytes" $?

rm -f "$d/short.out"
"$bin" "$d/short.nrp2" "$d/short.out" >/dev/null 2>"$d/err"; rc=$?
[ "$rc" -eq 1 ] && grep -q "short spectra" "$d/err" && [ ! -e "$d/short.out" ]
check "truncated input -> exit 1, no output file" $?
exit $fail
