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

CC  ?= gcc
CXX ?= c++
AR      ?= ar
RANLIB  ?= ranlib
BACKEND ?= kiss

# CFG_SIG payload-coverage placeholders (round-3 review B01): CXXFLAGS/
# CPPFLAGS/EXTRA_LDFLAGS/NO_STDIO are not consumed by this Makefile today
# (this repo has no C++ TUs of its own, and no NO_STDIO-gated code path),
# but the CFG_SIG payload below unconditionally includes them so the
# payload string has the same stable shape as audio_common's and AEC's, and
# so a future use of any of them here keys builds correctly instead of
# silently aliasing with a build that didn't set it. DEBUG is real here
# (see the "Default optimizations" section below) -- resolved before that
# section runs, and before CFG_SIG.
CXXFLAGS      ?=
CPPFLAGS      ?=
EXTRA_LDFLAGS ?=
NO_STDIO      ?= 0
DEBUG         ?= 0

# Locate audio_common: normal checkout has it as a sibling of this repo
# (../../audio_common from c_impl/). The second candidate covers this repo being
# consumed as a git submodule two levels deeper (e.g. Audio_ALG/lib/nr/c_impl/ ->
# .../lib/nr/../../audio_common == ../../../../audio_common from c_impl/).
AC_DIR ?= $(firstword $(wildcard ../../audio_common ../../../../audio_common))

CFLAGS = -Wall -Wextra -O2 -std=gnu99
CFLAGS += -I./include -I./example -I$(AC_DIR)/include
CFLAGS += $(EXTRA_CFLAGS)

# The NE10 archive contains one C++ translation unit (NE10's generic-radix FFT
# kernel), so linking a binary against it needs the C++ runtime. Mirror
# audio_common's own Makefile: use the C++ driver to link when BACKEND=ne10 (all
# of NR's own sources stay plain C either way — only the LINK driver changes).
LINK = $(CC)
LDFLAGS_EXTRA =
ifeq ($(BACKEND),ne10)
  LINK = $(CXX)
  LDFLAGS_EXTRA = -lc++
endif

# =============================================================================
# Default optimizations (mathematically equivalent, 100% bit-exact) vs DEBUG
# (round-3 review B01: DEBUG resolved BEFORE CFG_SIG, replacing the old
# `debug: CFLAGS += -DUSE_STANDARD_MATH; debug: CFLAGS := $(filter-out ...)`
# target-specific-variable pair. That old scheme mutated CFLAGS only in the
# recipe's own target-specific scope, AFTER CFG_SIG had already hashed the
# un-mutated CFLAGS -- a debug build's objects were compiled with
# -DUSE_STANDARD_MATH (and without the six USE_* optimizations) but keyed as
# if they weren't, silently sharing a directory with a same-flags non-debug
# build. Resolving DEBUG via this ifeq, BEFORE CFG_SIG is computed further
# below, means the flag choice is baked into CFLAGS itself before hashing,
# so a debug build gets its own directory like any other distinct config.
# `make debug` now just delegates: `$(MAKE) DEBUG=1 all`.)
# =============================================================================
ifeq ($(DEBUG),0)
CFLAGS += -DUSE_FAST_GAIN_SMOOTHING
CFLAGS += -DUSE_SHARED_XI_RATIO
CFLAGS += -DUSE_OPTIMIZED_MIN_BUFFER
CFLAGS += -DUSE_OPTIMIZED_E1
CFLAGS += -DUSE_SINGLE_CLAMP
CFLAGS += -DUSE_INCREMENTAL_MIN
else
CFLAGS += -DUSE_STANDARD_MATH
endif

# =============================================================================
# Build Configuration Flags (pass via EXTRA_CFLAGS)
# =============================================================================
#
# USE_STANDARD_MATH - Use standard math library functions (for debugging)
#   When defined: Uses expf(), logf(), sqrtf(), log10f(), powf()
#   When not defined: Uses fast LUT+Taylor approximations
#   Now selected via `make debug` (DEBUG=1), not EXTRA_CFLAGS -- see above.
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

LDFLAGS = -lm $(LDFLAGS_EXTRA)
LDFLAGS += $(EXTRA_LDFLAGS)

# -Werror opt-in for this repo's OWN sources (default off; CI can flip it on
# with `make WERROR=1`). Like AEC, NR compiles no vendored TUs itself (FFT +
# fast_math are vendored inside audio_common), so every object built by this
# Makefile is "our code" -- no separate warning isolation is needed here.
WERROR ?= 0
ifeq ($(WERROR),1)
  CFLAGS += -Werror
