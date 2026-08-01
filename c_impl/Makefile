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

# Announce the resolved backend on every build (same MAKECMDGOALS guard as
# audio_common's own banner: print-bin-dir/print-obj-dir/print-lib-path are
# consumed via `$$(make -s ... print-lib-path)` command substitution
# elsewhere, and this must not add stray stdout to that captured value).
ifeq ($(filter print-%,$(MAKECMDGOALS)),)
$(info NR: FFT backend = $(BACKEND) -- switch with `make BACKEND=kiss` or `make BACKEND=ne10`)
endif

# CFG_SIG payload-coverage placeholders (round-3 review B01): CXXFLAGS/
# CPPFLAGS/EXTRA_LDFLAGS/NO_STDIO are not consumed by this Makefile today
# (this repo has no C++ TUs of its own, and no NO_STDIO-gated code path),
# but the CFG_SIG payload below unconditionally includes them so the
# payload string has the same stable shape as audio_common's and AEC's, and
# so a future use of any of them here keys builds correctly instead of
# silently aliasing with a build that didn't set it. DEBUG is real here
# (see the "Default optimizations" section below) -- resolved before that
# section runs, and before CFG_SIG.
#
# CXXFLAGS and CPPFLAGS are also two of the five names the "Command-line
# override rejection" foreach further below rejects a command-line/`-e`
# override of (a Codex review finding -- the same class of bug
# audio_common's CPPFLAGS had two rounds ago and AEC's CXXFLAGS/CPPFLAGS
# had, both fixed the same way). `?=` only ever assigns when the variable's
# origin is still "undefined" -- if either already has a value from the
# environment, `?=` is a complete no-op (GNU Make never attempts the
# assignment at all), so the origin never flips to "environment override"
# under `make -e` no matter how early this line sits. `+=` fixes this while
# keeping the externally-visible behaviour identical: appending an empty
# string is a no-op on the VALUE (a plain-environment CXXFLAGS/CPPFLAGS
# still folds in normally -- origin becomes "file" -- and still
# participates in CFG_SIG_PAYLOAD unchanged), but `+=` is an unconditional
# assignment ATTEMPT, so under `-e` GNU Make's origin bookkeeping now
# correctly flips it to "environment override", which the foreach rejects.
# See audio_common's/AEC's Makefile for the identical fix and full writeup.
CXXFLAGS      +=
CPPFLAGS      +=
EXTRA_LDFLAGS ?=
NO_STDIO      ?= 0
DEBUG         ?= 0

# DEBUG must be exactly "0" or "1" (confirmed footgun, external review): "?="
# only takes effect when DEBUG is COMPLETELY unset, so a caller whose shell
# environment happens to already export DEBUG to some other value (e.g.
# "release") sails straight past the assignment above and falls through the
# `ifeq ($(DEBUG),0)` below into its else branch -- the USE_STANDARD_MATH
# debug path, silently missing all six production optimizations -- instead
# of getting the standard build the caller actually asked for by typing a
# bare `make`. Reject anything that isn't literally 0 or 1 outright, loudly,
# before that ifeq (and before CFG_SIG, further below) ever sees it.
#
# round-4 review (Codex): the previous `$(filter $(DEBUG),0 1)` form was
# itself bypassable -- $(filter PATTERN...,TEXT) treats its FIRST argument as
# a (possibly multi-word) pattern LIST matched against the second, so a
# two-word DEBUG value (e.g. `make DEBUG='0 1' ...`) became
# `$(filter 0 1,0 1)`, which matches and returns the non-empty "0 1",
# leaving the ifeq-against-empty check FALSE and silently NOT erroring.
# Values containing Make's `%` wildcard are similarly at risk of unintended
# pattern-matching through that mechanism. `ifneq` does literal string
# comparison (no wildcard/list semantics), so two nested exact-equality
# checks -- neither of which can match a multi-word or `%`-bearing value --
# replace the single $(filter)-based check.
ifneq ($(DEBUG),0)
ifneq ($(DEBUG),1)
$(error DEBUG must be exactly 0 or 1 (got DEBUG='$(DEBUG)') -- pass DEBUG=0 \
  (default: fast-math + the six production optimizations, same as a bare \
  `make`) or DEBUG=1 (same as `make debug`: standard-math, optimizations \
  off). Any other value -- including one inherited from a stray exported \
  DEBUG environment variable -- used to silently fall through to the \
  standard-math debug path instead of erroring; it no longer does)
endif
endif

# TOOLCHAIN_CHECK=0 skips the CC/CXX -dumpmachine target-coherence guard in
# _cfg_guard below (round-4 review P1-2). Participates in CFG_SIG, so a
# guard-skipped build can never alias a guarded one.
TOOLCHAIN_CHECK ?= 1

# DIST_ROOT / HOSTCC (round-5 review): where `make publish` writes releases
# (test scripts point this at a throwaway mktemp dir so they never touch the
# real dist/), and the HOST compiler for the publish-time atomic
# symlink-swap helper (never $(CC): that may be a cross compiler). Neither
# is in CFG_SIG -- neither affects what is built. See audio_common's
# Makefile for the full writeups.
#
# ALLOW_DIRTY_PUBLISH (round-6 review P2, scope narrowed in round-7): `make
# publish` REFUSES by default when EITHER this checkout (nr) OR the producer
# audio_common checkout (resolved via AC_DIR) has uncommitted TRACKED
# changes (`git status --porcelain -uno` non-empty) -- a release whose
# ATTEST provenance cannot name the exact source state of BOTH repos that
# produced it is not a board deliverable. ALLOW_DIRTY_PUBLISH=1 is the
# explicit escape hatch for dev publishes; it is recorded in the attestation
# together with a sha256 of `git diff --binary HEAD` for whichever
# checkout(s) are dirty, so the deviation itself is traceable. It covers
# TRACKED changes only -- untracked files have their own dimension below
# (round-7 review: the tracked diff hash says nothing about untracked
# bytes, so lumping the two under one flag let two different untracked
# source states publish with identical provenance). A checkout with NO git
# identity at all (nr itself, or the checkout resolved via AC_DIR --
# including AC_DIR unset, missing, or not a directory) is refused
# UNCONDITIONALLY, in BOTH repos -- neither this knob nor
# ALLOW_UNTRACKED_PUBLISH admits it, because without an identity neither the
# commit nor the untracked enumeration can be named for that checkout
# (provenance is impossible; round-7 Stage 2c: ALLOW_DIRTY_PUBLISH used to
# admit this case, since "unknown" only tripped the dirty `!= 0` check,
# which ALLOW_DIRTY_PUBLISH=1 short-circuited entirely).
#
# ALLOW_UNTRACKED_PUBLISH (round-7 review): publish also REFUSES by default
# when EITHER checkout (nr or the producer audio_common) contains ANY
# untracked, non-ignored file (`git ls-files --others --exclude-standard`
# non-empty; gitignored build output is excluded by design and never part
# of this provenance) -- an untracked source a (possibly dirty) Makefile
# references can change the artifact without leaving a trace in the tracked
# diff. ALLOW_UNTRACKED_PUBLISH=1 is the separate, orthogonal escape hatch;
# it records untracked_tree_sha256 (nr) and/or
# audio_common_untracked_tree_sha256 (producer) in the attestation: sha256
# over sorted FIXED-FIELD per-file records, computed per repo by the shared
# `hash_untracked()` shell function (see the `_publish_impl` recipe body) --
# "L <sha256(path)> <sha256(readlink output)>" for symlinks, "F <mode>
# <sha256(path)> <sha256(content)>" for regular files -- every
# variable-length value is itself hashed, so records concatenate
# unambiguously (raw space-joined path/target strings were collision-prone:
# "a b"->"c" vs "a"->"b c" encoded identically) and any stat/readlink/shasum
# failure downgrades the entry to an X record => FATAL, never an empty hash
# (fail-closed). A path in either checkout that is neither a regular file
# nor a symlink (an embedded git checkout, a fifo) is always refused, named,
# with a diagnostic naming which repo it came from. Neither knob is in
# CFG_SIG: they never change what is built, only whether publish proceeds.
# See audio_common's Makefile for the full single-repo writeup this extends
# to the two-repo (nr + producer) case.
#
# ATTEST_STAMP (round-6 review P2, TEST-ONLY): overrides the UTC timestamp
# embedded in the attestation FILENAME so the isolation tests can
# deterministically force same-second publish collisions and prove the
# no-clobber retry path. Never use it on a real publish -- though note a
# forged stamp is within the already-accepted threat model: attestations
# are unsigned and provide traceability, NOT authenticity against an
# attacker with filesystem access. Not in CFG_SIG or MANIFEST. See
# audio_common's Makefile for the full writeups on both of the above.
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

