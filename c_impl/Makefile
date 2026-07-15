# MMSE-LSA Denoiser Makefile
# V3-2 C Implementation
#
# =============================================================================
# FFT backend policy (this branch: feature/static-memory)
# =============================================================================
# FFT + fast_math no longer live in this repo — they come from the shared
# ../audio_common layer (consumed as a prebuilt static archive, libaudio_common.a).
# audio_common exposes two backends behind the SAME public API (fft_wrapper.h):
#
#   BACKEND=kiss   portable KISS FFT     (default here; bit-reproducible
#                                         reference + the Python<->C parity backend)
#   BACKEND=ne10   ARM NEON NE10 FFT     (embedded target; pass explicitly)
#
# This branch's DELIVERABLE is the NE10 backend for the embedded target:
#     make BACKEND=ne10 ...
# KISS stays the default (`BACKEND ?= kiss`) so every existing parity / bit-exact
# gate (tools/parity_nr.py, the debug/standard-math builds, the byte-equal
# regression checks) keeps its deterministic reference build without callers
# having to pass anything.
# =============================================================================

CC  = gcc
CXX = c++
BACKEND ?= kiss

# Locate audio_common: normal checkout has it as a sibling of this repo
# (../../audio_common from c_impl/). The second candidate covers this repo being
# consumed as a git submodule two levels deeper (e.g. Audio_ALG/lib/nr/c_impl/ ->
# .../lib/nr/../../audio_common == ../../../../audio_common from c_impl/).
AC_DIR ?= $(firstword $(wildcard ../../audio_common ../../../../audio_common))
AC_LIB  = $(AC_DIR)/bin/$(BACKEND)/libaudio_common.a

CFLAGS = -Wall -Wextra -O2 -std=gnu99
CFLAGS += -I./include -I./example -I$(AC_DIR)/include
CFLAGS += $(EXTRA_CFLAGS)

# The NE10 archive contains one C++ translation unit (NE10's generic-radix FFT
# kernel), so linking a binary against it needs the C++ runtime. Mirror
# audio_common's own Makefile: use the C++ driver to link when BACKEND=ne10 (all
# of NR's own sources stay plain C either way — only the LINK driver changes).
LINK = $(CC)
ifeq ($(BACKEND),ne10)
  LINK = $(CXX)
  LDFLAGS_EXTRA = -lc++
endif

# =============================================================================
# Default optimizations (mathematically equivalent, 100% bit-exact)
# =============================================================================
CFLAGS += -DUSE_FAST_GAIN_SMOOTHING
CFLAGS += -DUSE_SHARED_XI_RATIO
CFLAGS += -DUSE_OPTIMIZED_MIN_BUFFER
CFLAGS += -DUSE_OPTIMIZED_E1
CFLAGS += -DUSE_SINGLE_CLAMP
CFLAGS += -DUSE_INCREMENTAL_MIN

