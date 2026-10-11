#!/usr/bin/env python3
"""Compare current ANR scalar final-gain reference and optimized per-hop bytes.

Run from any directory: python python/tools/test_bit_exact.py --backend kiss --simd 1.
Builds use one audio_common archive and release FP policy; all scratch is temporary.
"""
import argparse
import os
from pathlib import Path
import shlex
import struct
import subprocess
import tempfile


FIELDS = (
    "power", "SPP", "xi", "gamma", "gain", "gain_prev", "enhanced_psd_prev",
    "log_gain_prev", "noise_psd", "MCRA S", "MCRA S_min", "MCRA internal SPP",
    "SPP gamma_prev", "SPP noise_psd_prev", "spectrum_out", "gain_out",
    "scalar state", "flags/ring/scene state", "MCRA full min ring",
)
DEFINES = (
    "USE_FAST_GAIN_SMOOTHING", "USE_SHARED_XI_RATIO", "USE_OPTIMIZED_MIN_BUFFER",
    "USE_OPTIMIZED_E1", "USE_SINGLE_CLAMP", "USE_INCREMENTAL_MIN",
)


def run(command, **kwargs):
    result = subprocess.run(command, check=True, **kwargs)
    return result.stdout


def read_exact(stream, size):
    parts = []
    remaining = size
    while remaining:
        part = stream.read(remaining)
        if not part:
            if remaining == size:
                return None
            raise RuntimeError("truncated bit-exact stream")
        parts.append(part)
        remaining -= len(part)
    return b"".join(parts)


def compare(reference, optimized):
    processes = [subprocess.Popen([str(path)], stdout=subprocess.PIPE)
                 for path in (reference, optimized)]
    count = frames = byte_count = 0
    try:
        infos = [read_exact(p.stdout, 16) for p in processes]
        if any(info is None for info in infos):
            raise RuntimeError("runner failed before stream header")
        info = [struct.unpack("=4I", data) for data in infos]
        if info[0][0] != 0x414E5231 or info[1][0] != info[0][0]:
            raise RuntimeError("invalid stream header")
        if info[0][1] != info[1][1] or info[0][2] != 0 or info[0][3] != info[1][3]:
            raise RuntimeError("inconsistent runner configuration")
        print("final-gain NEON path exercised:", "yes" if info[1][2] else "no (scalar build)", flush=True)
        while True:
            headers = [read_exact(p.stdout, 28) for p in processes]
            if headers == [None, None]:
                break
            if None in headers or headers[0] != headers[1]:
                raise RuntimeError("record metadata/length mismatch")
            magic, grid, strength, feature, frame, field, words = struct.unpack("=7I", headers[0])
            if magic != 0x414E5232 or field >= len(FIELDS) or words > 200000:
                raise RuntimeError("invalid record header")
            values = [read_exact(p.stdout, 4 * words) for p in processes]
            if None in values:
                raise RuntimeError("missing record payload")
            if values[0] != values[1]:
                first = next(i for i, (a, b) in enumerate(zip(*values)) if a != b) // 4
                a = struct.unpack_from("=I", values[0], 4 * first)[0]
                b = struct.unpack_from("=I", values[1], 4 * first)[0]
                raise RuntimeError(
                    f"grid={'ABC'[grid]} strength={strength} "
                    f"feature={feature} hop={frame} {FIELDS[field]}[{first}]: "
                    f"0x{a:08x} != 0x{b:08x}"
                )
            count += 1
            frames += field == 0
            byte_count += 4 * words
        for process in processes:
            if process.wait() != 0:
                raise RuntimeError("runner exited unsuccessfully")
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
            process.wait()
            process.stdout.close()
    expected = 3 * (4 + 3 + 1) * info[0][3]
    if frames != expected or count == 0:
        raise RuntimeError(f"incomplete coverage: {frames} hops, expected {expected}")
    print(f"ANR bit-exact PASS: {frames} hops, {count} state/output records, {byte_count} bytes compared", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("kiss", "ne10"), default="ne10")
    parser.add_argument("--simd", choices=(0, 1), type=int, default=1)
    parser.add_argument("--ac-dir", type=Path)
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"))
    parser.add_argument("--cxx", default=os.environ.get("CXX", "c++"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    common = args.ac_dir.resolve() if args.ac_dir else root.parent / "audio_common"
    if not (common / "Makefile").is_file():
        parser.error("audio_common not found; pass --ac-dir /path/to/audio_common")
    producer = ["make", "--no-print-directory", "-C", str(common),
                f"BACKEND={args.backend}", f"SIMD={args.simd}", "WERROR=1",
                f"CC={args.cc}", f"CXX={args.cxx}", "DEBUG=0"]
    run(producer + ["lib"])
    library = Path(run(producer + ["-s", "print-lib-path"], capture_output=True, text=True).strip())
    if not library.is_file():
        raise RuntimeError(f"producer archive missing: {library}")
    flags = ["-O2", "-std=gnu99", "-Wall", "-Wextra", "-Werror",
             "-ffp-contract=off", "-fno-math-errno",
             "-I" + str(root / "c_impl/include"), "-I" + str(common / "include")]
    flags += ["-D" + define for define in DEFINES]
    if not args.simd:
        flags.append("-DSIMD_KERNELS_FORCE_SCALAR")
    with tempfile.TemporaryDirectory(prefix="anr-bit-exact-") as directory:
        scratch = Path(directory)
        binaries = {}
        for name, source, extra in (
            ("reference", "test_bit_exact_stream.c", ["-DANR_REFERENCE_KERNELS"]),
            ("optimized", "test_bit_exact_stream.c", []),
            ("minimum", "test_min_ordered_special.c", []),
            ("kernels", "test_anr_kernels.c", []),
        ):
            obj = scratch / (name + ".o")
            binary = scratch / name
            run(shlex.split(args.cc) + flags + extra + ["-c", str(root / "c_impl/test" / source), "-o", str(obj)])
            linker = args.cxx if args.backend == "ne10" else args.cc
            run(shlex.split(linker) + [str(obj), str(library), "-lm", "-o", str(binary)])
            binaries[name] = binary
        compare(binaries["reference"], binaries["optimized"])
        run([str(binaries["minimum"])])
        run([str(binaries["kernels"])])


if __name__ == "__main__":
    main()