# Locate audio_common: normal checkout has it as a sibling of this repo
# (../../audio_common from c_impl/). The second candidate covers this repo being
# consumed as a git submodule two levels deeper (e.g. Audio_ALG/lib/nr/c_impl/ ->
# .../lib/nr/../../audio_common == ../../../../audio_common from c_impl/).
AC_DIR ?= $(firstword $(wildcard ../../audio_common ../../../../audio_common))

CFLAGS = -Wall -Wextra -O2 -std=gnu99
CFLAGS += -I./include -I./example -I$(AC_DIR)/include
CFLAGS += $(EXTRA_CFLAGS)
CFLAGS += $(SIMD_CFLAGS)

# The NE10 archive contains one C++ translation unit (NE10's generic-radix FFT
# kernel), so linking a binary against it uses the C++ DRIVER when
# BACKEND=ne10 (all of NR's own sources stay plain C either way — only the
# LINK driver changes). The driver supplies the correct C++ runtime itself
# (libc++ on macOS/clang, libstdc++ on GNU/Linux gcc); the old hardcoded
# `-lc++` alongside it was a macOS-ism (duplicate there, a link error on
# GNU/Linux) and is gone (round-4 review P1-2). LINK participates in CFG_SIG
# below (P2-1).
LINK = $(CC)
ifeq ($(BACKEND),ne10)
  LINK = $(CXX)
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

LDFLAGS = -lm
LDFLAGS += $(EXTRA_LDFLAGS)

# -Werror opt-in for this repo's OWN sources (default off; CI can flip it on
# with `make WERROR=1`). Like AEC, NR compiles no vendored TUs itself (FFT +
# fast_math are vendored inside audio_common), so every object built by this
# Makefile is "our code" -- no separate warning isolation is needed here.
WERROR ?= 0
ifeq ($(WERROR),1)
  CFLAGS += -Werror
endif

# --- FP-contraction policy: unified across all four repos (round-3 review
# B04). This repo has no C++ TUs of its own (CXXFLAGS is a CFG_SIG
# payload-coverage placeholder only, per the comment near the top of this
# file -- nothing here ever compiles a .cpp), so only CFLAGS needs the
# policy flag. Appended here, AFTER every prior CFLAGS append in this file
# (base flags, -I paths, EXTRA_CFLAGS, the DEBUG-vs-default-optimizations
# block, and WERROR just above), and BEFORE CFG_SIG_PAYLOAD is computed
# below -- so it automatically participates in CFG_SIG (no separate payload
# entry needed) and nothing after this line can re-append and override it.
# See audio_common's Makefile for the full cross-repo design writeup (this
# repo's three own TUs -- mmse_lsa_denoiser.c/mcra_noise_estimator.c/
# spp_estimator.c -- include only fast_math.h/fft_wrapper.h, no NEON
# intrinsics, so they are genuinely scalar and expected to disassemble
# fmadd/fmla-free under this flag; see scripts/audit_fp_contract.sh in
# audio_common for the disassembly-level verification).
#
# --- Bare-literal policy flag, defined early (Codex review: `make -e`
# environment-override gap) --------------------------------------------------
# FP_POLICY is a plain, dependency-free `:=` literal (no reference to CFLAGS
# or anything else computed above) that used to be defined much further down
# this file, immediately ahead of CFG_SIG_PAYLOAD -- for a reason that still
# applies and is unaffected by this move (see the "FP-contraction policy"
# comment above: FP_POLICY's CFLAGS append still needs to happen AFTER every
# other CFLAGS append in this file, and BEFORE CFG_SIG_PAYLOAD is computed --
# both still true with only the bare literal relocated here). FP_POLICY is
# ALSO listed in the "Command-line override rejection" foreach directly
# below, and that combination used to be a real gap under `make -e`,
# empirically confirmed: `env FP_POLICY=-ffp-contract=fast make -e -n
# BACKEND=kiss lib` used to sail straight through with no error (rc=0),
# silently dropping -ffp-contract=off from the dry-run compile line (see the
# foreach's own comment for the full mechanism -- $(origin FP_POLICY) only
# flips from plain "environment" to "environment override" once a makefile
# assignment to FP_POLICY has actually been PARSED, which never happened
# before the foreach ran while the bare `:=` sat all the way down at its old
# position, well after this foreach). Duplicating only the bare literal up
# here -- ahead of the foreach in file order -- fixes it; the original site
# further below still holds its OTHER job unchanged (`CFLAGS +=
# $(FP_POLICY)`, appended LAST), so there is exactly one `:=` definition of
# FP_POLICY in this file, just moved. Same fix audio_common/AEC already
# applied to their own Makefiles.
FP_POLICY := -ffp-contract=off