endif

.DEFAULT_GOAL := all

# =============================================================================
# Consumer two-phase audio_common resolution (round-3 review B01)
# =============================================================================
# Same design as AEC's Makefile (see that file for the full writeup this
# comment summarises): the old `ac_lib: $(MAKE) -C $(AC_DIR) BACKEND=$(BACKEND)
# lib` order-only prerequisite + a hardcoded `AC_LIB = $(AC_DIR)/bin/$(BACKEND)/
# libaudio_common.a` forwarded only BACKEND to the producer sub-make and
# hardcoded a flat path that no longer exists (audio_common's own bin/ is now
# CFG_SIG-keyed). The fix is a two-phase recursive-make dispatch driven by
# whether AC_LIB (the resolved absolute archive path) is already known:
# phase 1 (AC_LIB unset) queries audio_common's `print-lib-path` (forwarding
# this invocation's exact BACKEND/WERROR/CC/CXX/EXTRA_CFLAGS/NO_STDIO) and
# re-invokes itself with AC_LIB set; phase 2 (AC_LIB known) defines the real
# rules, with $(AC_LIB) as a NORMAL (not order-only) prerequisite so relinking
# happens iff its mtime actually advanced. `lib` (this repo's own
# libmmse_lsa.a -- denoiser/MCRA/SPP core only, no FFT/audio_common code)
# needs none of this and lives entirely outside the dispatch, further down.
#
# `make -n`: see AEC's Makefile comment for why the dispatch recipe's
# sub-`make` calls are genuinely spawned even under `make -n` (GNU Make
# always executes, never merely prints, a recipe line that textually
# mentions $(MAKE)) yet still create zero files (verified empirically): -n
# propagates to every child `make` via MAKEFLAGS regardless of how it was
# invoked, so each child's own recipes are themselves just printed.
AC_FWD = BACKEND=$(BACKEND) WERROR=$(WERROR) CC='$(CC)' CXX='$(CXX)' EXTRA_CFLAGS='$(EXTRA_CFLAGS)' NO_STDIO=$(NO_STDIO)

ifeq ($(AC_LIB),)
.PHONY: all mem parity test-config
all mem parity test-config:
	+@ac="$$($(MAKE) -s --no-print-directory -C $(AC_DIR) $(AC_FWD) print-lib-path)"; \
	 test -n "$$ac" || { echo "FATAL: could not resolve audio_common archive path (AC_DIR=$(AC_DIR) -- is audio_common present as a sibling of this repo?)" >&2; exit 1; }; \
	 $(MAKE) --no-print-directory $@ AC_LIB="$$ac"
else
# Producer-identity component of this consumer's own CFG_SIG (see AEC's
# Makefile for the full rationale): the LAST path component of $(AC_LIB)'s
# directory (e.g. "kiss-2139547423"), never the full (absolute) path.
AC_PRODUCER_SIG := $(notdir $(patsubst %/,%,$(dir $(AC_LIB))))
endif

# --- Hash-keyed object/binary directory + full-coverage CFG_SIG ------------
# obj/<backend>-<sig>/ AND (round-3 review B01) bin/<backend>-<sig>/ -- see
# audio_common's Makefile for the full design rationale (identical design,
# applied here). BIN_DIR used to be flat (`bin`), so an ne10 build after a
# kiss build -- or two same-backend builds differing only in EXTRA_CFLAGS/
# WERROR/DEBUG, or a stale mtime from a differently-flagged prior build --
# could silently deliver the wrong `denoise_wav`/`libmmse_lsa.a`/etc. to
# whatever last happened to write that flat path. Payload coverage
# (USER-MANDATED): CC CXX AR RANLIB CFLAGS CXXFLAGS CPPFLAGS LDFLAGS
# EXTRA_CFLAGS EXTRA_LDFLAGS BACKEND WERROR NO_STDIO DEBUG, PLUS (consumer-
# specific) AC_PRODUCER_SIG.
#
# Must be defined after CFLAGS/LDFLAGS are fully assembled (DEBUG-vs-default
# optimizations, WERROR, LDFLAGS_EXTRA) and after the AC_LIB ifeq/else above
# resolves AC_PRODUCER_SIG, but before the first rule below that mentions
# $(OBJ_DIR)/$(BIN_DIR)/anything derived from them -- GNU Make expands a
# rule's target/prerequisite list immediately when parsed, not deferred like
# a recipe body.
#
# Deliberately NOT $(strip)'d (false-miss OK, false-hit never -- see
# audio_common's Makefile). cksum (POSIX) computes the hash.
CFG_SIG_PAYLOAD := CC=$(CC) CXX=$(CXX) AR=$(AR) RANLIB=$(RANLIB) CFLAGS=$(CFLAGS) CXXFLAGS=$(CXXFLAGS) CPPFLAGS=$(CPPFLAGS) LDFLAGS=$(LDFLAGS) EXTRA_CFLAGS=$(EXTRA_CFLAGS) EXTRA_LDFLAGS=$(EXTRA_LDFLAGS) BACKEND=$(BACKEND) WERROR=$(WERROR) NO_STDIO=$(NO_STDIO) DEBUG=$(DEBUG) AC_PRODUCER_SIG=$(AC_PRODUCER_SIG)
CFG_SIG := $(shell printf '%s' "$(CFG_SIG_PAYLOAD)" | cksum | cut -d' ' -f1)