# =============================================================================
# Build Configuration Flags (pass via EXTRA_CFLAGS)
# =============================================================================
#
# USE_STANDARD_MATH - Use standard math library functions (for debugging)
#   When defined: Uses expf(), logf(), sqrtf(), log10f(), powf()
#   When not defined: Uses fast LUT+Taylor approximations
#   Example: make EXTRA_CFLAGS="-DUSE_STANDARD_MATH"
#
# USE_FAST_PERCENTILE - Use fast percentile approximation (for speed optimization)
#   When defined: Uses mean × 0.17 approximation for 20th percentile
#   When not defined: Uses exact Quickselect algorithm (requires extra ~20KB memory)
#   Example: make EXTRA_CFLAGS="-DUSE_FAST_PERCENTILE"
#
# USE_FAST_GAIN_SMOOTHING - Optimize gain smoothing by eliminating log-exp-log redundancy
#   When defined: Performs clamping in log domain, avoids exp→log conversion
#   When not defined: Uses original exp→clamp→log sequence
#   Example: make EXTRA_CFLAGS="-DUSE_FAST_GAIN_SMOOTHING"
#
# USE_SHARED_XI_RATIO - Share v=xi/(1+xi)*gamma computation between SPP and Gain
#   When defined: SPP outputs v, Gain reuses it instead of recomputing
#   When not defined: Both SPP and Gain compute v independently
#   Example: make EXTRA_CFLAGS="-DUSE_SHARED_XI_RATIO"
#
# USE_OPTIMIZED_MIN_BUFFER - Optimize MCRA min tracking buffer memory layout
#   When defined: Layout [freq_idx * L + frame_idx], contiguous access per frequency
#   When not defined: Layout [frame_idx * n_freqs + freq_idx], strided access
#   Example: make EXTRA_CFLAGS="-DUSE_OPTIMIZED_MIN_BUFFER"
#
# USE_OPTIMIZED_E1 - Optimize E1(v) exponential integral branch ordering
#   When defined: Checks v > 1.0 first, computes log10 once for v <= 1.0
#   When not defined: Uses original branch order (v < 0.1, v <= 1.0, v > 1.0)
#   Example: make EXTRA_CFLAGS="-DUSE_OPTIMIZED_E1"
#
# USE_SINGLE_CLAMP - Remove redundant final clamp in gain calculation
#   When defined: Skips final [g_min, 1.0] clamp (already clamped before log-domain)
#   When not defined: Performs clamp twice (gain_mmse and final gain)
#   Example: make EXTRA_CFLAGS="-DUSE_SINGLE_CLAMP"
#
# Recommended build configurations:
#   1. Debug build (standard math, no optimizations, matches Python most closely):
#      make debug
#
#   2. Standard build (fast math + all equivalent optimizations):
#      make
#
#   3. Full optimized build (all approximations including fast percentile):
#      make EXTRA_CFLAGS="-DUSE_FAST_PERCENTILE"
#
# =============================================================================

# Debug flags (uncomment for debugging)
# CFLAGS += -g -DDEBUG

LDFLAGS = -lm $(LDFLAGS_EXTRA)

# -Werror opt-in for this repo's OWN sources (default off; CI can flip it on
# with `make WERROR=1`). Like AEC, NR compiles no vendored TUs itself (FFT +
# fast_math are vendored inside audio_common), so every object built by this
# Makefile is "our code" -- no separate warning isolation is needed here.
WERROR ?= 0
ifeq ($(WERROR),1)
  CFLAGS += -Werror
endif

# Directories
SRC_DIR = src
EXAMPLE_DIR = example
# Hash-keyed object dir: obj/<backend>-<cfg-sig>/ (not a single flat
# directory shared across every BACKEND/EXTRA_CFLAGS combination, unlike the
# old scheme -- that used to mean neither a BACKEND nor an EXTRA_CFLAGS
# change invalidated the .o files already sitting in obj/, the long-standing
# trap this section used to document at the ac_lib rule below, "Always
# `make clean` when changing BACKEND"). CFG_SIG (below) hashes the exact
# compiler invocation that produces every object in this build, and OBJ_DIR
# embeds it directly: every distinct (BACKEND, CFLAGS, EXTRA_CFLAGS, WERROR)
# combination gets its own directory, automatically -- no manual clean ever
# required, and two differently-configured builds can run concurrently in
# this same tree without stomping each other's objects. OBJ_ROOT is the
# whole obj/ tree (every config) -- used by `clean` to nuke everything, not
# just the current config's subdirectory. BIN_DIR stays flat (not
# per-backend/config): the final binaries are last-write-wins wholes, same
# as before.
OBJ_ROOT = obj
OBJ_DIR = $(OBJ_ROOT)/$(BACKEND)-$(CFG_SIG)
BIN_DIR = bin

