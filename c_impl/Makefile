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

# Directories
SRC_DIR = src
EXAMPLE_DIR = example
OBJ_DIR = obj
BIN_DIR = bin

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
all: dirs $(TARGET)

# Create directories
dirs:
	@mkdir -p $(OBJ_DIR) $(BIN_DIR)

# Build audio_common's archive for the selected BACKEND. Order-only prerequisite
# on the link steps below: `ac_lib` is phony, so it (and the recursive make it
# runs) always executes before the link recipe — audio_common's own Makefile
# decides whether anything is actually stale. Being order-only means it does NOT
# force OUR .o files to recompile, and it does NOT feed into whether $(TARGET)
# itself is considered stale — this repo's obj/bin dirs are NOT split per
# BACKEND (unlike audio_common's), so switching BACKEND on an already-built tree
# without `make clean` will NOT relink automatically. Always `make clean` when
# changing BACKEND.
.PHONY: ac_lib
ac_lib:
	$(MAKE) -C $(AC_DIR) BACKEND=$(BACKEND) lib

# Link
$(TARGET): $(OBJS) $(EXAMPLE_OBJS) | ac_lib
	$(LINK) $(CFLAGS) -o $@ $(OBJS) $(EXAMPLE_OBJS) $(AC_LIB) $(LDFLAGS)
	@echo "Build complete: $@"

# Compile source files
$(OBJ_DIR)/%.o: $(SRC_DIR)/%.c
	$(CC) $(CFLAGS) -c -o $@ $<

# Compile example files
$(OBJ_DIR)/%.o: $(EXAMPLE_DIR)/%.c
	$(CC) $(CFLAGS) -c -o $@ $<

# Debug build (disable all optimizations, use standard math)
debug: CFLAGS += -DUSE_STANDARD_MATH
debug: CFLAGS := $(filter-out -DUSE_FAST_GAIN_SMOOTHING -DUSE_SHARED_XI_RATIO -DUSE_OPTIMIZED_MIN_BUFFER -DUSE_OPTIMIZED_E1 -DUSE_SINGLE_CLAMP -DUSE_INCREMENTAL_MIN,$(CFLAGS))
debug: dirs $(TARGET)
	@echo "Debug build complete (standard math, no optimizations): $(TARGET)"

# Clean
clean:
	rm -rf $(OBJ_DIR) $(BIN_DIR)
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

lib: dirs $(OBJS)
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

parity: dirs $(OBJS) $(OBJ_DIR)/parity_runner.o | ac_lib
	$(LINK) $(CFLAGS) -o $(PARITY_TARGET) $(OBJS) $(OBJ_DIR)/parity_runner.o $(AC_LIB) $(LDFLAGS)
	@echo "Build complete: $(PARITY_TARGET)"

$(OBJ_DIR)/parity_runner.o: $(EXAMPLE_DIR)/parity_runner.c
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

mem: dirs $(OBJS) $(OBJ_DIR)/main_mem.o | ac_lib
	$(LINK) $(CFLAGS) -o $(MEM_TARGET) $(OBJS) $(OBJ_DIR)/main_mem.o $(AC_LIB) $(LDFLAGS)
	@echo "Static-memory build complete: $(MEM_TARGET)"

$(OBJ_DIR)/main_mem.o: $(EXAMPLE_DIR)/main_mem.c
	$(CC) $(CFLAGS) -c -o $@ $<

# Help
help:
	@echo "MMSE-LSA Denoiser Build System"
	@echo ""
	@echo "Targets:"
	@echo "  all      - Build the denoiser executable (default)"
	@echo "  mem      - Build the static-memory example (bin/denoise_mem)"
	@echo "  parity   - Build the Python<->C parity runner (bin/parity_runner)"
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

.PHONY: all dirs clean install uninstall test lib help debug parity mem ac_lib