# Directories
SRC_DIR = src
EXAMPLE_DIR = example
TEST_DIR = test
OBJ_ROOT = obj
OBJ_DIR = $(OBJ_ROOT)/$(BACKEND)-$(CFG_SIG)
BIN_DIR = bin/$(BACKEND)-$(CFG_SIG)

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

# --- CFG_SIG collision guard + directory creation (round-3 review B01) -----
# See audio_common's Makefile for the full design writeup (identical
# mechanism, applied here).
.PHONY: _cfg_guard
_cfg_guard:
	@mkdir -p $(OBJ_DIR) $(BIN_DIR)
	@for d in $(OBJ_DIR) $(BIN_DIR); do \
	  m="$$d/config.manifest"; \
	  if [ -f "$$m" ]; then \
	    old="$$(cat "$$m")"; \
	    if [ "$$old" != "$(CFG_SIG_PAYLOAD)" ]; then \
	      echo "FATAL: CFG_SIG collision or coverage gap in $$m" >&2; \
	      echo "  CFG_SIG=$(CFG_SIG)" >&2; \
	      echo "  stored : $$old" >&2; \
	      echo "  current: $(CFG_SIG_PAYLOAD)" >&2; \
	      exit 1; \
	    fi; \
	  else \
	    tmp="$$d/.config.manifest.tmp.$$$$"; \
	    printf '%s\n' "$(CFG_SIG_PAYLOAD)" > "$$tmp"; \
	    mv -f "$$tmp" "$$m"; \
	  fi; \
	done

# Compile source files (-MD -MP: round-3 review B01 header dependency
# tracking -- see audio_common's Makefile; included near the bottom of this
# file via `-include $(wildcard $(OBJ_DIR)/*.d)`).
$(OBJ_DIR)/%.o: $(SRC_DIR)/%.c | _cfg_guard
	$(CC) $(CFLAGS) -MD -MP -c -o $@ $<

# Compile example files
$(OBJ_DIR)/%.o: $(EXAMPLE_DIR)/%.c | _cfg_guard
	$(CC) $(CFLAGS) -MD -MP -c -o $@ $<

# Build static library (denoiser/MCRA/SPP core only — link $(AC_LIB) separately
# for the FFT backend, same as the binaries above). No audio_common archive
# is linked into libmmse_lsa.a, so (per the two-phase design above) this is a
# real rule living entirely outside the AC_LIB dispatch.
LIB_TARGET = $(BIN_DIR)/libmmse_lsa.a

.PHONY: lib
lib: $(LIB_TARGET)

$(LIB_TARGET): $(OBJS) | _cfg_guard
	$(AR) rc $@ $(OBJS)
	$(RANLIB) $@
	@echo "Static library built: $@"

# =============================================================================
# Phase 2 real rules: only defined once AC_LIB is known (see the dispatch
# block above). $(AC_LIB): FORCE always re-invokes audio_common's own build
# (a no-op if it's already up to date), but only touches $(AC_LIB)'s mtime
# if audio_common really rebuilt something, so the binaries below only
# relink when it did.
# =============================================================================
ifneq ($(AC_LIB),)
.PHONY: all FORCE
all: $(TARGET)

FORCE:

$(AC_LIB): FORCE
	+$(MAKE) -C $(AC_DIR) $(AC_FWD) lib
	@test -f '$@' || { echo "ERROR: audio_common did not produce $@ (query/build divergence -- only BACKEND/WERROR/CC/CXX/EXTRA_CFLAGS/NO_STDIO overrides are supported)"; exit 1; }

