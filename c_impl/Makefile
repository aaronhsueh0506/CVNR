# ANR Makefile
#
# =============================================================================
# FFT backend
# =============================================================================
# FFT and fast math come from ../audiolib/common (prebuilt static archive libaudio_common.a) behind
# one public API (fft_wrapper.h). The NE10 implementation follows the compiler target. BACKEND stays a
# variable because it names the keyed obj/bin directories and is forwarded to audiolib.
# =============================================================================

CC  ?= gcc
CXX ?= c++
AR      ?= ar
RANLIB  ?= ranlib
BACKEND ?= ne10
ifneq ($(BACKEND),ne10)
$(error BACKEND must be ne10 (got '$(BACKEND)'): ne10 is the only FFT backend)
endif

# Announce the resolved backend on every build. print-* goals are skipped: their output is
# consumed through command substitution and must stay free of extra stdout.
ifeq ($(filter print-%,$(MAKECMDGOALS)),)
$(info NR: FFT backend = $(BACKEND))
endif

# CXXFLAGS applies to the C++ API smoke test; the production library is C.
# CPPFLAGS and NO_STDIO remain payload placeholders. Empty appends also
# expose environment overrides to the validation guard.
CXXFLAGS      +=
CPPFLAGS      +=
EXTRA_LDFLAGS ?=
NO_STDIO      ?= 0
DEBUG         ?= 0

# DEBUG must be exactly 0 or 1. A value inherited from the environment (for example "release")
# would otherwise select the standard-math debug path without the production optimizations.
# The check compares literal strings: $(filter) treats a multi-word value or '%' as a pattern list.
ifneq ($(DEBUG),0)
ifneq ($(DEBUG),1)
$(error DEBUG must be exactly 0 or 1 (got DEBUG='$(DEBUG)') -- pass DEBUG=0 \
  (default: fast-math + the six production optimizations, same as a bare \
  `make`) or DEBUG=1 (same as `make debug`: standard-math, optimizations \
  off). Any other value is rejected, including one inherited from an exported \
  DEBUG environment variable)
endif
endif

# TOOLCHAIN_CHECK=0 skips the CC/CXX -dumpmachine target-coherence guard in
# _cfg_guard below. Participates in CFG_SIG, so a
# guard-skipped build can never alias a guarded one.
TOOLCHAIN_CHECK ?= 1

# Publish knobs (full description in audiolib's Makefile); none is part of CFG_SIG.
#   DIST_ROOT                where `make publish` writes releases.
#   HOSTCC                   host compiler for the symlink-swap helper (never $(CC), which may be a
#                            cross compiler).
#   ALLOW_DIRTY_PUBLISH      =1 admits uncommitted tracked changes in this or the audiolib checkout.
#   ALLOW_UNTRACKED_PUBLISH  =1 admits untracked, non-ignored files in either checkout.
#   Both are recorded in the attestation; a checkout without git identity is always refused.
#   ATTEST_STAMP             test-only override of the UTC stamp in the attestation file name.
DIST_ROOT ?= dist
HOSTCC    ?= cc
ALLOW_DIRTY_PUBLISH ?= 0
ALLOW_UNTRACKED_PUBLISH ?= 0
ATTEST_STAMP ?=

SIMD ?= 1
ifneq ($(words $(SIMD)),1)
$(error SIMD must be exactly 0 or 1, got '$(SIMD)')
endif
ifneq ($(filter-out 0 1,$(SIMD)),)
$(error SIMD must be exactly 0 or 1, got '$(SIMD)')
endif
ifeq ($(SIMD),0)
SIMD_CFLAGS := -DSIMD_KERNELS_FORCE_SCALAR
else
SIMD_CFLAGS :=
endif

# Locate audiolib: a sibling of this repo (../../audiolib/common from c_impl/), or two levels
# deeper when this repo is a git submodule (Audio_ALG/lib/nr/c_impl/ -> ../../../../audiolib/common).
COMMON_DIR ?= $(firstword $(wildcard ../../audiolib/common ../../../../audiolib/common))

CFLAGS = -Wall -Wextra -O2 -std=gnu99
CFLAGS += -I./include -I./example -I$(COMMON_DIR)/include -I$(COMMON_DIR)
CFLAGS += $(EXTRA_CFLAGS)
CFLAGS += $(SIMD_CFLAGS)

# The NE10 archive contains one C++ translation unit, so linking uses the C++ driver (all NR
# sources stay plain C). The driver supplies the C++ runtime. LINK is part of CFG_SIG.
LINK = $(CXX)

# =============================================================================
# Default optimizations versus DEBUG. DEBUG is resolved before CFG_SIG is computed, so the flag
# set belongs to the build identity and a debug build gets its own directory.
# `make debug` delegates to `$(MAKE) DEBUG=1 all`.
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
# Build configuration flags (pass through EXTRA_CFLAGS)
# =============================================================================
#
# USE_STANDARD_MATH         libm expf/logf/sqrtf/log10f/powf instead of the fast LUT/Taylor exp,
#                           minimax log and target sqrt. Selected by `make debug` (DEBUG=1), which
#                           also drops the six USE_* optimizations below;
#                           EXTRA_CFLAGS="-DUSE_STANDARD_MATH" keeps them.
# USE_FAST_PERCENTILE       Initial noise floor from mean * 0.23 instead of the exact 30th
#                           percentile (saves only the quickselect scratch: the startup rows share
#                           the minimum ring's storage in the denoiser's tracker).
# USE_FAST_GAIN_SMOOTHING   Clamp in the log domain and skip the exp->log round trip.
#                           Formula-equivalent only: with approximate math it is not bit-exact to
#                           the disabled path.
# USE_SHARED_XI_RATIO       SPP outputs v = xi/(1+xi)*gamma and the gain stage reuses it.
# USE_OPTIMIZED_MIN_BUFFER  Noise-tracker minimum ring laid out [freq_idx * L + frame_idx]
#                           (contiguous per frequency) instead of [frame_idx * n_freqs + freq_idx].
# USE_OPTIMIZED_E1          E1(v): test v > 1.0 first and compute log10 once for v <= 1.0.
# USE_SINGLE_CLAMP          Skip the final [g_min, 1.0] clamp that the log-domain clamp covers.
# USE_INCREMENTAL_MIN       Track the noise-tracker minimum incrementally: O(1) on average, a full
#                           rescan only when the evicted value was the minimum.
#
# Common builds:
#   make debug                                  standard math, no optimizations (closest to Python)
#   make                                        fast math and the six optimizations
#   make EXTRA_CFLAGS="-DUSE_FAST_PERCENTILE"   additionally the fast percentile approximation
#
# =============================================================================

LDFLAGS = -lm
LDFLAGS += $(EXTRA_LDFLAGS)

# -Werror opt-in for this repo's own sources (`make WERROR=1`, default off). Every object built
# here is this repo's code: FFT and fast math are built in audiolib.
WERROR ?= 0
ifeq ($(WERROR),1)
  CFLAGS += -Werror
endif

# Keep multiply/add ordering stable in C and the C++ smoke test: no implicit FMA (checked by
# audiolib/common/scripts/audit_fp_contract.sh), and audiolib's guarded AArch64 sqrtf calls lower
# to FSQRT without an errno-checking libm fallback.
# FP_POLICY is a plain literal defined here, ahead of the override checks below, so that its
# origin is final when they query it. It is appended to CFLAGS last: after every other append and
# before CFG_SIG_PAYLOAD is computed.
FP_POLICY := -ffp-contract=off -fno-math-errno