# --- Hash-keyed object directory (build hygiene) ----------------------------
# This MUST be defined here, before any rule below mentions $(OBJ_DIR) (or
# anything derived from it, e.g. $(OBJS)/$(EXAMPLE_OBJS) used in a
# prerequisite list): GNU Make expands a rule's target/prerequisite list
# IMMEDIATELY when that line is parsed, not deferred like a recipe body, so
# a forward reference would silently resolve using CFG_SIG's value at THAT
# point in the file (empty, if this line hadn't run yet) -- verified
# empirically with a minimal reproduction.
#
# There is no parse-time comparison and nothing is ever deleted to "detect"
# a config change (the previous scheme did a $(shell rm -rf ...)/$(shell
# mkdir ...)/$(shell echo ...) unconditionally while the Makefile was being
# read, which mutated the filesystem even under `make -n` and raced two
# concurrent builds with different flags against each other's shared obj/
# directory). Under this scheme `make -n` touches nothing on disk (CFG_SIG
# is a pure string hash) and two differently-configured builds (e.g.
# `make BACKEND=kiss -j4 & make BACKEND=ne10 -j4 & wait`) can run
# concurrently in this same tree: each lands in its own obj/<backend>-<sig>/
# directory and never touches the other's objects. OBJ_DIR's own creation
# happens lazily via the order-only prerequisite on the pattern rules below
# ($(OBJ_DIR)/%.o: ... | $(OBJ_DIR)), not at Makefile-parse time.
#
# cksum (POSIX -- present on macOS/BSD/GNU/busybox, unlike shasum which is a
# GNU coreutils extension and may be absent from slim embedded build images)
# computes the hash. On stdin it prints "<checksum> <byte-count>" with no
# filename field (verified on macOS's BSD cksum), so `cut -d' ' -f1` isolates
# just the checksum.
CFG_SIG := $(shell printf '%s' "$(CC) $(CFLAGS) $(EXTRA_CFLAGS) BACKEND=$(BACKEND) WERROR=$(WERROR)" | cksum | cut -d' ' -f1)

# Source files (gain calculation merged into mmse_lsa_denoiser.c). FFT + fast_math
# come from audio_common (linked via $(AC_LIB)); this repo only supplies the
# denoiser/MCRA/SPP core.
SRCS = $(SRC_DIR)/mmse_lsa_denoiser.c \
       $(SRC_DIR)/mcra_noise_estimator.c \
       $(SRC_DIR)/spp_estimator.c

EXAMPLE_SRCS = $(EXAMPLE_DIR)/main.c

# Object files
OBJS = $(patsubst $(SRC_DIR)/%.c,$(OBJ_DIR)/%.o,$(SRCS))
EXAMPLE_OBJS = $(patsubst $(EXAMPLE_DIR)/%.c,$(OBJ_DIR)/%.o,$(EXAMPLE_SRCS))

# Target binary
TARGET = $(BIN_DIR)/denoise_wav

# Default target
all: $(TARGET)

# $(OBJ_DIR)/$(BIN_DIR) creation is an order-only prerequisite on the actual
# compile/link rules below (not a $(shell mkdir) at parse time, and not a
# plain prerequisite that could race a parallel compile under `make -j`) --
# every rule that writes into one of these directories depends on it
# existing first, and mkdir -p is idempotent if two rules' order-only
# prereqs resolve concurrently. `dirs` is kept as a convenience alias for
# any caller used to invoking it directly.
$(OBJ_DIR) $(BIN_DIR):
	@mkdir -p $@

dirs: $(OBJ_DIR) $(BIN_DIR)

# Build audio_common's archive for the selected BACKEND. Order-only prerequisite
# on the link steps below: `ac_lib` is phony, so it (and the recursive make it
# runs) always executes before the link recipe — audio_common's own Makefile
# decides whether anything is actually stale. Being order-only means it does NOT
# force OUR .o files to recompile, and it does NOT feed into whether $(TARGET)
# itself is considered stale. No manual `make clean` is ever required when
# switching BACKEND/EXTRA_CFLAGS/WERROR -- CFG_SIG (above) gives each config
# its own $(OBJ_DIR), so there's nothing stale to relink.
.PHONY: ac_lib
ac_lib:
	$(MAKE) -C $(AC_DIR) BACKEND=$(BACKEND) lib

# Link
$(TARGET): $(OBJS) $(EXAMPLE_OBJS) | ac_lib $(BIN_DIR)
	$(LINK) $(CFLAGS) -o $@ $(OBJS) $(EXAMPLE_OBJS) $(AC_LIB) $(LDFLAGS)
	@echo "Build complete: $@"