$(TARGET): $(OBJS) $(EXAMPLE_OBJS) $(AC_LIB) | _cfg_guard
	$(LINK) $(CFLAGS) -o $@ $(OBJS) $(EXAMPLE_OBJS) $(AC_LIB) $(LDFLAGS)
	@echo "Build complete: $@"

# =============================================================================
# Python<->C parity runner (drives mmse_lsa_process_gain on dumped spectra)
# Built separately from denoise_wav (both have their own main()).
# Honors EXTRA_CFLAGS, so:  make parity            -> fast-math
#                           make debug parity       -> std-math (or: make parity DEBUG=1)
# See tools/parity_nr.py for the Python side.
# =============================================================================
.PHONY: parity
PARITY_TARGET = $(BIN_DIR)/parity_runner
parity: $(PARITY_TARGET)

$(PARITY_TARGET): $(OBJS) $(OBJ_DIR)/parity_runner.o $(AC_LIB) | _cfg_guard
	$(LINK) $(CFLAGS) -o $@ $(OBJS) $(OBJ_DIR)/parity_runner.o $(AC_LIB) $(LDFLAGS)
	@echo "Build complete: $@"

$(OBJ_DIR)/parity_runner.o: $(EXAMPLE_DIR)/parity_runner.c | _cfg_guard
	$(CC) $(CFLAGS) -MD -MP -c -o $@ $<

# =============================================================================
# Static-memory build: the NR engine + MCRA/SPP + FFT allocate ALL state from
# caller-provided memory — zero malloc/free on the audio path. Links the
# static-memory example (example/main_mem.c) against the SAME objects as
# denoise_wav (the malloc path and the static path are always both compiled in
# now — see mmse_lsa_get_mem_size()/mmse_lsa_init() — so there is no separate
# object set to keep from mixing, unlike the old compile-time-gated build).
# Honors EXTRA_CFLAGS, e.g.:  make mem EXTRA_CFLAGS="-DUSE_STANDARD_MATH"
# FFT backends: both KISS and NE10 are 100% no-malloc on the static path
#       (make mem BACKEND=ne10) since audio_common's vendored NE10 patch
#       (+P0003 hardening) — handle, work buffers, AND the R2C/C2R twiddle
#       cfg are all carved from the caller pool via ne10_fft_init_r2c_float32_ext,
#       so fft_init() is heap-free end to end; the per-frame audio path was
#       always malloc-free either way.
# =============================================================================
.PHONY: mem
MEM_TARGET = $(BIN_DIR)/denoise_mem
mem: $(MEM_TARGET)

$(MEM_TARGET): $(OBJS) $(OBJ_DIR)/main_mem.o $(AC_LIB) | _cfg_guard
	$(LINK) $(CFLAGS) -o $@ $(OBJS) $(OBJ_DIR)/main_mem.o $(AC_LIB) $(LDFLAGS)
	@echo "Static-memory build complete: $@"

$(OBJ_DIR)/main_mem.o: $(EXAMPLE_DIR)/main_mem.c | _cfg_guard
	$(CC) $(CFLAGS) -MD -MP -c -o $@ $<

# =============================================================================
# Config-validation / alignment-guard regression tests (F05/F07 remediation:
# overflow-checked get_mem_size size arithmetic + sample_rate/framing/L/
# num_init_frames bounds + misaligned-pool-base rejection). Standalone runner,
# no external test framework — see test/test_config_validation.c. Builds
# against the same objects as denoise_wav and runs itself; a non-zero exit
# (any failed check) fails the `make test-config` recipe.
# =============================================================================
.PHONY: test-config
TEST_TARGET = $(BIN_DIR)/test_config_validation
test-config: $(TEST_TARGET)
	./$(TEST_TARGET)

$(TEST_TARGET): $(OBJS) $(OBJ_DIR)/test_config_validation.o $(AC_LIB) | _cfg_guard
	$(LINK) $(CFLAGS) -o $@ $(OBJS) $(OBJ_DIR)/test_config_validation.o $(AC_LIB) $(LDFLAGS)
	@echo "Build complete: $@"

$(OBJ_DIR)/test_config_validation.o: $(TEST_DIR)/test_config_validation.c | _cfg_guard
	$(CC) $(CFLAGS) -MD -MP -c -o $@ $<
endif