# FP_ALLOWED_CHARS_RE is the character allow-list of the flag check further down. It is a plain
# literal defined here for the same reason as FP_POLICY.
FP_ALLOWED_CHARS_RE := ^[A-Za-z0-9_./=,+ -]*$$
#
# --- Command-line override rejection -----------------------------------------
# A command-line or `make -e` override of one of these variables would silently drop this
# Makefile's own appends (FP policy, USE_* defines, include paths, -lm) or widen the allow-list,
# while still producing artifacts. EXTRA_CFLAGS / EXTRA_LDFLAGS are the supported hooks.
$(foreach v,CFLAGS CXXFLAGS CPPFLAGS LDFLAGS FP_POLICY FP_ALLOWED_CHARS_RE,\
  $(if $(findstring command,$(origin $(v)))$(findstring override,$(origin $(v))),\
    $(error $(v) cannot be overridden (origin: $(origin $(v))) -- it would silently drop this Makefile's own flag appends (FP policy, USE_* defines, include paths); use EXTRA_CFLAGS / EXTRA_LDFLAGS instead)))

# FP policy conflict detection: reject -Ofast, -ffast-math and -ffp-contract=<x> in the fully
# assembled CFLAGS, CXXFLAGS and CPPFLAGS (EXTRA_CFLAGS and environment values included). It runs
# before FP_POLICY is appended and before CFG_SIG is computed, so a rejected build never creates
# an obj/bin directory. $(filter) matches whole words: a harmless token such as -DNOTE=-Ofastness
# is accepted, which a $(findstring) substring test would reject.
FP_INPUT_FLAGS := $(CFLAGS) $(CXXFLAGS) $(CPPFLAGS)

# --- Link flags ---------------------------------------------------------------
# LDFLAGS is embedded in every link recipe the same way CFLAGS is in compile recipes, so the
# character-safety checks below run on the union of CFLAGS, CXXFLAGS, CPPFLAGS and LDFLAGS. The
# FP-semantic check stays on the compile flags: -Ofast and friends mean nothing to the linker.
SHELL_SAFE_INPUT_FLAGS := $(FP_INPUT_FLAGS) $(LDFLAGS)

# Make cannot parse shell quoting: EXTRA_CFLAGS="'-Ofast'" keeps its quote characters, so the
# whole-word $(filter) misses -Ofast while the shell strips the quotes and the compiler sees it.
# The supported input is therefore plain, unquoted, whitespace-separated argv tokens, enforced by
# an allow-list (a deny-list misses globs, tilde, redirection and process substitution). Make has
# no regex function, so it shells out to grep -E with the text single-quoted; a Make-native
# single-quote test comes first and gates that embedding.
ifneq ($(findstring ',$(SHELL_SAFE_INPUT_FLAGS)),)
$(error FP policy conflict: CFLAGS/CXXFLAGS/CPPFLAGS/LDFLAGS/EXTRA_CFLAGS/EXTRA_LDFLAGS contains a single-quote character; this repo requires plain, unquoted, whitespace-separated compiler/linker argv tokens built only from the allowed character set (see the allow-list below) -- a single quote specifically must be rejected by this Make-native check BEFORE the allow-list's own $(shell) call can safely single-quote-embed the rest of the text)
endif

# The allow-list: letters, digits, underscore, dot, slash, equals, comma, plus, minus and space
# (the token separator). It covers every flag this Makefile uses (-O2, -Wall/-Wextra,
# -std=gnu99, -I paths, the USE_* defines, -lm), value-carrying defines (-DNAME=value) and linker
# pass-through such as -Wl,-rpath,dir. LC_ALL=C pins the bracket ranges to ASCII order. The
# expression is FP_ALLOWED_CHARS_RE, defined near the top of this file.
SHELL_SAFE_ALLOWLIST_RC := $(shell printf '%s' '$(SHELL_SAFE_INPUT_FLAGS)' | LC_ALL=C grep -Eq '$(FP_ALLOWED_CHARS_RE)'; echo $$?)
ifneq ($(SHELL_SAFE_ALLOWLIST_RC),0)
# Diagnostic only, on the error path: delete every allowed character and list the remaining ones
# so that the message names the offending characters.
SHELL_SAFE_DISALLOWED_CHARS := $(shell printf '%s' '$(SHELL_SAFE_INPUT_FLAGS)' | LC_ALL=C tr -d 'A-Za-z0-9_./=,+ -' | fold -w1 | LC_ALL=C sort -u | tr -d '\n')
$(error FP policy conflict: CFLAGS/CXXFLAGS/CPPFLAGS/LDFLAGS/EXTRA_CFLAGS/EXTRA_LDFLAGS contains a character outside the allowed set [A-Za-z0-9_./=,+- ] (letters/digits/underscore/dot/slash/equals/comma/plus/minus, plus space as the token separator) -- disallowed character(s) found: "$(SHELL_SAFE_DISALLOWED_CHARS)"; this repo requires plain, unquoted, whitespace-separated compiler/linker argv tokens built only from that set -- remove/replace the disallowed character(s) shown above in CFLAGS/CXXFLAGS/CPPFLAGS/LDFLAGS/EXTRA_CFLAGS/EXTRA_LDFLAGS)
endif

FP_CONFLICT_FLAGS := $(filter -Ofast -ffast-math -ffp-contract=%,$(FP_INPUT_FLAGS))
ifneq ($(FP_CONFLICT_FLAGS),)
$(error FP policy conflict: CFLAGS/CXXFLAGS/CPPFLAGS/EXTRA_CFLAGS contains $(FP_CONFLICT_FLAGS); this repo pins -ffp-contract=off; remove $(FP_CONFLICT_FLAGS) from CFLAGS/CXXFLAGS/CPPFLAGS/EXTRA_CFLAGS)
endif

# Override rejection for the remaining internal check variables. They are computed from the
# assembled flags, so the check must run after their assignment (their origin is final only then).
# A command-line override of any of them would turn the checks above into no-ops.
# SHELL_SAFE_DISALLOWED_CHARS is diagnostic text only and is not protected.
$(foreach v,FP_INPUT_FLAGS SHELL_SAFE_INPUT_FLAGS SHELL_SAFE_ALLOWLIST_RC FP_CONFLICT_FLAGS,\
  $(if $(findstring command,$(origin $(v)))$(findstring override,$(origin $(v))),\
    $(error $(v) cannot be overridden (origin: $(origin $(v))) -- it would silently defeat the FP-policy/shell-safety allow-list/conflict checks above, leaving the real CFLAGS/CXXFLAGS/CPPFLAGS/LDFLAGS content unvalidated; this variable is internal to those checks and has no supported external use)))

# FP_POLICY is defined near the top of this file; only its append to CFLAGS (last) belongs here.
CFLAGS    += $(FP_POLICY)

.DEFAULT_GOAL := all

# =============================================================================
# audiolib resolution (two-phase dispatch)
# =============================================================================
# Phase 1 (COMMON_LIB unset): ask audiolib for its archive path (`print-lib-path`, forwarding this
# invocation's BACKEND/SIMD/WERROR/CC/CXX/EXTRA_CFLAGS/NO_STDIO/TOOLCHAIN_CHECK) and re-invoke
# make with COMMON_LIB set. Phase 2 (COMMON_LIB known): the real rules, with $(COMMON_LIB) as a normal
# prerequisite so that relinking happens iff the archive's mtime advanced. `lib` (libanr.a, no
# audiolib code) needs neither phase and lives outside the dispatch.
#
# Under `make -n` the dispatch recipe's sub-makes still run (a recipe that mentions $(MAKE) always
# executes); -n propagates through MAKEFLAGS, so each child only prints its recipes.
COMMON_FWD = BACKEND=$(BACKEND) SIMD=$(SIMD) WERROR=$(WERROR) CC='$(CC)' CXX='$(CXX)' EXTRA_CFLAGS='$(EXTRA_CFLAGS)' NO_STDIO=$(NO_STDIO) TOOLCHAIN_CHECK=$(TOOLCHAIN_CHECK)

ifeq ($(COMMON_LIB),)
.PHONY: all mem parity test-config test-config-parity test-reconfigure test-noise-restart test-scene-change test-shared-startup test-api-cpp bench-anr
all mem parity test-config test-config-parity test-reconfigure test-noise-restart test-scene-change test-shared-startup test-api-cpp bench-anr:
	+@ac="$$($(MAKE) -s --no-print-directory -C $(COMMON_DIR) $(COMMON_FWD) print-lib-path)"; \
	 test -n "$$ac" || { echo "FATAL: could not resolve audiolib archive path (COMMON_DIR=$(COMMON_DIR) -- is audiolib present as a sibling of this repo?)" >&2; exit 1; }; \
	 $(MAKE) --no-print-directory $@ COMMON_LIB="$$ac"
else
# Producer identity in this repo's CFG_SIG: the last path component of $(COMMON_LIB)'s directory
# (for example ne10-2139547423), never the absolute path.
COMMON_PRODUCER_SIG := $(notdir $(patsubst %/,%,$(dir $(COMMON_LIB))))
endif

# Directories. They precede CFG_SIG_PAYLOAD because SRCS references SRC_DIR; OBJ_DIR and BIN_DIR
# are recursive assignments that reference CFG_SIG before its own := line.
SRC_DIR = src
EXAMPLE_DIR = example
TEST_DIR = test
# OBJ_ROOT / BIN_ROOT: where the keyed obj/bin trees live (default obj/ and bin/). A placement
# knob only, not part of CFG_SIG; the isolation tests build into scratch directories with it.
OBJ_ROOT ?= obj
BIN_ROOT ?= bin
OBJ_DIR = $(OBJ_ROOT)/$(BACKEND)-$(CFG_SIG)
BIN_DIR = $(BIN_ROOT)/$(BACKEND)-$(CFG_SIG)

# Library sources (the gain calculation is in anr.c). FFT and fast math come from audiolib
# through $(COMMON_LIB). SRCS is part of CFG_SIG_PAYLOAD: adding or removing a source keys to a fresh
# obj/bin directory.
SRCS = $(SRC_DIR)/anr.c \
       $(SRC_DIR)/noise_estimator.c \
       $(SRC_DIR)/spp_estimator.c

# --- Hash-keyed object/binary directories and CFG_SIG ---------------------------
# obj/<backend>-<sig>/ and bin/<backend>-<sig>/ (design as in audiolib's Makefile): builds that
# differ in backend, flags, WERROR, DEBUG or producer never share a directory. The payload covers
# CC CXX AR RANLIB LINK CFLAGS CXXFLAGS CPPFLAGS LDFLAGS EXTRA_CFLAGS EXTRA_LDFLAGS BACKEND SIMD
# WERROR NO_STDIO DEBUG TOOLCHAIN_CHECK COMMON_PRODUCER_SIG, the sorted SRCS and CC_TARGET_SIG (the
# effective pointer/FP/ISA predefines, since one CC command can select a different SDK via PATH).
# It is defined after the flags are final and before the first rule that mentions OBJ_DIR or
# BIN_DIR, because Make expands a rule's target list at parse time. The payload is not $(strip)ped
# (a false miss is acceptable, a false hit is not).
override CC_TARGET_SIG := $(shell sh $(COMMON_DIR)/scripts/target_abi_signature.sh $(CC) $(CPPFLAGS) $(CFLAGS))
CFG_SIG_PAYLOAD := CC_TARGET_SIG=$(CC_TARGET_SIG) CC=$(CC) CXX=$(CXX) AR=$(AR) RANLIB=$(RANLIB) LINK=$(LINK) CFLAGS=$(CFLAGS) CXXFLAGS=$(CXXFLAGS) CPPFLAGS=$(CPPFLAGS) LDFLAGS=$(LDFLAGS) EXTRA_CFLAGS=$(EXTRA_CFLAGS) EXTRA_LDFLAGS=$(EXTRA_LDFLAGS) BACKEND=$(BACKEND) SIMD=$(SIMD) WERROR=$(WERROR) NO_STDIO=$(NO_STDIO) DEBUG=$(DEBUG) TOOLCHAIN_CHECK=$(TOOLCHAIN_CHECK) COMMON_PRODUCER_SIG=$(COMMON_PRODUCER_SIG) SRCS=$(sort $(SRCS))
CFG_SIG := $(shell printf '%s' "$(CFG_SIG_PAYLOAD)" | cksum | cut -d' ' -f1)

EXAMPLE_SRCS = $(EXAMPLE_DIR)/main.c

# Object files
OBJS = $(patsubst $(SRC_DIR)/%.c,$(OBJ_DIR)/%.o,$(SRCS))
EXAMPLE_OBJS = $(patsubst $(EXAMPLE_DIR)/%.c,$(OBJ_DIR)/%.o,$(EXAMPLE_SRCS))

# Target binary
TARGET = $(BIN_DIR)/denoise_wav

# --- CFG_SIG collision guard and directory creation ----------------------------
# Same mechanism as audiolib's Makefile.
.PHONY: _cfg_guard
_cfg_guard:
	@test -n "$(CC_TARGET_SIG)" && test "$(CC_TARGET_SIG)" != unavailable || { \
	  echo "FATAL: cannot determine compiler target; CC preprocessing with the configured flags must succeed." >&2; \
	  exit 1; }
	@if [ "$(TOOLCHAIN_CHECK)" = "1" ]; then \
	  cc_m="$$($(CC) -dumpmachine 2>/dev/null)"; cxx_m="$$($(CXX) -dumpmachine 2>/dev/null)"; \
	  if [ -z "$$cc_m" ] || [ "$$cc_m" != "$$cxx_m" ]; then \
	    echo "FATAL: CC/CXX compile for different targets (CC='$(CC)' -> '$$cc_m', CXX='$(CXX)' -> '$$cxx_m')." >&2; \
	    echo "  BACKEND=ne10 links a C++ TU (audiolib's NE10 archive); pass the FULL toolchain:" >&2; \
	    echo "    make BACKEND=ne10 CC=aarch64-linux-gnu-gcc CXX=aarch64-linux-gnu-g++ AR=aarch64-linux-gnu-ar RANLIB=aarch64-linux-gnu-ranlib" >&2; \
	    echo "  (TOOLCHAIN_CHECK=0 skips this check; it participates in CFG_SIG.)" >&2; \
	    exit 1; \
	  fi; \
	fi
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

# Compile source files. -MD -MP track header dependencies (included at the end of this file).
$(OBJ_DIR)/%.o: $(SRC_DIR)/%.c | _cfg_guard
	$(CC) $(CFLAGS) -MD -MP -c -o $@ $<

# Compile example files
$(OBJ_DIR)/%.o: $(EXAMPLE_DIR)/%.c | _cfg_guard
	$(CC) $(CFLAGS) -MD -MP -c -o $@ $<

# Static library: denoiser/noise tracker/SPP core only; link $(COMMON_LIB) separately for the FFT.
# No audiolib archive goes into libanr.a, so this rule lives outside the COMMON_LIB dispatch.
LIB_TARGET = $(BIN_DIR)/libanr.a

.PHONY: lib
lib: $(LIB_TARGET)

# Fresh archive: build into a PID-suffixed temporary file and rename it into place, never
# `ar rc` onto an existing archive (a removed source's member would stay). Concurrent builds of
# the same configuration each write their own temporary file; the final mv is atomic.
$(LIB_TARGET): $(OBJS) | _cfg_guard
	t="$@.tmp.$$$$" && rm -f "$$t" && $(AR) rc "$$t" $(OBJS) && $(RANLIB) "$$t" && mv -f "$$t" $@
	@echo "Static library built: $@"

# =============================================================================
# Phase 2 rules, defined once COMMON_LIB is known. $(COMMON_LIB): FORCE always re-invokes audiolib's
# own build, which touches the archive only if it rebuilt something, so the binaries below
# relink only then.
# =============================================================================
ifneq ($(COMMON_LIB),)
.PHONY: all FORCE
all: $(TARGET)

FORCE:

$(COMMON_LIB): FORCE
	+$(MAKE) -C $(COMMON_DIR) $(COMMON_FWD) lib
	@test -f '$@' || { echo "ERROR: audiolib did not produce $@ (query/build divergence -- supported forwarded controls are BACKEND/SIMD/WERROR/CC/CXX/EXTRA_CFLAGS/NO_STDIO/TOOLCHAIN_CHECK)"; exit 1; }

$(TARGET): $(OBJS) $(EXAMPLE_OBJS) $(COMMON_LIB) | _cfg_guard
	$(LINK) $(CFLAGS) -o $@ $(OBJS) $(EXAMPLE_OBJS) $(COMMON_LIB) $(LDFLAGS)
	@echo "Build complete: $@"

# =============================================================================
# Python<->C parity runner (drives anr_process_gain on dumped spectra)
# Built separately from denoise_wav (both have their own main()).
# Honors EXTRA_CFLAGS, so:  make parity            -> fast-math
#                           make debug parity       -> std-math (or: make parity DEBUG=1)
# See python/tools/parity_nr.py for the Python side.
# =============================================================================
.PHONY: parity
PARITY_TARGET = $(BIN_DIR)/parity_runner
parity: $(PARITY_TARGET)

$(PARITY_TARGET): $(OBJS) $(OBJ_DIR)/parity_runner.o $(COMMON_LIB) | _cfg_guard
	$(LINK) $(CFLAGS) -o $@ $(OBJS) $(OBJ_DIR)/parity_runner.o $(COMMON_LIB) $(LDFLAGS)
	@echo "Build complete: $@"

$(OBJ_DIR)/parity_runner.o: $(EXAMPLE_DIR)/parity_runner.c | _cfg_guard
	$(CC) $(CFLAGS) -MD -MP -c -o $@ $<

# =============================================================================
# Static-memory build: the engine, noise tracker/SPP and FFT take all state from caller-provided
# memory (no malloc/free on the audio path). Links example/main_mem.c against the same objects
# as denoise_wav; the heap and static paths are both always compiled in (anr_get_mem_size() and
# anr_init()). Honors EXTRA_CFLAGS, e.g.:  make mem EXTRA_CFLAGS="-DUSE_STANDARD_MATH"
# The FFT is heap-free on the static path: the handle, work buffers and R2C/C2R twiddle
# configuration are carved from the caller pool (ne10_fft_init_r2c_float32_ext in audiolib's
# vendored NE10).
# =============================================================================
.PHONY: mem
MEM_TARGET = $(BIN_DIR)/denoise_mem
mem: $(MEM_TARGET)

$(MEM_TARGET): $(OBJS) $(OBJ_DIR)/main_mem.o $(COMMON_LIB) | _cfg_guard
	$(LINK) $(CFLAGS) -o $@ $(OBJS) $(OBJ_DIR)/main_mem.o $(COMMON_LIB) $(LDFLAGS)
	@echo "Static-memory build complete: $@"

$(OBJ_DIR)/main_mem.o: $(EXAMPLE_DIR)/main_mem.c | _cfg_guard
	$(CC) $(CFLAGS) -MD -MP -c -o $@ $<

# =============================================================================
# Config-validation and alignment-guard tests: overflow-checked get_mem_size arithmetic,
# sample_rate/framing/L/num_init_frames bounds and misaligned-pool rejection. Standalone runner
# (test/test_config_validation.c) built against the same objects as denoise_wav; a non-zero exit
# fails the recipe.
# =============================================================================
.PHONY: test-config test-reconfigure test-noise-restart test-scene-change test-shared-startup
TEST_TARGET = $(BIN_DIR)/test_config_validation
TEST_RECFG_TARGET = $(BIN_DIR)/test_reconfigure
TEST_RESTART_TARGET = $(BIN_DIR)/test_noise_restart
TEST_SCENE_TARGET = $(BIN_DIR)/test_scene_change_margin
TEST_SHARED_TARGET = $(BIN_DIR)/test_shared_startup
test-config: $(TEST_TARGET)
	"$(abspath $(TEST_TARGET))"

test-reconfigure: $(TEST_RECFG_TARGET)
	"$(abspath $(TEST_RECFG_TARGET))"

test-noise-restart: $(TEST_RESTART_TARGET)
	"$(abspath $(TEST_RESTART_TARGET))"

test-scene-change: $(TEST_SCENE_TARGET)
	"$(abspath $(TEST_SCENE_TARGET))"

test-shared-startup: $(TEST_SHARED_TARGET)
	"$(abspath $(TEST_SHARED_TARGET))"

$(TEST_TARGET): $(OBJS) $(OBJ_DIR)/test_config_validation.o $(COMMON_LIB) | _cfg_guard
	$(LINK) $(CFLAGS) -o $@ $(OBJS) $(OBJ_DIR)/test_config_validation.o $(COMMON_LIB) $(LDFLAGS)
	@echo "Build complete: $@"

$(TEST_RECFG_TARGET): $(OBJS) $(OBJ_DIR)/test_reconfigure.o $(COMMON_LIB) | _cfg_guard
	$(LINK) $(CFLAGS) -o $@ $(OBJS) $(OBJ_DIR)/test_reconfigure.o $(COMMON_LIB) $(LDFLAGS)
	@echo "Build complete: $@"


$(OBJ_DIR)/test_config_validation.o: $(TEST_DIR)/test_config_validation.c | _cfg_guard
	$(CC) $(CFLAGS) -MD -MP -c -o $@ $<

$(OBJ_DIR)/test_reconfigure.o: $(TEST_DIR)/test_reconfigure.c | _cfg_guard
	$(CC) $(CFLAGS) -MD -MP -c -o $@ $<

# Noise-tracker recovery after digital silence (see test/test_noise_restart.c).
$(TEST_RESTART_TARGET): $(OBJS) $(OBJ_DIR)/test_noise_restart.o $(COMMON_LIB) | _cfg_guard
	$(LINK) $(CFLAGS) -o $@ $(OBJS) $(OBJ_DIR)/test_noise_restart.o $(COMMON_LIB) $(LDFLAGS)
	@echo "Build complete: $@"

$(OBJ_DIR)/test_noise_restart.o: $(TEST_DIR)/test_noise_restart.c | _cfg_guard
	$(CC) $(CFLAGS) -MD -MP -c -o $@ $<

# Scene-change flatness decision just above and below the threshold (see
# test/test_scene_change_margin.c).
$(TEST_SCENE_TARGET): $(OBJS) $(OBJ_DIR)/test_scene_change_margin.o $(COMMON_LIB) | _cfg_guard
	$(LINK) $(CFLAGS) -o $@ $(OBJS) $(OBJ_DIR)/test_scene_change_margin.o $(COMMON_LIB) $(LDFLAGS)
	@echo "Build complete: $@"

$(OBJ_DIR)/test_scene_change_margin.o: $(TEST_DIR)/test_scene_change_margin.c | _cfg_guard
	$(CC) $(CFLAGS) -MD -MP -c -o $@ $<

# Shared startup/ring storage of the integrated tracker versus the standalone tracker (see
# test/test_shared_startup.c).
$(TEST_SHARED_TARGET): $(OBJS) $(OBJ_DIR)/test_shared_startup.o $(COMMON_LIB) | _cfg_guard
	$(LINK) $(CFLAGS) -o $@ $(OBJS) $(OBJ_DIR)/test_shared_startup.o $(COMMON_LIB) $(LDFLAGS)
	@echo "Build complete: $@"

$(OBJ_DIR)/test_shared_startup.o: $(TEST_DIR)/test_shared_startup.c | _cfg_guard
	$(CC) $(CFLAGS) -MD -MP -c -o $@ $<

# =============================================================================
# Python<->C effective-config parity dump: prints the canonical AnrConfig for every shipped
# (grid, strength) combination so that ../python/tests/test_config_parity.py can compare it with
# process_audio.py's build_v3_2_base_params() + apply_strength() composition. See the header of
# test/test_config_parity.c.
# =============================================================================
.PHONY: test-config-parity
TEST_PARITY_TARGET = $(BIN_DIR)/test_config_parity
test-config-parity: $(TEST_PARITY_TARGET)
	"$(abspath $(TEST_PARITY_TARGET))"

$(TEST_PARITY_TARGET): $(OBJS) $(OBJ_DIR)/test_config_parity.o $(COMMON_LIB) | _cfg_guard
	$(LINK) $(CFLAGS) -o $@ $(OBJS) $(OBJ_DIR)/test_config_parity.o $(COMMON_LIB) $(LDFLAGS)
	@echo "Build complete: $@"

$(OBJ_DIR)/test_config_parity.o: $(TEST_DIR)/test_config_parity.c | _cfg_guard
	$(CC) $(CFLAGS) -MD -MP -c -o $@ $<

# Verify the public C API through a C++ caller.
.PHONY: test-api-cpp
TEST_CPP_TARGET = $(BIN_DIR)/test_api_cpp
test-api-cpp: $(TEST_CPP_TARGET)
	"$(abspath $(TEST_CPP_TARGET))"

$(TEST_CPP_TARGET): $(OBJS) $(OBJ_DIR)/test_api_cpp.o $(COMMON_LIB) | _cfg_guard
	$(CXX) $(filter-out -std=gnu99,$(CFLAGS)) $(CXXFLAGS) $(FP_POLICY) -o $@ $(OBJS) $(OBJ_DIR)/test_api_cpp.o $(COMMON_LIB) $(LDFLAGS)

$(OBJ_DIR)/test_api_cpp.o: $(TEST_DIR)/test_api_cpp.cpp | _cfg_guard
	$(CXX) $(filter-out -std=gnu99,$(CFLAGS)) $(CXXFLAGS) -std=c++17 $(FP_POLICY) -MD -MP -c -o $@ $<

# Per-hop cost of anr_process() and anr_process_gain() on three grids and two strengths. Host-only
# timing of the build selected by BACKEND/SIMD/CC; run it on an otherwise idle machine.
.PHONY: bench-anr
BENCH_TARGET = $(BIN_DIR)/bench_anr
BENCH_ARGS ?=
bench-anr: $(BENCH_TARGET)
	"$(abspath $(BENCH_TARGET))" $(BENCH_ARGS)

$(BENCH_TARGET): $(OBJS) $(OBJ_DIR)/bench_anr.o $(COMMON_LIB) | _cfg_guard
	$(LINK) $(CFLAGS) -o $@ $(OBJS) $(OBJ_DIR)/bench_anr.o $(COMMON_LIB) $(LDFLAGS)
	@echo "Build complete: $@"

$(OBJ_DIR)/bench_anr.o: $(TEST_DIR)/bench_anr.c | _cfg_guard
	$(CC) $(CFLAGS) -MD -MP -c -o $@ $<
endif

# Compare release kernels with the scalar reference using temporary native binaries.
PYTHON ?= python3
.PHONY: test-bit-exact
test-bit-exact:
	$(PYTHON) ../python/tools/test_bit_exact.py --backend $(BACKEND) --simd $(SIMD) \
	  --ac-dir "$(abspath $(COMMON_DIR))" --cc "$(CC)" --cxx "$(CXX)"

# --- Query targets -----------------------------------------------------------
# Report THIS invocation's own build identity (empty COMMON_PRODUCER_SIG unless
# COMMON_LIB was explicitly passed in). To get the exact path `make all` (or
# `make mem`/`parity`/`test-config`) would produce, resolve COMMON_LIB the same
# way phase 1 does and pass it explicitly:
#   ac=$$(make -s -C ../../audiolib/common BACKEND=$$B print-lib-path)
#   make -s BACKEND=$$B print-bin-dir COMMON_LIB="$$ac"
.PHONY: print-bin-dir print-obj-dir print-lib-path
# print-bin-dir dispatches through the same phase-1 producer resolution as
# the build goals, so a bare `make -s print-bin-dir` prints the exact
# directory the binaries are delivered into (NR's binaries only exist in the
# resolved-producer directory). Passing COMMON_LIB= explicitly skips the query.
ifeq ($(COMMON_LIB),)
print-bin-dir:
	+@ac="$$($(MAKE) -s --no-print-directory -C $(COMMON_DIR) $(COMMON_FWD) print-lib-path)"; \
	 test -n "$$ac" || { echo "FATAL: could not resolve audiolib archive path (COMMON_DIR=$(COMMON_DIR))" >&2; exit 1; }; \
	 $(MAKE) -s --no-print-directory print-bin-dir COMMON_LIB="$$ac"
else
print-bin-dir:
	@echo $(abspath $(BIN_DIR))
endif
print-obj-dir:
	@echo $(abspath $(OBJ_DIR))
print-lib-path:
	@echo $(abspath $(LIB_TARGET))

# =============================================================================
# publish: immutable, content-addressed release under $(DIST_ROOT), same layout and semantics as
# audiolib's publish (see that Makefile): deterministic MANIFEST, append-only ATTEST/ provenance,
# rename-atomic `current` swap through the swapln helper built with $(HOSTCC), and a lock taken
# before the prerequisite build. `publish` is the locked driver; _publish_impl is internal and goes
# through the same two-phase COMMON_LIB dispatch as `all`. Both checkouts (this repo and COMMON_DIR)
# must have a git identity and be clean unless ALLOW_DIRTY_PUBLISH / ALLOW_UNTRACKED_PUBLISH admit
# them; the attestation records each checkout's commit and dirty / untracked state. Attestations
# are unsigned: traceability, not authenticity.
# =============================================================================
PUBLISH_ARTIFACTS = $(LIB_TARGET) $(TARGET)
DIST_BACKEND_DIR  = $(DIST_ROOT)/$(BACKEND)
DIST_LOCK         = $(DIST_ROOT)/.lock.$(BACKEND)

.PHONY: publish _publish_impl
# Dry-run guard. The recipe mentions $(MAKE), so GNU make runs it under -n, -q and -t as well; the
# word scan of MAKEFLAGS below keeps all three free of side effects (no DIST_ROOT, lock, stage or
# MANIFEST/ATTEST writes):
#   -t  print a note and exit 0 (recursing would apply touch semantics to the outputs).
#   -q  exit 1 (publish is phony, so it would always run).
#   -n  recurse into _publish_impl only; the child inherits -n and merely prints its commands.
# Bundled short flags may be the first word ("n", "sn") or separate dashed words; "--" ends the
# flags; command-line variable overrides (which can contain n, q or t) are skipped.
publish:
	+@has_n=0; has_q=0; has_t=0; \
	for w in $(MAKEFLAGS); do \
	  case "$$w" in --) break ;; --*|*=*) continue ;; -n|-q|-t) ;; -*) continue ;; esac; \
	  case "$$w" in *n*) has_n=1 ;; esac; \
	  case "$$w" in *q*) has_q=1 ;; esac; \
	  case "$$w" in *t*) has_t=1 ;; esac; \
	done; \
	if [ "$$has_t" = 1 ]; then echo "publish: -t (touch) is a no-op here -- publish is an action, not a build product; nothing was touched"; exit 0; fi; \
	if [ "$$has_q" = 1 ]; then exit 1; fi; \
	if [ "$$has_n" = 1 ]; then exec $(MAKE) --no-print-directory _publish_impl; fi; \
	mkdir -p $(DIST_ROOT); \
	if ! mkdir "$(DIST_LOCK)" 2>/dev/null; then \
	  echo "FATAL: publish lock $(DIST_LOCK) already held (concurrent 'make publish BACKEND=$(BACKEND)'?)" >&2; \
	  exit 1; \
	fi; \
	trap 'rmdir "$(DIST_LOCK)" 2>/dev/null' EXIT INT TERM; \
	$(MAKE) --no-print-directory _publish_impl