# Compile source files
$(OBJ_DIR)/%.o: $(SRC_DIR)/%.c | $(OBJ_DIR)
	$(CC) $(CFLAGS) -c -o $@ $<

# Compile example files
$(OBJ_DIR)/%.o: $(EXAMPLE_DIR)/%.c | $(OBJ_DIR)
	$(CC) $(CFLAGS) -c -o $@ $<

# Debug build (disable all optimizations, use standard math)
debug: CFLAGS += -DUSE_STANDARD_MATH
debug: CFLAGS := $(filter-out -DUSE_FAST_GAIN_SMOOTHING -DUSE_SHARED_XI_RATIO -DUSE_OPTIMIZED_MIN_BUFFER -DUSE_OPTIMIZED_E1 -DUSE_SINGLE_CLAMP -DUSE_INCREMENTAL_MIN,$(CFLAGS))
debug: $(TARGET)
	@echo "Debug build complete (standard math, no optimizations): $(TARGET)"

# Clean
clean:
	rm -rf $(OBJ_ROOT) $(BIN_DIR)
	@echo "Clean complete"

# Install (copy to /usr/local/bin)
install: $(TARGET)
	cp $(TARGET) /usr/local/bin/
	@echo "Installed to /usr/local/bin/denoise_wav"

# Uninstall
uninstall:
	rm -f /usr/local/bin/denoise_wav
	@echo "Uninstalled"

# Test with sample file (requires test.wav in current directory)
test: $(TARGET)
	@if [ -f test.wav ]; then \
		./$(TARGET) test.wav test_out.wav; \
	else \
		echo "No test.wav found. Create a test file or run:"; \
		echo "  $(TARGET) <input.wav> <output.wav>"; \
	fi

# Build static library (denoiser/MCRA/SPP core only — link $(AC_LIB) separately
# for the FFT backend, same as the binaries above).
LIB_TARGET = $(BIN_DIR)/libmmse_lsa.a

lib: $(OBJS) | $(BIN_DIR)
	ar rcs $(LIB_TARGET) $(OBJS)
	@echo "Static library built: $(LIB_TARGET)"

# =============================================================================
# Python<->C parity runner (drives mmse_lsa_process_gain on dumped spectra)
# Built separately from denoise_wav (both have their own main()).
# Honors EXTRA_CFLAGS, so:  make parity            -> fast-math
#                           make parity EXTRA_CFLAGS="-DUSE_STANDARD_MATH" -> std-math
# See tools/parity_nr.py for the Python side.
# =============================================================================
PARITY_TARGET = $(BIN_DIR)/parity_runner

parity: $(OBJS) $(OBJ_DIR)/parity_runner.o | ac_lib $(BIN_DIR)
	$(LINK) $(CFLAGS) -o $(PARITY_TARGET) $(OBJS) $(OBJ_DIR)/parity_runner.o $(AC_LIB) $(LDFLAGS)
	@echo "Build complete: $(PARITY_TARGET)"

$(OBJ_DIR)/parity_runner.o: $(EXAMPLE_DIR)/parity_runner.c | $(OBJ_DIR)
	$(CC) $(CFLAGS) -c -o $@ $<

# =============================================================================
# Static-memory build: the NR engine + MCRA/SPP + FFT allocate ALL state from
# caller-provided memory — zero malloc/free on the audio path. Links the
# static-memory example (example/main_mem.c) against the SAME objects as
# denoise_wav (the malloc path and the static path are always both compiled in
# now — see mmse_lsa_get_mem_size()/mmse_lsa_init() — so there is no separate
# object set to keep from mixing, unlike the old compile-time-gated build).
# Honors EXTRA_CFLAGS, e.g.:  make mem EXTRA_CFLAGS="-DUSE_STANDARD_MATH"
# FFT backends: KISS is 100% no-malloc on the static path. NE10 (make mem
#       BACKEND=ne10) is PARTIAL — handle + work buffers come from the pool, but
#       NE10's twiddle cfg keeps its one-time internal malloc at fft_create()
#       (standard NE10 has no ext-mem API for it); the per-frame audio path is
#       still malloc-free either way.
# =============================================================================
MEM_TARGET = $(BIN_DIR)/denoise_mem