# --- Query targets (round-3 review B01) -------------------------------------
# Report THIS invocation's own build identity (empty AC_PRODUCER_SIG unless
# AC_LIB was explicitly passed in). To get the exact path `make all` (or
# `make mem`/`parity`/`test-config`) would produce, resolve AC_LIB the same
# way phase 1 does and pass it explicitly:
#   ac=$$(make -s -C ../../audio_common BACKEND=$$B print-lib-path)
#   make -s BACKEND=$$B print-bin-dir AC_LIB="$$ac"
.PHONY: print-bin-dir print-obj-dir print-lib-path
print-bin-dir:
	@echo $(abspath $(BIN_DIR))
print-obj-dir:
	@echo $(abspath $(OBJ_DIR))
print-lib-path:
	@echo $(abspath $(LIB_TARGET))

# =============================================================================
# publish: immutable per-config release under dist/ (round-3 review B01) --
# same design as audio_common's/AEC's publish (see audio_common's Makefile
# for the full writeup). `publish` needs $(AC_LIB), so it goes through the
# same two-phase dispatch as all/mem/parity/test-config when AC_LIB isn't
# already known.
# =============================================================================
PUBLISH_ARTIFACTS = $(LIB_TARGET) $(TARGET)
DIST_BACKEND_DIR  = dist/$(BACKEND)
DIST_REL_DIR      = $(DIST_BACKEND_DIR)/$(CFG_SIG)
DIST_LOCK         = dist/.lock.$(BACKEND)

ifeq ($(AC_LIB),)
.PHONY: publish
publish:
	+@ac="$$($(MAKE) -s --no-print-directory -C $(AC_DIR) $(AC_FWD) print-lib-path)"; \
	 test -n "$$ac" || { echo "FATAL: could not resolve audio_common archive path" >&2; exit 1; }; \
	 $(MAKE) --no-print-directory publish AC_LIB="$$ac"
else
.PHONY: publish
publish: $(PUBLISH_ARTIFACTS)
	@mkdir -p dist; \
	if ! mkdir "$(DIST_LOCK)" 2>/dev/null; then \
	  echo "FATAL: publish lock $(DIST_LOCK) already held (concurrent 'make publish BACKEND=$(BACKEND)'?)" >&2; \
	  exit 1; \
	fi; \
	trap 'rmdir "$(DIST_LOCK)" 2>/dev/null' EXIT INT TERM; \
	set -e; \
	commit="$$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"; \
	dateutc="$$(date -u +%Y-%m-%dT%H:%M:%SZ)"; \
	mkdir -p "$(DIST_BACKEND_DIR)"; \
	tmp="$(DIST_BACKEND_DIR)/$(CFG_SIG).tmp"; \
	rm -rf "$$tmp"; mkdir -p "$$tmp"; \
	cp $(PUBLISH_ARTIFACTS) "$$tmp/"; \
	shas="$$( cd "$$tmp" && for f in *; do shasum -a 256 "$$f"; done )"; \
	{ echo "repo=nr"; \
	  echo "backend=$(BACKEND)"; \
	  echo "cfg_sig=$(CFG_SIG)"; \
	  echo "producer_cfg_sig=$(AC_PRODUCER_SIG)"; \
	  echo "cc=$(CC)"; echo "cxx=$(CXX)"; \
	  echo "cflags=$(CFLAGS)"; \
	  echo "extra_cflags=$(EXTRA_CFLAGS)"; \
	  echo "werror=$(WERROR)"; echo "no_stdio=$(NO_STDIO)"; echo "debug=$(DEBUG)"; \
	  echo "git_commit=$$commit"; echo "date_utc=$$dateutc"; \
	  echo "$$shas"; \
	} > "$$tmp/MANIFEST.txt"; \
	rm -rf "$(DIST_REL_DIR)"; \
	mv "$$tmp" "$(DIST_REL_DIR)"; \
	ln -s "$(CFG_SIG)" "$(DIST_BACKEND_DIR)/.current.tmp"; \
	mv -f "$(DIST_BACKEND_DIR)/.current.tmp" "$(DIST_BACKEND_DIR)/current"; \
	echo "nr: published $(BACKEND)/$(CFG_SIG) -> $(DIST_BACKEND_DIR)/current"
endif

# debug delegates to `all` with DEBUG=1 (round-3 review B01 -- see the
# "Default optimizations vs DEBUG" section above for why this replaced the
# old target-specific-variable CFLAGS mutation).
debug:
	+@$(MAKE) DEBUG=1 all
	@echo "Debug build complete (standard math, no optimizations)"