ifeq ($(COMMON_LIB),)
.PHONY: _publish_impl
_publish_impl:
	+@ac="$$($(MAKE) -s --no-print-directory -C $(COMMON_DIR) $(COMMON_FWD) print-lib-path)"; \
	 test -n "$$ac" || { echo "FATAL: could not resolve audiolib archive path" >&2; exit 1; }; \
	 $(MAKE) --no-print-directory _publish_impl COMMON_LIB="$$ac"
else
.PHONY: _publish_impl
_publish_impl: $(PUBLISH_ARTIFACTS)
	@set -e; \
	work="$$(mktemp -d)"; \
	tmp="$(DIST_BACKEND_DIR)/.stage.$$$$"; \
	trap 'rm -rf "$$tmp" "$$work"' EXIT INT TERM; \
	hash_untracked() { \
	  LC_ALL=C sort | while IFS= read -r p; do \
	    fp="$$1$$p"; \
	    ph="$$(printf '%s' "$$p" | shasum -a 256 | cut -d' ' -f1)"; \
	    [ "$${#ph}" -eq 64 ] || { printf 'X %s\n' "$$p"; continue; }; \
	    if [ -L "$$fp" ]; then \
	      tgt="$$(readlink "$$fp")" || { printf 'X %s\n' "$$p"; continue; }; \
	      th="$$(printf '%s' "$$tgt" | shasum -a 256 | cut -d' ' -f1)"; \
	      [ "$${#th}" -eq 64 ] || { printf 'X %s\n' "$$p"; continue; }; \
	      printf 'L %s %s\n' "$$ph" "$$th"; \
	    elif [ -f "$$fp" ]; then \
	      m="$$(stat -f '%Lp' "$$fp" 2>/dev/null || stat -c '%a' "$$fp" 2>/dev/null)"; \
	      ch="$$(shasum -a 256 "$$fp" 2>/dev/null | cut -d' ' -f1)"; \
	      { [ -n "$$m" ] && [ "$${#ch}" -eq 64 ]; } || { printf 'X %s\n' "$$p"; continue; }; \
	      printf 'F %s %s %s\n' "$$m" "$$ph" "$$ch"; \
	    else printf 'X %s\n' "$$p"; fi; \
	  done; \
	}; \
	commit="$$(git rev-parse HEAD 2>/dev/null || echo unknown)"; \
	if [ "$$commit" = "unknown" ]; then \
	  echo "FATAL: publish refused -- nr has no git identity here (not a git checkout)." >&2; \
	  echo "  Without an identity the attestation cannot name the source state OR enumerate untracked" >&2; \
	  echo "  content, so NO escape hatch admits this." >&2; \
	  echo "  Publish from a real checkout or a scratch clone with a disposable commit instead." >&2; \
	  exit 1; \
	fi; \
	dirty=0; [ -n "$$(git status --porcelain -uno 2>/dev/null)" ] && dirty=1; \
	unt_list="$$(git ls-files --others --exclude-standard 2>/dev/null)"; \
	untracked=0; [ -n "$$unt_list" ] && untracked=1; \
	if [ -n "$(COMMON_DIR)" ] && [ -d "$(COMMON_DIR)" ]; then \
	  ac_commit="$$(git -C $(COMMON_DIR) rev-parse HEAD 2>/dev/null || echo unknown)"; \
	else \
	  ac_commit=unknown; \
	fi; \
	if [ "$$ac_commit" = "unknown" ]; then \
	  echo "FATAL: publish refused -- audiolib (COMMON_DIR=$(COMMON_DIR)) has no git identity here (missing, not a directory, or not a git checkout)." >&2; \
	  echo "  Without an identity the attestation cannot name the source state OR enumerate untracked" >&2; \
	  echo "  content, so NO escape hatch admits this." >&2; \
	  echo "  Point COMMON_DIR at a real audiolib checkout (or a scratch clone with a disposable commit)." >&2; \
	  exit 1; \
	fi; \
	ac_dirty=0; [ -n "$$(git -C $(COMMON_DIR) status --porcelain -uno 2>/dev/null)" ] && ac_dirty=1; \
	ac_unt_list="$$(git -C $(COMMON_DIR) ls-files --others --exclude-standard 2>/dev/null)"; \
	ac_untracked=0; [ -n "$$ac_unt_list" ] && ac_untracked=1; \
	adp=0; [ "$(ALLOW_DIRTY_PUBLISH)" = "1" ] && adp=1; \
	aup=0; [ "$(ALLOW_UNTRACKED_PUBLISH)" = "1" ] && aup=1; \
	if [ "$$adp" != "1" ] && ( [ "$$dirty" = "1" ] || [ "$$ac_dirty" = "1" ] ); then \
	  echo "FATAL: publish refused --" >&2; \
	  [ "$$dirty" = "1" ] && echo "  nr working tree is dirty (uncommitted TRACKED changes)." >&2; \
	  [ "$$ac_dirty" = "1" ] && echo "  audiolib (COMMON_DIR=$(COMMON_DIR)) working tree is dirty (uncommitted TRACKED changes)." >&2; \
	  echo "  Commit (or clone a clean checkout) for a board deliverable, or pass ALLOW_DIRTY_PUBLISH=1" >&2; \
	  echo "  for a dev publish -- the escape hatch is recorded in the attestation." >&2; \
	  exit 1; \
	fi; \
	if [ "$$aup" != "1" ] && ( [ "$$untracked" = "1" ] || [ "$$ac_untracked" = "1" ] ); then \
	  echo "FATAL: publish refused -- untracked (non-ignored) files present (they can change the artifact without a trace in the tracked diff):" >&2; \
	  if [ "$$untracked" = "1" ]; then \
	    echo "  nr:" >&2; \
	    printf '%s\n' "$$unt_list" | head -5 | sed 's/^/    /' >&2; \
	  fi; \
	  if [ "$$ac_untracked" = "1" ]; then \
	    echo "  audiolib (COMMON_DIR=$(COMMON_DIR)):" >&2; \
	    printf '%s\n' "$$ac_unt_list" | head -5 | sed 's/^/    /' >&2; \
	  fi; \
	  echo "  Track/remove them for a board deliverable, or pass ALLOW_UNTRACKED_PUBLISH=1 -- the escape" >&2; \
	  echo "  hatch is recorded in the attestation with (audiolib_)untracked_tree_sha256 over their exact contents." >&2; \
	  exit 1; \
	fi; \
	ddiff=""; [ "$$dirty" = "1" ] && ddiff="$$(git diff --binary HEAD 2>/dev/null | shasum -a 256 | cut -d' ' -f1)"; \
	ac_ddiff=""; [ "$$ac_dirty" = "1" ] && ac_ddiff="$$(git -C $(COMMON_DIR) diff --binary HEAD 2>/dev/null | shasum -a 256 | cut -d' ' -f1)"; \
	uhash=""; \
	if [ "$$untracked" = "1" ]; then \
	  printf '%s\n' "$$unt_list" | hash_untracked "./" > "$$work/untracked.records"; \
	  if grep -q '^X ' "$$work/untracked.records"; then \
	    echo "FATAL: publish refused -- an untracked path in nr cannot be hashed deterministically (embedded git checkout / special file / I/O failure) and so cannot enter the provenance record:" >&2; \
	    grep '^X ' "$$work/untracked.records" | sed 's/^X /    /' >&2; \
	    exit 1; \
	  fi; \
	  uhash="$$(shasum -a 256 < "$$work/untracked.records" | cut -d' ' -f1)"; \
	fi; \
	ac_uhash=""; \
	if [ "$$ac_untracked" = "1" ]; then \
	  printf '%s\n' "$$ac_unt_list" | hash_untracked "$(COMMON_DIR)/" > "$$work/ac_untracked.records"; \
	  if grep -q '^X ' "$$work/ac_untracked.records"; then \
	    echo "FATAL: publish refused -- an untracked path in audiolib (COMMON_DIR=$(COMMON_DIR)) cannot be hashed deterministically (embedded git checkout / special file / I/O failure) and so cannot enter the provenance record:" >&2; \
	    grep '^X ' "$$work/ac_untracked.records" | sed 's/^X /    /' >&2; \
	    exit 1; \
	  fi; \
	  ac_uhash="$$(shasum -a 256 < "$$work/ac_untracked.records" | cut -d' ' -f1)"; \
	fi; \
	dateutc="$$(date -u +%Y-%m-%dT%H:%M:%SZ)"; \
	stamp='$(ATTEST_STAMP)'; [ -n "$$stamp" ] || stamp="$$(date -u +%Y%m%dT%H%M%SZ)"; \
	$(HOSTCC) -O2 -o "$$work/swapln" $(COMMON_DIR)/tools/atomic_symlink_swap.c || { echo "FATAL: could not build the atomic symlink-swap helper with HOSTCC=$(HOSTCC) (pass HOSTCC=<host compiler>)" >&2; exit 1; }; \
	mkdir -p "$(DIST_BACKEND_DIR)"; \
	rm -rf "$$tmp"; mkdir -p "$$tmp"; \
	cp $(PUBLISH_ARTIFACTS) "$$tmp/"; \
	shas="$$( cd "$$tmp" && for f in *; do shasum -a 256 "$$f"; done )"; \
	content12="$$(printf '%s\n' "$$shas" | sort | shasum -a 256 | cut -c1-12)"; \
	rel_id="$(CFG_SIG)-$$content12"; \
	rel_dir="$(DIST_BACKEND_DIR)/$$rel_id"; \
	{ echo "repo=nr"; \
	  echo "release_id=$$rel_id"; \
	  echo "backend=$(BACKEND)"; \
	  echo "cfg_sig=$(CFG_SIG)"; \
	  echo "producer_cfg_sig=$(COMMON_PRODUCER_SIG)"; \
	  echo "cc=$(CC)"; echo "cxx=$(CXX)"; echo "ar=$(AR)"; echo "ranlib=$(RANLIB)"; echo "link=$(LINK)"; \
	  echo "cflags=$(CFLAGS)"; \
	  echo "extra_cflags=$(EXTRA_CFLAGS)"; \
	  echo "werror=$(WERROR)"; echo "no_stdio=$(NO_STDIO)"; echo "debug=$(DEBUG)"; \
	  echo "$$shas"; \
	} > "$$tmp/MANIFEST.txt"; \
	suffix=""; [ "$$dirty" = "1" ] && suffix="-dirty"; \
	if [ -d "$$rel_dir" ]; then \
	  for f in "$$tmp"/*; do \
	    bn="$$(basename "$$f")"; \
	    cmp -s "$$f" "$$rel_dir/$$bn" || { echo "FATAL: existing release $$rel_id differs from staged content for $$bn (content-address collision, or the stored release/MANIFEST was modified on disk)" >&2; exit 1; }; \
	  done; \
	  rm -rf "$$tmp"; \
	  echo "nr: $$rel_id already published (byte-verified, incl. MANIFEST) -- appending attestation + repointing current"; \
	else \
	  mkdir "$$tmp/ATTEST"; \
	  mv "$$tmp" "$$rel_dir"; \
	fi; \
	mkdir -p "$$rel_dir/ATTEST"; \
	n=1; \
	while :; do \
	  attest_name="attest-$$stamp-$$commit$$suffix-$$(printf '%03d' "$$n").txt"; \
	  { echo "event_id=$${attest_name%.txt}"; \
	    echo "repo=nr"; \
	    echo "release_id=$$rel_id"; \
	    echo "cfg_sig=$(CFG_SIG)"; \
	    echo "backend=$(BACKEND)"; \
	    echo "git_commit=$$commit"; echo "git_dirty=$$dirty"; \
	    [ -n "$$ddiff" ] && echo "dirty_diff_sha256=$$ddiff"; \
	    echo "git_untracked=$$untracked"; \
	    [ -n "$$uhash" ] && echo "untracked_tree_sha256=$$uhash"; \
	    echo "audiolib_git_commit=$$ac_commit"; echo "audiolib_git_dirty=$$ac_dirty"; \
	    [ -n "$$ac_ddiff" ] && echo "audiolib_dirty_diff_sha256=$$ac_ddiff"; \
	    echo "audiolib_git_untracked=$$ac_untracked"; \
	    [ -n "$$ac_uhash" ] && echo "audiolib_untracked_tree_sha256=$$ac_uhash"; \
	    echo "date_utc=$$dateutc"; \
	    echo "allow_dirty_publish=$$adp"; \
	    echo "allow_untracked_publish=$$aup"; \
	  } > "$$work/attest.txt"; \
	  rc=0; "$$work/swapln" --excl-install "$$work/attest.txt" "$$rel_dir/ATTEST/$$attest_name" || rc=$$?; \
	  [ "$$rc" -eq 0 ] && break; \
	  [ "$$rc" -eq 2 ] || { echo "FATAL: could not install attestation $$attest_name" >&2; exit 1; }; \
	  n=$$((n+1)); \
	  [ "$$n" -le 999 ] || { echo "FATAL: 999 attestation name collisions for $$stamp-$$commit (runaway?)" >&2; exit 1; }; \
	done; \
	"$$work/swapln" "$$rel_id" "$(DIST_BACKEND_DIR)/current"; \
	echo "nr: published $(BACKEND)/$$rel_id -> $(DIST_BACKEND_DIR)/current (attested: $$attest_name)"
endif

# =============================================================================
# Python<->C numeric parity tool (test/pyc_parity_nr.sh, ../python/tools/pyc_parity_nr.py).
# `pyc-parity` builds the tool's two C drivers (pyc_gain_driver, pyc_e2e_driver) with this
# invocation's flags, the way `parity` builds parity_runner. The script builds the std-math and the
# shipping configuration, runs the comparison and decides pass/fail; this goal does not run it.
# =============================================================================
.PHONY: pyc-parity
ifeq ($(COMMON_LIB),)
pyc-parity:
	+@ac="$$($(MAKE) -s --no-print-directory -C $(COMMON_DIR) $(COMMON_FWD) print-lib-path)"; \
	 test -n "$$ac" || { echo "FATAL: could not resolve audiolib archive path (COMMON_DIR=$(COMMON_DIR) -- is audiolib present as a sibling of this repo?)" >&2; exit 1; }; \
	 $(MAKE) --no-print-directory $@ COMMON_LIB="$$ac"
else
PYC_PARITY_DIR = $(TEST_DIR)/pyc_parity
PYC_GAIN_TARGET = $(BIN_DIR)/pyc_gain_driver
PYC_E2E_TARGET = $(BIN_DIR)/pyc_e2e_driver
pyc-parity: $(PYC_GAIN_TARGET) $(PYC_E2E_TARGET)

$(PYC_GAIN_TARGET): $(OBJS) $(OBJ_DIR)/pyc_gain_driver.o $(COMMON_LIB) | _cfg_guard
	$(LINK) $(CFLAGS) -o $@ $(OBJS) $(OBJ_DIR)/pyc_gain_driver.o $(COMMON_LIB) $(LDFLAGS)
	@echo "Build complete: $@"

$(PYC_E2E_TARGET): $(OBJS) $(OBJ_DIR)/pyc_e2e_driver.o $(COMMON_LIB) | _cfg_guard
	$(LINK) $(CFLAGS) -o $@ $(OBJS) $(OBJ_DIR)/pyc_e2e_driver.o $(COMMON_LIB) $(LDFLAGS)
	@echo "Build complete: $@"

$(OBJ_DIR)/pyc_gain_driver.o: $(PYC_PARITY_DIR)/pyc_gain_driver.c | _cfg_guard
	$(CC) $(CFLAGS) -MD -MP -c -o $@ $<

$(OBJ_DIR)/pyc_e2e_driver.o: $(PYC_PARITY_DIR)/pyc_e2e_driver.c | _cfg_guard
	$(CC) $(CFLAGS) -MD -MP -c -o $@ $<
endif

# debug delegates to `all` with DEBUG=1 (see "Default optimizations versus DEBUG" above).
debug:
	+@$(MAKE) DEBUG=1 all
	@echo "Debug build complete (standard math, no optimizations)"

# Clean
clean:
	rm -rf $(OBJ_ROOT) $(BIN_ROOT)
	@echo "Clean complete"

# Install (copy to /usr/local/bin) -- resolves this invocation's own denoise_wav
# via the two-phase dispatch (needs COMMON_LIB), same as `all`.
ifeq ($(COMMON_LIB),)
install:
	+@ac="$$($(MAKE) -s --no-print-directory -C $(COMMON_DIR) $(COMMON_FWD) print-lib-path)"; \
	 $(MAKE) --no-print-directory install COMMON_LIB="$$ac"
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
ifeq ($(COMMON_LIB),)
test:
	+@ac="$$($(MAKE) -s --no-print-directory -C $(COMMON_DIR) $(COMMON_FWD) print-lib-path)"; \
	 $(MAKE) --no-print-directory test COMMON_LIB="$$ac"
else
test: $(TARGET)
	@if [ -f test.wav ]; then \
		"$(abspath $(TARGET))" test.wav test_out.wav; \
	else \
		echo "No test.wav found. Create a test file or run:"; \
		echo "  $(TARGET) <input.wav> <output.wav>"; \
	fi
endif

# Help
help:
	@echo "ANR Build System"
	@echo ""
	@echo "Targets:"
	@echo "  all      - Build the denoiser executable (default)"
	@echo "  mem      - Build the static-memory example (denoise_mem)"
	@echo "  parity   - Build the Python<->C parity runner (parity_runner)"
	@echo "  test-config - Build + run config-validation/alignment-guard tests"
	@echo "  test-config-parity - Build + run the canonical-configuration dump used by the Python parity test"
	@echo "  test-reconfigure - Build + run the runtime reconfiguration tests"
	@echo "  test-noise-restart - Build + run the digital-silence noise tracking tests"
	@echo "  test-scene-change - Build + run the scene-change flatness margin test"
	@echo "  test-shared-startup - Build + run the shared startup/ring storage equivalence test"
	@echo "  test-api-cpp - Build + run the C++ header compile/link smoke test"
	@echo "  test-bit-exact - Compare the optimized kernels with the scalar reference (needs python3); also runs the"
	@echo "                   kernel-level tests test_anr_kernels and test_min_ordered_special; test_anr_kernels is the only"
	@echo "                   gate for the ring growth constant and the inert-restart weight; with SIMD=0 it compares scalar with scalar"
	@echo "  bench-anr - Build + run the per-hop cost benchmark (host timing of this build; BENCH_ARGS=\"<passes> <warmup> <hops>\")"
	@echo "  lib      - Build static library"
	@echo "  publish  - Copy this build's artifacts to dist/<backend>/<config-hash>/ + update dist/<backend>/current"
	@echo "  clean    - Remove build artifacts (dist/ survives -- publish is a deliberate release)"
	@echo "  install  - Install to /usr/local/bin"
	@echo "  uninstall - Remove from /usr/local/bin"
	@echo "  test     - Run test (requires test.wav)"
	@echo "  help     - Show this help"
	@echo ""
	@echo "Build Configurations:"
	@echo "  make                                          - Standard build (NE10 FFT, ARM NEON, embedded deliverable, fast math - default)"
	@echo "  make debug                                  - Debug build (DEBUG=1, matches Python output)"
	@echo "  make EXTRA_CFLAGS=\"-DUSE_FAST_PERCENTILE\"    - Optimized build (all approximations)"
	@echo "  make WERROR=1                                  - Opt-in: -Werror for this repo's own sources"
	@echo ""
	@echo "Objects/binaries live in <OBJ_ROOT>|<BIN_ROOT>/<backend>-<config-hash>/ (default obj/bin) -- switching"
	@echo "SIMD, EXTRA_CFLAGS, WERROR, or DEBUG always lands in a fresh directory"
	@echo "automatically; no manual clean needed, and two differently-configured"
	@echo "builds can run concurrently in this same tree. Run \`make print-bin-dir\`"
	@echo "(same flags as your build) to locate this invocation's own artifacts, or"
	@echo "\`make publish\` for a stable dist/<backend>/current/ handoff path."
	@echo ""
	@echo "Flags:"
	@echo "  USE_STANDARD_MATH   - selected via \`make debug\` (DEBUG=1), not EXTRA_CFLAGS"
	@echo "  USE_FAST_PERCENTILE - Use mean*0.23 approximation instead of exact 30th percentile"
	@echo ""
	@echo "Memory usage:"
	@echo "  Without USE_FAST_PERCENTILE: + num_init_frames floats per instance for the percentile scratch"
	@echo "  With USE_FAST_PERCENTILE: No extra memory"
	@echo ""
	@echo "After building:"
	@echo "  ./<BIN_ROOT>/<backend>-<config-hash>/denoise_wav input.wav output.wav (default bin/)"

.PHONY: dirs clean install uninstall test help
dirs: _cfg_guard

# --- Header dependency tracking -----------------------------------------------
# $(wildcard) is empty, not an error, before any object of this CFG_SIG exists.
-include $(wildcard $(OBJ_DIR)/*.d)