mem: $(OBJS) $(OBJ_DIR)/main_mem.o | ac_lib $(BIN_DIR)
	$(LINK) $(CFLAGS) -o $(MEM_TARGET) $(OBJS) $(OBJ_DIR)/main_mem.o $(AC_LIB) $(LDFLAGS)
	@echo "Static-memory build complete: $(MEM_TARGET)"

$(OBJ_DIR)/main_mem.o: $(EXAMPLE_DIR)/main_mem.c | $(OBJ_DIR)
	$(CC) $(CFLAGS) -c -o $@ $<

# =============================================================================
# Config-validation / alignment-guard regression tests (F05/F07 remediation:
# overflow-checked get_mem_size size arithmetic + sample_rate/framing/L/
# num_init_frames bounds + misaligned-pool-base rejection). Standalone runner,
# no external test framework — see test/test_config_validation.c. Builds
# against the same objects as denoise_wav and runs itself; a non-zero exit
# (any failed check) fails the `make test-config` recipe.
# =============================================================================
TEST_DIR    = test
TEST_TARGET = $(BIN_DIR)/test_config_validation

test-config: $(OBJS) $(OBJ_DIR)/test_config_validation.o | ac_lib $(BIN_DIR)
	$(LINK) $(CFLAGS) -o $(TEST_TARGET) $(OBJS) $(OBJ_DIR)/test_config_validation.o $(AC_LIB) $(LDFLAGS)
	@echo "Build complete: $(TEST_TARGET)"
	./$(TEST_TARGET)

$(OBJ_DIR)/test_config_validation.o: $(TEST_DIR)/test_config_validation.c | $(OBJ_DIR)
	$(CC) $(CFLAGS) -c -o $@ $<

# Help
help:
	@echo "MMSE-LSA Denoiser Build System"
	@echo ""
	@echo "Targets:"
	@echo "  all      - Build the denoiser executable (default)"
	@echo "  mem      - Build the static-memory example (bin/denoise_mem)"
	@echo "  parity   - Build the Python<->C parity runner (bin/parity_runner)"
	@echo "  test-config - Build + run config-validation/alignment-guard tests"
	@echo "  lib      - Build static library"
	@echo "  clean    - Remove build artifacts"
	@echo "  install  - Install to /usr/local/bin"
	@echo "  uninstall - Remove from /usr/local/bin"
	@echo "  test     - Run test (requires test.wav)"
	@echo "  help     - Show this help"
	@echo ""
	@echo "Build Configurations:"
	@echo "  make                                          - Standard build (KISS FFT, fast math)"
	@echo "  make BACKEND=ne10                             - NE10 R2C/C2R build (ARM NEON, embedded deliverable)"
	@echo "  make EXTRA_CFLAGS=\"-DUSE_STANDARD_MATH\"      - Debug build (matches Python output)"
	@echo "  make EXTRA_CFLAGS=\"-DUSE_FAST_PERCENTILE\"    - Optimized build (all approximations)"
	@echo "  make WERROR=1                                  - Opt-in: -Werror for this repo's own sources"
	@echo ""
	@echo "Objects live in obj/<backend>-<config-hash>/ -- switching BACKEND,"
	@echo "EXTRA_CFLAGS, or WERROR always lands in a fresh directory automatically;"
	@echo "no manual clean needed, and two differently-configured builds can run"
	@echo "concurrently in this same tree."
	@echo ""
	@echo "Flags:"
	@echo "  USE_STANDARD_MATH   - Use standard math functions (expf, logf, etc.)"
	@echo "  USE_FAST_PERCENTILE - Use mean*0.17 approximation instead of exact percentile"
	@echo ""
	@echo "Memory usage:"
	@echo "  Without USE_FAST_PERCENTILE: +20KB for exact percentile buffer"
	@echo "  With USE_FAST_PERCENTILE: No extra memory"
	@echo ""
	@echo "After building:"
	@echo "  ./bin/denoise_wav input.wav output.wav"

.PHONY: all dirs clean install uninstall test lib help debug parity mem ac_lib test-config