# Clean
clean:
	rm -rf $(OBJ_ROOT) bin
	@echo "Clean complete"

# Install (copy to /usr/local/bin) -- resolves this invocation's own denoise_wav
# via the two-phase dispatch (needs AC_LIB), same as `all`.
ifeq ($(AC_LIB),)
install:
	+@ac="$$($(MAKE) -s --no-print-directory -C $(AC_DIR) $(AC_FWD) print-lib-path)"; \
	 $(MAKE) --no-print-directory install AC_LIB="$$ac"
else
install: $(TARGET)
	cp $(TARGET) /usr/local/bin/
	@echo "Installed to /usr/local/bin/denoise_wav"
endif

# Uninstall
uninstall:
	rm -f /usr/local/bin/denoise_wav
	@echo "Uninstalled"

# Test with sample file (requires test.wav in current directory)
ifeq ($(AC_LIB),)
test:
	+@ac="$$($(MAKE) -s --no-print-directory -C $(AC_DIR) $(AC_FWD) print-lib-path)"; \
	 $(MAKE) --no-print-directory test AC_LIB="$$ac"
else
test: $(TARGET)
	@if [ -f test.wav ]; then \
		./$(TARGET) test.wav test_out.wav; \
	else \
		echo "No test.wav found. Create a test file or run:"; \
		echo "  $(TARGET) <input.wav> <output.wav>"; \
	fi
endif

# Help
help:
	@echo "MMSE-LSA Denoiser Build System"
	@echo ""
	@echo "Targets:"
	@echo "  all      - Build the denoiser executable (default)"
	@echo "  mem      - Build the static-memory example (denoise_mem)"
	@echo "  parity   - Build the Python<->C parity runner (parity_runner)"
	@echo "  test-config - Build + run config-validation/alignment-guard tests"
	@echo "  lib      - Build static library"
	@echo "  publish  - Copy this build's artifacts to dist/<backend>/<config-hash>/ + update dist/<backend>/current"
	@echo "  clean    - Remove build artifacts (dist/ survives -- publish is a deliberate release)"
	@echo "  install  - Install to /usr/local/bin"
	@echo "  uninstall - Remove from /usr/local/bin"
	@echo "  test     - Run test (requires test.wav)"
	@echo "  help     - Show this help"
	@echo ""
	@echo "Build Configurations:"
	@echo "  make                                          - Standard build (KISS FFT, fast math)"
	@echo "  make BACKEND=ne10                             - NE10 R2C/C2R build (ARM NEON, embedded deliverable)"
	@echo "  make debug                                    - Debug build (DEBUG=1, matches Python output)"
	@echo "  make EXTRA_CFLAGS=\"-DUSE_FAST_PERCENTILE\"    - Optimized build (all approximations)"
	@echo "  make WERROR=1                                  - Opt-in: -Werror for this repo's own sources"
	@echo ""
	@echo "Objects/binaries live in obj|bin/<backend>-<config-hash>/ -- switching"
	@echo "BACKEND, EXTRA_CFLAGS, WERROR, or DEBUG always lands in a fresh directory"
	@echo "automatically; no manual clean needed, and two differently-configured"
	@echo "builds can run concurrently in this same tree. Run \`make print-bin-dir\`"
	@echo "(same flags as your build) to locate this invocation's own artifacts, or"
	@echo "\`make publish\` for a stable dist/<backend>/current/ handoff path."
	@echo ""
	@echo "Flags:"
	@echo "  USE_STANDARD_MATH   - now selected via \`make debug\` (DEBUG=1), not EXTRA_CFLAGS"
	@echo "  USE_FAST_PERCENTILE - Use mean*0.17 approximation instead of exact percentile"
	@echo ""
	@echo "Memory usage:"
	@echo "  Without USE_FAST_PERCENTILE: +20KB for exact percentile buffer"
	@echo "  With USE_FAST_PERCENTILE: No extra memory"
	@echo ""
	@echo "After building:"
	@echo "  ./bin/<backend>-<config-hash>/denoise_wav input.wav output.wav"

.PHONY: dirs clean install uninstall test help
dirs: _cfg_guard

# --- Header dependency tracking (round-3 review B01) ------------------------
# See audio_common's Makefile for the full rationale. $(wildcard ...) makes
# this evaluate to nothing (not an error) before any objects exist yet for
# this CFG_SIG.
-include $(wildcard $(OBJ_DIR)/*.d)