# FP_ALLOWED_CHARS_RE (added alongside the FP-policy allow-list redesign
# below -- replicated from audio_common's/AEC's identical fix, see the
# "REDESIGN" comment further down for the full writeup) is a SECOND bare,
# dependency-free `:=` literal with the exact same `make -e` exposure as
# FP_POLICY above -- it lives here, fully relocated (this is its ONLY
# definition in this file), so its origin is already final by the time the
# foreach below queries it. The regex it holds is documented in full where
# it is actually used (the FP-policy allow-list block, further below).
FP_ALLOWED_CHARS_RE := ^[A-Za-z0-9_./=,+ -]*$$
#
# --- Command-line override rejection (round-4 review P1-1) ------------------
# See audio_common's Makefile for the full writeup: a command-line
# CFLAGS=/CXXFLAGS=/CPPFLAGS=/LDFLAGS=/FP_POLICY=/FP_ALLOWED_CHARS_RE= silently
# disables every one of this file's own assignments/appends to that variable
# (here that would strip -ffp-contract=off, the USE_* optimization defines,
# the -I paths, and -lm) while still producing artifacts -- and a
# command-line/`-e` override of FP_ALLOWED_CHARS_RE specifically could widen
# the allowed character set (e.g. to `.*`, matching anything) and silently
# neuter the allow-list below. EXTRA_CFLAGS / EXTRA_LDFLAGS are the supported
# hooks.
$(foreach v,CFLAGS CXXFLAGS CPPFLAGS LDFLAGS FP_POLICY FP_ALLOWED_CHARS_RE,\
  $(if $(findstring command,$(origin $(v)))$(findstring override,$(origin $(v))),\
    $(error $(v) cannot be overridden (origin: $(origin $(v))) -- it would silently drop this Makefile's own flag appends (FP policy, USE_* defines, include paths); use EXTRA_CFLAGS / EXTRA_LDFLAGS instead)))

# Conflict detection (round-3 review B04; widened to CXXFLAGS/CPPFLAGS by a
# later Codex review, mirroring audio_common's and AEC's identical fix):
# reject outright rather than let a caller silently re-enable contraction.
# Checked against the fully-assembled $(CFLAGS) $(CXXFLAGS) $(CPPFLAGS) (each
# already includes EXTRA_CFLAGS folded in above, AND any
# CFLAGS=/CXXFLAGS=/CPPFLAGS= command-line override, since a command-line-set
# value is what every prior `+=` in this file appended to) -- BEFORE
# FP_POLICY is appended below and BEFORE CFG_SIG is computed, so a rejected
# build never creates an obj/bin directory.
#
# CORRECTED UNDERSTANDING (this used to check $(CFLAGS) alone, reasoning that
# this repo has no C++ TUs of its own so CXXFLAGS/CPPFLAGS "didn't matter" --
# the exact same reasoning audio_common's and AEC's Makefiles both had to
# correct via their own Codex reviews. CXXFLAGS/CPPFLAGS are still two of the
# five names the "Command-line override rejection" foreach above rejects a
# command-line/`-e` override of, and both already participate in
# CFG_SIG_PAYLOAD below -- a PLAIN ENVIRONMENT CXXFLAGS or CPPFLAGS is
# deliberately allowed to fold in normally via that same foreach's origin
# logic, never going through EXTRA_CFLAGS at all, so `env CXXFLAGS=-Ofast
# make BACKEND=kiss lib` used to sail straight through this block entirely:
# no check here ever inspected $(CXXFLAGS), so the day either variable
# starts feeding a real compile recipe in this repo, a live
# -Ofast/-ffast-math/-ffp-contract=<x> could ride in completely unchecked.
# The check below inspects all three variables together so no combination of
# CFLAGS/CXXFLAGS/CPPFLAGS -- command-line-folded, EXTRA_CFLAGS-folded, or a
# plain environment value -- can carry any of these three patterns past this
# gate, today or once either variable is actually consumed. This position
# (after every CFLAGS append earlier in this file -- base flags, -I paths,
# EXTRA_CFLAGS, the DEBUG-vs-default-optimizations block, WERROR -- and
# before FP_POLICY's own append just below) is the same position already
# relied on to see CFLAGS's fully-composed value, and is equally late enough
# for CXXFLAGS and CPPFLAGS: neither is ever appended to anywhere else in
# this file (each is a single bare `+=` at the top of this file -- see that
# line's own comment), both fully resolved well before this point.
#
# (round-9-class fix, ported here from audio_common's/AEC's Makefile rather
# than discovered independently) $(findstring ...) does a plain SUBSTRING
# search over the whole concatenated text, so it false-positives on any token
# that merely CONTAINS one of these patterns as part of a larger identifier
# -- e.g. a harmless `-DROUND9_NOTE=-Ofastness` macro definition is not the
# compiler flag -Ofast at all, yet a naive $(findstring -Ofast,...) check
# would reject it anyway. $(filter PATTERN...,TEXT) instead splits TEXT on
# whitespace into WORDS and matches each whole word against PATTERN (a
# trailing %% is a single wildcard, used here for -ffp-contract=<anything>),
# so it only ever matches a complete flag token, never a substring buried
# inside an unrelated token.
FP_INPUT_FLAGS := $(CFLAGS) $(CXXFLAGS) $(CPPFLAGS)

# --- link-flags character-safety coverage (Codex review, ported from
# audio_common's identical fix): the allow-list redesign below originally
# validated FP_INPUT_FLAGS only -- CFLAGS/CXXFLAGS/CPPFLAGS -- leaving LDFLAGS
# (built from a plain `-lm` literal plus whatever EXTRA_LDFLAGS folds in, see
# the `LDFLAGS += $(EXTRA_LDFLAGS)` line near the top of this file)
# completely unchecked, even though LDFLAGS is embedded in every real link
# recipe below ($(LINK) $(CFLAGS) -o $@ ... $(LDFLAGS) -- all four of
# $(TARGET)/$(PARITY_TARGET)/$(MEM_TARGET)/$(TEST_TARGET)) exactly the same
# way CFLAGS is embedded in every compile recipe. Confirmed empirically
# against this repo's own (pre-fix) Makefile: `make BACKEND=kiss
# AC_LIB=<resolved archive path> EXTRA_LDFLAGS=';echo LINK_FLAG_INJECTION' -n
# all` sailed through every check below untouched (rc=0, no $(error) fired
# anywhere in THIS file) and printed a real link recipe line with the shell
# metacharacter payload sitting live and unfiltered right after `-lm` -- the
# exact same class of exposure the allow-list below exists to close for
# CFLAGS/CXXFLAGS/CPPFLAGS, just left open on this one variable (the CFG_SIG
# manifest text was tainted with it too, confirming it also isn't merely a
# display-only gap). Fixed by introducing this union: the two checks that
# only care about CHARACTER safety (the single-quote pre-check and the
# allow-list itself, immediately below) now run against
# SHELL_SAFE_INPUT_FLAGS instead of FP_INPUT_FLAGS directly, so LDFLAGS/
# EXTRA_LDFLAGS content goes through the exact same grep-based gate with no
# separate/duplicated $(shell) invocation. The FP-semantic conflict check
# (FP_CONFLICT_FLAGS, further below -- -Ofast/-ffast-math/-ffp-contract=% are
# meaningless as LINK flags, not just unnecessary to check there) stays
# scoped to FP_INPUT_FLAGS alone, unchanged. See audio_common's Makefile for
# the full cross-repo writeup this comment summarizes (identical fix, applied
# here).
SHELL_SAFE_INPUT_FLAGS := $(FP_INPUT_FLAGS) $(LDFLAGS)

# (Codex review, ported from audio_common's/AEC's Makefile -- the confirmed-
# live bug this closes) $(filter) directly above does whole-WORD matching
# against GNU Make's OWN text representation of CFLAGS/CXXFLAGS/CPPFLAGS --
# but Make has zero concept of shell quoting. A value like
# EXTRA_CFLAGS="'-Ofast'" is stored by Make as the literal 9-character text
# '-Ofast', quote characters included, which is not equal to the bare word
# -Ofast, so $(filter) can never match it -- yet when this same text later
# appears on an actual compile recipe line and that line is handed to
# $(SHELL), the shell strips the quote characters and the compiler genuinely
# receives -Ofast as a real argv token (confirmed empirically against THIS
# repo's old CFLAGS-only findstring check, before this fix:
# `env EXTRA_CFLAGS="'-Ofast'" make BACKEND=kiss lib` succeeded, and the real
# compile line ended up with a bare -Ofast token). Three confirmed-live
# bypass shapes: EXTRA_CFLAGS="'-Ofast'" (single-quoted),
# EXTRA_CFLAGS='"-ffast-math"' (double-quoted), and EXTRA_CFLAGS="-O'f'ast"
# (quote-split mid-token -- the shell concatenates the pieces back into
# -Ofast once it strips the quotes). A fourth family, @response-file syntax
# (EXTRA_CFLAGS=@flags.rsp), is unrelated to quoting but equally invisible to
# a plain whole-word check: many compilers treat a bare @file argv token as
# "read more arguments from this file", which could inject anything at all
# with zero text ever appearing in CFLAGS/EXTRA_CFLAGS itself.
#
# Since Make cannot parse shell quoting, this block does not try to detect
# "a quoted variant of -Ofast" specifically. Instead, the ONLY supported
# external-input format for CFLAGS/CXXFLAGS/CPPFLAGS/EXTRA_CFLAGS is plain,
# unquoted, whitespace-separated compiler argv tokens -- and ANY appearance
# of shell quoting/escaping/expansion/response-file syntax in the combined
# text is rejected outright, regardless of what follows it, BEFORE the
# $(filter ...) exact-token conflict check below even runs, so that check
# only ever sees guaranteed-unquoted input. (This paragraph intentionally
# says nothing about -Ofast/-ffast-math/-ffp-contract itself: whether a
# token IS one of those three is decided solely by the unchanged $(filter)
# check; a harmless token that merely contains innocuous characters, e.g.
# -DROUND9_NOTE=-Ofastness or -DTEXT=ffast-math, contains none of the
# characters checked for below and so is untouched by this block.)
#
# REDESIGN (replicated from audio_common's/AEC's identical fix -- see
# audio_common's Makefile for the full writeup this comment summarizes): the
# character-by-character DENY-list this block used to be (single quote,
# double quote, backslash, backtick, a literal "$(" sequence, semicolon,
# pipe, ampersand, and an @-prefixed response-file token) is structurally
# unable to keep up -- a live audit found it does NOT catch bare glob
# characters (*, ?, [, ]), tilde (~), or -- most seriously -- real shell
# REDIRECTION (>, <) or process substitution (<(...)): none of these are
# Make's own syntax, so Make cannot pre-resolve or reject them the way it
# happens to catch ${VAR}-style expansions (GNU Make treats ${...}
# identically to $(...) and resolves it itself before any check runs -- a
# different, unrelated mechanism from the deny-list). If a recipe line
# containing an unbanned '>' or '<' is ever actually executed by a real
# shell (not a dry run), it silently redirects the compiler invocation's own
# stdout/stdin to an arbitrary path -- a real, unconditional risk,
# independent of any -Ofast/-ffast-math/-ffp-contract semantics. Separately,
# the old "$(" entry was likely DEAD CODE for well-formed input all along:
# `make ... 'CFLAGS=-O2 $(shell echo INJECTED)'` lets GNU Make's OWN parser
# resolve the well-formed $(...) reference at command-line-parsing time --
# "INJECTED" lands in CFLAGS as plain text, no literal "$(" substring ever
# reaches the check -- while an UNBALANCED `$(unbalanced` (no closing paren)
# makes Make itself abort with its own "unterminated variable reference.
# Stop." before any makefile-level check runs at all. Either way the
# findstring-based "$(" check never actually fires for the cases it was
# meant to catch.
#
# Replaced here with a single ALLOW-list covering the input as a whole. GNU
# Make has no native regex/character-class function, so this necessarily
# shells out to `grep -E` -- a $(shell ...) call, the same technique this
# file already uses for CFG_SIG's cksum computation below. Embedding
# untrusted, Make-supplied text inside a constructed shell command is
# exactly the kind of thing that can reintroduce the very problem being
# fixed if done carelessly, so the embedding strategy is deliberately narrow
# and was verified directly (not assumed) by audio_common's own phase of
# this fix: FP_INPUT_FLAGS is embedded SINGLE-QUOTED in the shell command
# text below (`printf '%s' '$(FP_INPUT_FLAGS)' | ...`). Inside a
# single-quoted POSIX shell string, EVERY character is literal except a
# single quote itself -- double quote, backslash, backtick, "$(", semicolon,
# pipe, and ampersand are all completely inert there. So the ONLY character
# that can break this embedding is a literal single quote in FP_INPUT_FLAGS
# itself (which would close the quoted string early and hand whatever
# follows to the shell as live syntax) -- which is why the single-quote
# check below is the ONE survivor from the old 9-item deny-list, kept for
# this entirely different, structural reason (safe shell-embedding), not
# merely because it's also a disallowed character (the allow-list below
# would reject it either way). It MUST run first, and MUST stay a pure
# $(findstring) check with zero shell involvement, so it can gate the
# shell-embedding step that follows it.
#
# Embeds SHELL_SAFE_INPUT_FLAGS (CFLAGS/CXXFLAGS/CPPFLAGS/LDFLAGS,
# fully-assembled -- see the "link-flags character-safety coverage" comment
# above for why LDFLAGS is folded in here too), not FP_INPUT_FLAGS alone, so
# a single quote arriving only via LDFLAGS/EXTRA_LDFLAGS is caught by this
# same Make-native check before the allow-list's own $(shell) call below
# single-quote-embeds the union.
ifneq ($(findstring ',$(SHELL_SAFE_INPUT_FLAGS)),)
$(error FP policy conflict: CFLAGS/CXXFLAGS/CPPFLAGS/LDFLAGS/EXTRA_CFLAGS/EXTRA_LDFLAGS contains a single-quote character; this repo requires plain, unquoted, whitespace-separated compiler/linker argv tokens built only from the allowed character set (see the allow-list below) -- a single quote specifically must be rejected by this Make-native check BEFORE the allow-list's own $(shell) call can safely single-quote-embed the rest of the text)
endif

# The allow-list itself. Allowed set: letters, digits, underscore, dot,
# slash, equals, comma, plus, minus -- plus space (the token SEPARATOR
# between flags; SHELL_SAFE_INPUT_FLAGS is always multiple whitespace-joined
# tokens, never a single one, so space must be permitted even though it is
# not part of any individual flag's own character set). Chosen (same audit
# audio_common's/AEC's Makefile performed for its own identical allow-list)
# by checking every legitimate flag THIS Makefile's own invocations actually
# use: -O0/-O2/-O3, -Wall/-Wextra, -std=gnu99, -I./include/-I./example/
# -I$(AC_DIR)/include, the USE_* optimization defines this file appends by
# default (-DUSE_FAST_GAIN_SMOOTHING/-DUSE_SHARED_XI_RATIO/
# -DUSE_OPTIMIZED_MIN_BUFFER/-DUSE_OPTIMIZED_E1/-DUSE_SINGLE_CLAMP/
# -DUSE_INCREMENTAL_MIN/-DUSE_STANDARD_MATH), the EXTRA_CFLAGS-hook defines
# this file's own comments document as supported (-DUSE_FAST_PERCENTILE,
# etc.), and LDFLAGS's own default `-lm` -- every one of these tokens is
# built ONLY from letters/digits/underscore, plus slash/dot for the -I paths.
# Comma and plus are included for headroom beyond this Makefile's current own
# usage (e.g. -Wl,-rpath,dir / -Wa,--option pass-through flags a legitimate
# EXTRA_LDFLAGS consumer might need), on the same audit basis: neither
# character appears anywhere in this Makefile's own flags today, so including
# them cannot regress anything currently working, and both are inert to the
# shell (unlike the characters actually excluded below). Equals covers
# EXTRA_CFLAGS defines that carry a value, e.g. the harmless
# -DROUND9_NOTE=-Ofastness / -DTEXT=ffast-math positive-control tokens this
# block's own comments discuss above.
#
# LC_ALL=C avoids any locale-dependent surprises in the [A-Za-z0-9...]
# ranges (verified identical under C locale on this host's BSD grep/tr; the
# same invocation is expected to behave identically under GNU grep/tr on a
# Linux host, since POSIX bracket-expression ranges are locale-defined by
# design and C locale pins them to the unambiguous ASCII ordering on both).
#
# Every one of the FORMER 9-item deny-list's targets (single quote, double
# quote, backslash, backtick, a literal "$(", semicolon, pipe, ampersand,
# @-response-file) is a character NOT in this allowed set, so all of them
# are rejected by construction now. This repo has no standalone shell-test
# script for this check (unlike AEC's test/run_fp_flag_policy_test.sh) --
# every one of the old deny-list's negative test cases, plus the new
# allow-list-only bypass shapes (glob */?/[]/, tilde, redirection >/<,
# process substitution <(...)), was re-verified by hand for this redesign;
# only the single-quote check above survives from the old deny-list, for
# the shell-embedding reason given there, not because the allow-list fails
# to cover it (a lone single quote is ALSO rejected by the allow-list on its
# own).
#
# MANUAL VERIFICATION (link-flags character-safety coverage gap, this
# review; same judgment call as above -- no standalone shell-test script
# added for this class of check either): re-run by hand against this file
# after the SHELL_SAFE_INPUT_FLAGS fix landed --
#   1. Repro, pre-fix behaviour reproduced first against a checked-out copy
#      of this file WITHOUT the fix (`git stash` equivalent): `make
#      BACKEND=kiss AC_LIB=<resolved archive path>
#      EXTRA_LDFLAGS=';echo LINK_FLAG_INJECTION' -n all` -- rc=0, no $(error)
#      fired anywhere in this file, and the printed $(TARGET) link recipe
#      carried `-lm ;echo LINK_FLAG_INJECTION` live and unfiltered (also
#      visible, tainted, in the printed CFG_SIG config.manifest text).
#   2. Same command against this file WITH the fix -- rejected: `$(error
#      ...)` fires at the allow-list check below, naming ";" as the
#      offending character, BEFORE any obj/bin directory or manifest is
#      created.
#   3. CFG_SIG for a normal default build (no EXTRA_CFLAGS/EXTRA_LDFLAGS) is
#      BYTE-IDENTICAL before/after this fix: SHELL_SAFE_INPUT_FLAGS only
#      participates in the two CHARACTER-safety checks (this allow-list and
#      the single-quote pre-check above), never in CFG_SIG_PAYLOAD itself
#      (CFG_SIG_PAYLOAD already listed CFLAGS/CXXFLAGS/CPPFLAGS/LDFLAGS
#      individually, unchanged by this fix) -- confirmed by diffing `make -n
#      BACKEND=kiss all` output before/after: identical CFG_SIG hash, obj/
#      bin directory names, and config.manifest contents for a clean
#      default build.
#   4. `make BACKEND=kiss test-config` still reports ALL CHECKS PASSED
#      (real, non-dry-run build+run) after the fix.
#   5. Legitimate flags still build cleanly after the fix: default build
#      (six USE_* defines), `EXTRA_CFLAGS=-DUSE_FAST_PERCENTILE`,
#      `EXTRA_CFLAGS='-DROUND9_NOTE=-Ofastness -DTEXT=ffast-math'` (comma/
#      plus/equals-bearing positive controls), and `WERROR=1` -- all pass
#      the allow-list/conflict checks and produce a real, working
#      denoise_wav/libmmse_lsa.a exactly as before this fix.
# See audio_common's Makefile for the full cross-repo writeup this
# comment summarizes (identical fix and identical manual-verification
# discipline, applied here).
#
# FP_ALLOWED_CHARS_RE itself is NOT defined here -- it is a bare, early
# `:=` literal (see the "Bare-literal policy flag" / "Command-line override
# rejection" comments near the top of this file, where it is protected
# against a command-line/`-e` override the exact same way FP_POLICY is).
# Only referenced here.
SHELL_SAFE_ALLOWLIST_RC := $(shell printf '%s' '$(SHELL_SAFE_INPUT_FLAGS)' | LC_ALL=C grep -Eq '$(FP_ALLOWED_CHARS_RE)'; echo $$?)
ifneq ($(SHELL_SAFE_ALLOWLIST_RC),0)
# Diagnostic-only second $(shell) call (only ever runs on the already-doomed
# error path above, never on a passing build): deletes every ALLOWED
# character from the same single-quote-embedded text, leaving only the
# disallowed ones, then dedupes/sorts them into a short, stable string --
# so the $(error ...) below names the SPECIFIC offending character(s)
# (e.g. ">" or "~" or "*") instead of a generic "invalid format" message.
SHELL_SAFE_DISALLOWED_CHARS := $(shell printf '%s' '$(SHELL_SAFE_INPUT_FLAGS)' | LC_ALL=C tr -d 'A-Za-z0-9_./=,+ -' | fold -w1 | LC_ALL=C sort -u | tr -d '\n')
$(error FP policy conflict: CFLAGS/CXXFLAGS/CPPFLAGS/LDFLAGS/EXTRA_CFLAGS/EXTRA_LDFLAGS contains a character outside the allowed set [A-Za-z0-9_./=,+- ] (letters/digits/underscore/dot/slash/equals/comma/plus/minus, plus space as the token separator) -- disallowed character(s) found: "$(SHELL_SAFE_DISALLOWED_CHARS)"; this repo requires plain, unquoted, whitespace-separated compiler/linker argv tokens built only from that set -- remove/replace the disallowed character(s) shown above in CFLAGS/CXXFLAGS/CPPFLAGS/LDFLAGS/EXTRA_CFLAGS/EXTRA_LDFLAGS)
endif

FP_CONFLICT_FLAGS := $(filter -Ofast -ffast-math -ffp-contract=%,$(FP_INPUT_FLAGS))
ifneq ($(FP_CONFLICT_FLAGS),)
$(error FP policy conflict: CFLAGS/CXXFLAGS/CPPFLAGS/EXTRA_CFLAGS contains $(FP_CONFLICT_FLAGS); this repo pins -ffp-contract=off; remove $(FP_CONFLICT_FLAGS) from CFLAGS/CXXFLAGS/CPPFLAGS/EXTRA_CFLAGS)
endif

# Command-line/`-e` override rejection for the FP-policy/shell-safety
# checks' remaining FOUR internal variables (replicated from audio_common's/
# AEC's identical fix, found live while audio_common implemented the
# allow-list above; SHELL_SAFE_INPUT_FLAGS/SHELL_SAFE_ALLOWLIST_RC added,
# same treatment, by the later Codex review that widened the
# character-safety check to LDFLAGS -- see the "link-flags character-safety
# coverage" comment above): FP_INPUT_FLAGS/SHELL_SAFE_INPUT_FLAGS/
# SHELL_SAFE_ALLOWLIST_RC/FP_CONFLICT_FLAGS are each computed from the
# fully-assembled CFLAGS/CXXFLAGS/CPPFLAGS (SHELL_SAFE_INPUT_FLAGS/
# SHELL_SAFE_ALLOWLIST_RC also fold in the fully-assembled LDFLAGS;
# SHELL_SAFE_ALLOWLIST_RC via a $(shell) call keyed off
# SHELL_SAFE_INPUT_FLAGS) -- unlike FP_POLICY/FP_ALLOWED_CHARS_RE above, none
# of the four is a bare, dependency-free literal, so none can be relocated
# earlier to ride in the six-name foreach near the top of this file (that
# foreach's own comment explains why bare-literal-and-early is required for
# the `-e` case). But each has the EXACT SAME command-line-override exposure
# as every name in that foreach: e.g. `make ... EXTRA_LDFLAGS=';echo
# INJECTED' SHELL_SAFE_ALLOWLIST_RC=0` (or the equivalent with
# SHELL_SAFE_INPUT_FLAGS=<anything clean>, FP_INPUT_FLAGS=<anything clean>,
# or FP_CONFLICT_FLAGS=) would silently win over this file's own computed
# value and turn every ifneq/$(error) gate above into a complete no-op --
# while the REAL $(CFLAGS)/$(CXXFLAGS)/$(CPPFLAGS)/$(LDFLAGS) used in every
# actual compile/link recipe still carry the dangerous, unvalidated content
# unmodified. Fixed the same way as the `-e` gap elsewhere in this file,
# mirrored for a LATE-computed (not early-literal) variable: the
# override-rejection check must itself run AFTER the variable's own real
# assignment (never before), so the origin-flip -- for both plain "command
# line" and, under `-e`, "environment override" -- has already happened by
# the time $(origin ...) is queried here. This is why this second foreach
# sits HERE, immediately after FP_CONFLICT_FLAGS (the last of the four to be
# assigned), rather than folded into the earlier foreach (which runs too
# early in the file for any of these four to have been assigned yet).
# SHELL_SAFE_DISALLOWED_CHARS is deliberately NOT included here: it is pure
# diagnostic text folded into the $(error ...) message on the failure path
# only, never a condition any ifneq tests, so overriding it cannot bypass
# anything -- at worst it would garble the reported character list on a
# build that was going to fail anyway.
$(foreach v,FP_INPUT_FLAGS SHELL_SAFE_INPUT_FLAGS SHELL_SAFE_ALLOWLIST_RC FP_CONFLICT_FLAGS,\
  $(if $(findstring command,$(origin $(v)))$(findstring override,$(origin $(v))),\
    $(error $(v) cannot be overridden (origin: $(origin $(v))) -- it would silently defeat the FP-policy/shell-safety allow-list/conflict checks above, leaving the real CFLAGS/CXXFLAGS/CPPFLAGS/LDFLAGS content unvalidated; this variable is internal to those checks and has no supported external use)))

# (Codex review / `make -e` gap fix: FP_POLICY's own bare `:=` literal now
# lives earlier in this file, directly above the "Command-line override
# rejection" foreach -- see that foreach's "Bare-literal policy flag"
# comment for why. Only FP_POLICY's OTHER job -- appending it to CFLAGS,
# LAST, exactly as the "FP-contraction policy" comment above describes --
# still lives at this position; there is exactly one `:=` definition of
# FP_POLICY in this file, not two.)
CFLAGS    += $(FP_POLICY)

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
AC_FWD = BACKEND=$(BACKEND) SIMD=$(SIMD) WERROR=$(WERROR) CC='$(CC)' CXX='$(CXX)' EXTRA_CFLAGS='$(EXTRA_CFLAGS)' NO_STDIO=$(NO_STDIO) TOOLCHAIN_CHECK=$(TOOLCHAIN_CHECK)

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

# Directories (declared before CFG_SIG_PAYLOAD below because SRCS -- which
# now participates in the payload, round-4 review P1-4 -- references
# $(SRC_DIR); OBJ_DIR/BIN_DIR are plain recursive assignments referencing
# CFG_SIG before its own `:=` line, which is fine -- see audio_common's
# Makefile for why).
SRC_DIR = src
EXAMPLE_DIR = example
TEST_DIR = test
# OBJ_ROOT / BIN_ROOT (round-6 review P1): where the keyed obj/bin trees
# live (defaults: obj/ and bin/ in this directory -- the default expansion
# is byte-identical to the previous hardcoded paths). Same rationale as
# DIST_ROOT above: a placement knob, never a build-content knob, so
# deliberately NOT in CFG_SIG. The isolation tests use these to run
# tamper/injection scenarios against a scratch-directory build of the real
# worktree, so the REAL obj/ and bin/ artifacts are never modified -- not
# even transiently. See audio_common's Makefile for the full writeup.
OBJ_ROOT ?= obj
BIN_ROOT ?= bin
OBJ_DIR = $(OBJ_ROOT)/$(BACKEND)-$(CFG_SIG)
BIN_DIR = $(BIN_ROOT)/$(BACKEND)-$(CFG_SIG)

# Source files (gain calculation merged into mmse_lsa_denoiser.c). FFT + fast_math
# come from audio_common (linked via $(AC_LIB)); this repo only supplies the
# denoiser/MCRA/SPP core. Participates in CFG_SIG_PAYLOAD below (round-4
# review P1-4): adding or removing a source file keys to a fresh obj/bin
# directory (see the fresh-archive recipe below for the other half of the
# stale-member fix).
SRCS = $(SRC_DIR)/mmse_lsa_denoiser.c \
       $(SRC_DIR)/mcra_noise_estimator.c \
       $(SRC_DIR)/spp_estimator.c

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
# optimizations, WERROR) and after the AC_LIB ifeq/else above
# resolves AC_PRODUCER_SIG, but before the first rule below that mentions
# $(OBJ_DIR)/$(BIN_DIR)/anything derived from them -- GNU Make expands a
# rule's target/prerequisite list immediately when parsed, not deferred like
# a recipe body.
#
# Deliberately NOT $(strip)'d (false-miss OK, false-hit never -- see
# audio_common's Makefile). cksum (POSIX) computes the hash.
# Round-4 review payload additions: LINK (P2-1), TOOLCHAIN_CHECK (the
# guard-skip knob must not alias a guarded build), SRCS (P1-4: sorted source
# list, so source add/remove keys to a fresh directory).
CFG_SIG_PAYLOAD := CC=$(CC) CXX=$(CXX) AR=$(AR) RANLIB=$(RANLIB) LINK=$(LINK) CFLAGS=$(CFLAGS) CXXFLAGS=$(CXXFLAGS) CPPFLAGS=$(CPPFLAGS) LDFLAGS=$(LDFLAGS) EXTRA_CFLAGS=$(EXTRA_CFLAGS) EXTRA_LDFLAGS=$(EXTRA_LDFLAGS) BACKEND=$(BACKEND) SIMD=$(SIMD) WERROR=$(WERROR) NO_STDIO=$(NO_STDIO) DEBUG=$(DEBUG) TOOLCHAIN_CHECK=$(TOOLCHAIN_CHECK) AC_PRODUCER_SIG=$(AC_PRODUCER_SIG) SRCS=$(sort $(SRCS))
CFG_SIG := $(shell printf '%s' "$(CFG_SIG_PAYLOAD)" | cksum | cut -d' ' -f1)

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
	@if [ "$(BACKEND)" = "ne10" ] && [ "$(TOOLCHAIN_CHECK)" = "1" ]; then \
	  cc_m="$$($(CC) -dumpmachine 2>/dev/null)"; cxx_m="$$($(CXX) -dumpmachine 2>/dev/null)"; \
	  if [ -z "$$cc_m" ] || [ "$$cc_m" != "$$cxx_m" ]; then \
	    echo "FATAL: CC/CXX compile for different targets (CC='$(CC)' -> '$$cc_m', CXX='$(CXX)' -> '$$cxx_m')." >&2; \
	    echo "  BACKEND=ne10 links a C++ TU (audio_common's NE10 archive); pass the FULL toolchain:" >&2; \
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

# Fresh-archive discipline (round-4 review P1-4): always built from scratch
# into a temp file and renamed into place -- never `ar rc` onto an existing
# archive (which only adds/replaces members and would keep a removed source's
# stale member forever). See audio_common's Makefile for the full writeup.
# One chained shell line with a PID-suffixed temp (round-5 review P2): two
# same-config processes racing this rule each write their OWN temp, final mv
# is atomic last-writer-wins. See audio_common's Makefile.
$(LIB_TARGET): $(OBJS) | _cfg_guard
	t="$@.tmp.$$$$" && rm -f "$$t" && $(AR) rc "$$t" $(OBJS) && $(RANLIB) "$$t" && mv -f "$$t" $@
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
	@test -f '$@' || { echo "ERROR: audio_common did not produce $@ (query/build divergence -- supported forwarded controls are BACKEND/SIMD/WERROR/CC/CXX/EXTRA_CFLAGS/NO_STDIO/TOOLCHAIN_CHECK)"; exit 1; }

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
	"$(abspath $(TEST_TARGET))"

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
# print-bin-dir dispatches through the same phase-1 producer resolution as
# the build goals, so a bare `make -s print-bin-dir` prints the exact
# directory the binaries are delivered into (NR's binaries only exist in the
# resolved-producer directory). Passing AC_LIB= explicitly skips the query.
ifeq ($(AC_LIB),)
print-bin-dir:
	+@ac="$$($(MAKE) -s --no-print-directory -C $(AC_DIR) $(AC_FWD) print-lib-path)"; \
	 test -n "$$ac" || { echo "FATAL: could not resolve audio_common archive path (AC_DIR=$(AC_DIR))" >&2; exit 1; }; \
	 $(MAKE) -s --no-print-directory print-bin-dir AC_LIB="$$ac"
else
print-bin-dir:
	@echo $(abspath $(BIN_DIR))
endif
print-obj-dir:
	@echo $(abspath $(OBJ_DIR))
print-lib-path:
	@echo $(abspath $(LIB_TARGET))

# =============================================================================
# publish v4: immutable, content-addressed release under $(DIST_ROOT)
# (round-3 B01 -> round-4 P2-2 -> round-5 P2 -> round-6 P1/P2) -- same design
# as audio_common's publish; see that Makefile for the full layout/semantics
# writeup (deterministic MANIFEST + append-only ATTEST/ provenance,
# byte-verified idempotent republish incl. MANIFEST tamper detection,
# rename(2)-atomic `current` swap via the swapln helper built with
# $(HOSTCC), and lock-FIRST driver so two concurrent same-config publishes
# can't race the prerequisite build). `publish` is the locked driver;
# _publish_impl is INTERNAL (direct invocation skips the lock) and goes
# through the same two-phase AC_LIB dispatch as `all`/`mem`.
#
# Round-6 (see audio_common's Makefile for the full writeup on all of this):
#   - `make -n`/`-q`/`-t` no longer touch $(DIST_ROOT) or the publish lock --
#     the `publish` driver word-scans MAKEFLAGS and short-circuits before any
#     filesystem side effect.
#   - git_commit is the FULL 40-hex OID (was --short), with dirty computed
#     from `git status --porcelain` and, when dirty, dirty_diff_sha256 =
#     sha256 of `git diff --binary HEAD`.
#   - ATTEST/ install is one-event-one-file via the swapln helper's
#     `--excl-install` mode (write-temp + link(2), atomic no-clobber): an
#     EEXIST collision (same second, same commit) bumps the attestation's
#     <seq> and retries (capped at 999) -- an existing attestation is NEVER
#     overwritten (round-5 used cp+mv -f, which silently clobbered a
#     same-second republish's prior record). Attestations remain UNSIGNED:
#     traceability, not authenticity.
#   - Dirty policy now covers BOTH checkouts that produced this artifact:
#     publish FATALs when either nr itself OR the producer audio_common
#     checkout (resolved via AC_DIR) is dirty, unless ALLOW_DIRTY_PUBLISH=1
#     (round-7 Stage 2c: a checkout with no git identity at all is its own
#     UNCONDITIONAL case -- see below -- no longer folded into this dirty
#     bullet). The attestation records both checkouts' provenance --
#     git_commit/git_dirty/dirty_diff_sha256 for nr, and the same three
#     fields audio_common_-prefixed for the producer -- plus
#     allow_dirty_publish so an accepted dirty publish is itself traceable.
#
# Round-7 (dirty/untracked policy split into two dimensions, extended here to
# BOTH checkouts that produce this artifact -- see audio_common's Makefile
# for the single-repo writeup this extends): publish FATALs by default when
# EITHER nr itself OR the producer audio_common checkout (resolved via
# AC_DIR) (a) has uncommitted TRACKED changes (`git status --porcelain
# -uno` non-empty), or (b) contains ANY untracked, non-ignored file (`git
# ls-files --others --exclude-standard` non-empty; gitignored build output
# is excluded by design). The two escape hatches are separate and
# orthogonal, and each applies across BOTH checkouts: ALLOW_DIRTY_PUBLISH=1
# admits tracked changes in either/both repo and records dirty_diff_sha256 /
# audio_common_dirty_diff_sha256 (sha256 of `git diff --binary HEAD` in nr /
# in $(AC_DIR)); ALLOW_UNTRACKED_PUBLISH=1 admits untracked files in
# either/both repo and records untracked_tree_sha256 /
# audio_common_untracked_tree_sha256 -- sha256 over sorted FIXED-FIELD
# per-file records, computed by the shared `hash_untracked()` shell function
# (see the recipe body below), one call per repo ("./" for nr, "$(AC_DIR)/"
# for the producer): "L <sha256(path)> <sha256(readlink output)>" for
# symlinks, "F <mode> <sha256(path)> <sha256(content)>" for regular files --
# every variable-length value is itself hashed so records concatenate
# unambiguously (raw space-joined path/target strings were collision-prone:
# "a b"->"c" vs "a"->"b c" encoded identically), and any stat/readlink/
# shasum failure downgrades the entry to an X record => FATAL ("... cannot
# be hashed deterministically ... cannot enter the provenance record"),
# never an empty hash (fail-closed). `git_untracked`/`untracked_tree_sha256`
# are recorded right after the corresponding dirty group in the attestation
# (self, then producer), and `allow_untracked_publish` right after
# `allow_dirty_publish`.
#
# Round-7 Stage 2c (this revision): a checkout with NO git identity at all --
# nr itself, or the checkout resolved via AC_DIR (including AC_DIR unset,
# missing, or not a directory) -- is refused UNCONDITIONALLY, in BOTH
# repos, checked BEFORE that repo's dirty/untracked flags are even computed.
# Neither ALLOW_DIRTY_PUBLISH nor ALLOW_UNTRACKED_PUBLISH admits it (see the
# ALLOW_DIRTY_PUBLISH knob comment near the top of this file for why the
# prior scheme could admit it). Once past that gate, dirty/untracked flags
# for both repos are plain 0/1 -- the "unknown" tri-state is gone from this
# logic entirely.
# =============================================================================
PUBLISH_ARTIFACTS = $(LIB_TARGET) $(TARGET)
DIST_BACKEND_DIR  = $(DIST_ROOT)/$(BACKEND)
DIST_LOCK         = $(DIST_ROOT)/.lock.$(BACKEND)

.PHONY: publish _publish_impl
# Dry-run guard (round-6 review P2-3, -t tightened by round-7): this recipe
# mentions $(MAKE), so GNU make executes it for real under -n/-q/-t (all
# three share that rule) -- which used to mkdir $(DIST_ROOT) persistently
# and take/release the real publish lock on every dry run. The word-scan
# below detects those flags in MAKEFLAGS and branches:
#   -t  prints a one-line note and exits 0 WITHOUT recursing (round-7:
#       recursing let standard touch semantics bump the mtimes of this
#       repo's objects and the delivered archive/binary -- real writes.
#       publish is a phony ACTION, not a build product; touching its
#       artifact prerequisites without attesting would fabricate state, so
#       touch mode is an explicit no-op here). Checked FIRST: in a COMBINED
#       invocation like `make -nt publish`, recursing for -n would hand the
#       child make both flags and GNU make then really applies touch
#       semantics (reproduced) -- so any t wins over n, conservatively;
#   -q  exits 1 directly (question mode's documented "needs updating"
#       answer -- publish is phony, so it always would run -- no output);
#   -n  exec a recursion-only path (the child make inherits -n and merely
#       PRINTS _publish_impl's commands).
# All three are now ZERO-WRITE: no DIST_ROOT, no lock, no stage/helper/
# MANIFEST/ATTEST writes, and no artifact mtime changes. MAKEFLAGS parsing
# (verified against GNU make 3.81: 17 flag combinations incl. long forms):
# bundled no-dash short flags may appear as the first word ("n", "sn") OR
# as separate dashed words ("-n" after a long option); long options start
# with "--"; a literal "--" separates flags from command-line variable
# overrides (which can themselves contain n/q/t -- BACKEND=ne10 -- hence
# the explicit skips). Normal invocations keep the round-5 lock-FIRST
# discipline unchanged. See audio_common's Makefile for the full writeup.
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

ifeq ($(AC_LIB),)
.PHONY: _publish_impl
_publish_impl:
	+@ac="$$($(MAKE) -s --no-print-directory -C $(AC_DIR) $(AC_FWD) print-lib-path)"; \
	 test -n "$$ac" || { echo "FATAL: could not resolve audio_common archive path" >&2; exit 1; }; \
	 $(MAKE) --no-print-directory _publish_impl AC_LIB="$$ac"
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
	  echo "  content, so NO escape hatch admits this (round-7 Stage 2c: ALLOW_DIRTY_PUBLISH used to)." >&2; \
	  echo "  Publish from a real checkout or a scratch clone with a disposable commit instead." >&2; \
	  exit 1; \
	fi; \
	dirty=0; [ -n "$$(git status --porcelain -uno 2>/dev/null)" ] && dirty=1; \
	unt_list="$$(git ls-files --others --exclude-standard 2>/dev/null)"; \
	untracked=0; [ -n "$$unt_list" ] && untracked=1; \
	if [ -n "$(AC_DIR)" ] && [ -d "$(AC_DIR)" ]; then \
	  ac_commit="$$(git -C $(AC_DIR) rev-parse HEAD 2>/dev/null || echo unknown)"; \
	else \
	  ac_commit=unknown; \
	fi; \
	if [ "$$ac_commit" = "unknown" ]; then \
	  echo "FATAL: publish refused -- audio_common (AC_DIR=$(AC_DIR)) has no git identity here (missing, not a directory, or not a git checkout)." >&2; \
	  echo "  Without an identity the attestation cannot name the source state OR enumerate untracked" >&2; \
	  echo "  content, so NO escape hatch admits this (round-7 Stage 2c: ALLOW_DIRTY_PUBLISH used to)." >&2; \
	  echo "  Point AC_DIR at a real audio_common checkout (or a scratch clone with a disposable commit)." >&2; \
	  exit 1; \
	fi; \
	ac_dirty=0; [ -n "$$(git -C $(AC_DIR) status --porcelain -uno 2>/dev/null)" ] && ac_dirty=1; \
	ac_unt_list="$$(git -C $(AC_DIR) ls-files --others --exclude-standard 2>/dev/null)"; \
	ac_untracked=0; [ -n "$$ac_unt_list" ] && ac_untracked=1; \
	adp=0; [ "$(ALLOW_DIRTY_PUBLISH)" = "1" ] && adp=1; \
	aup=0; [ "$(ALLOW_UNTRACKED_PUBLISH)" = "1" ] && aup=1; \
	if [ "$$adp" != "1" ] && ( [ "$$dirty" = "1" ] || [ "$$ac_dirty" = "1" ] ); then \
	  echo "FATAL: publish refused --" >&2; \
	  [ "$$dirty" = "1" ] && echo "  nr working tree is dirty (uncommitted TRACKED changes)." >&2; \
	  [ "$$ac_dirty" = "1" ] && echo "  audio_common (AC_DIR=$(AC_DIR)) working tree is dirty (uncommitted TRACKED changes)." >&2; \
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
	    echo "  audio_common (AC_DIR=$(AC_DIR)):" >&2; \
	    printf '%s\n' "$$ac_unt_list" | head -5 | sed 's/^/    /' >&2; \
	  fi; \
	  echo "  Track/remove them for a board deliverable, or pass ALLOW_UNTRACKED_PUBLISH=1 -- the escape" >&2; \
	  echo "  hatch is recorded in the attestation with (audio_common_)untracked_tree_sha256 over their exact contents." >&2; \
	  exit 1; \
	fi; \
	ddiff=""; [ "$$dirty" = "1" ] && ddiff="$$(git diff --binary HEAD 2>/dev/null | shasum -a 256 | cut -d' ' -f1)"; \
	ac_ddiff=""; [ "$$ac_dirty" = "1" ] && ac_ddiff="$$(git -C $(AC_DIR) diff --binary HEAD 2>/dev/null | shasum -a 256 | cut -d' ' -f1)"; \
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
	  printf '%s\n' "$$ac_unt_list" | hash_untracked "$(AC_DIR)/" > "$$work/ac_untracked.records"; \
	  if grep -q '^X ' "$$work/ac_untracked.records"; then \
	    echo "FATAL: publish refused -- an untracked path in audio_common (AC_DIR=$(AC_DIR)) cannot be hashed deterministically (embedded git checkout / special file / I/O failure) and so cannot enter the provenance record:" >&2; \
	    grep '^X ' "$$work/ac_untracked.records" | sed 's/^X /    /' >&2; \
	    exit 1; \
	  fi; \
	  ac_uhash="$$(shasum -a 256 < "$$work/ac_untracked.records" | cut -d' ' -f1)"; \
	fi; \
	dateutc="$$(date -u +%Y-%m-%dT%H:%M:%SZ)"; \
	stamp='$(ATTEST_STAMP)'; [ -n "$$stamp" ] || stamp="$$(date -u +%Y%m%dT%H%M%SZ)"; \
	$(HOSTCC) -O2 -o "$$work/swapln" $(AC_DIR)/tools/atomic_symlink_swap.c || { echo "FATAL: could not build the atomic symlink-swap helper with HOSTCC=$(HOSTCC) (pass HOSTCC=<host compiler>)" >&2; exit 1; }; \
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
	  echo "producer_cfg_sig=$(AC_PRODUCER_SIG)"; \
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
	    echo "audio_common_git_commit=$$ac_commit"; echo "audio_common_git_dirty=$$ac_dirty"; \
	    [ -n "$$ac_ddiff" ] && echo "audio_common_dirty_diff_sha256=$$ac_ddiff"; \
	    echo "audio_common_git_untracked=$$ac_untracked"; \
	    [ -n "$$ac_uhash" ] && echo "audio_common_untracked_tree_sha256=$$ac_uhash"; \
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

# debug delegates to `all` with DEBUG=1 (round-3 review B01 -- see the
# "Default optimizations vs DEBUG" section above for why this replaced the
# old target-specific-variable CFLAGS mutation).
debug:
	+@$(MAKE) DEBUG=1 all
	@echo "Debug build complete (standard math, no optimizations)"

# Clean
clean:
	rm -rf $(OBJ_ROOT) $(BIN_ROOT)
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
		"$(abspath $(TARGET))" test.wav test_out.wav; \
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
	@echo "Objects/binaries live in <OBJ_ROOT>|<BIN_ROOT>/<backend>-<config-hash>/ (default obj/bin) -- switching"
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
	@echo "  ./<BIN_ROOT>/<backend>-<config-hash>/denoise_wav input.wav output.wav (default bin/)"

.PHONY: dirs clean install uninstall test help
dirs: _cfg_guard

# --- Header dependency tracking (round-3 review B01) ------------------------
# See audio_common's Makefile for the full rationale. $(wildcard ...) makes
# this evaluate to nothing (not an error) before any objects exist yet for
# this CFG_SIG.
-include $(wildcard $(OBJ_DIR)/*.d)
