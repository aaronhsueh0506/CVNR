# MMSE-LSA Denoiser Makefile
# V3-2 C Implementation

CC = gcc
CFLAGS = -Wall -Wextra -O2 -std=c99
CFLAGS += -I./include -I./example
CFLAGS += $(EXTRA_CFLAGS)

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

LDFLAGS = -lm

# =============================================================================
# FFT Backend Selection
# =============================================================================
# Default: KISS FFT (portable, compiled from source)
# NE10:    Pass NE10_DIR=<path> to use NE10 R2C/C2R (ARM NEON optimized)
#
# Example: make NE10_DIR=/path/to/Ne10 CC=aarch64-linux-gnu-gcc
# =============================================================================

ifdef NE10_DIR
  # NE10 R2C/C2R backend (ARM NEON)
  FFT_SRC = $(SRC_DIR)/fft_wrapper_ne10.c
  CFLAGS += -I$(NE10_DIR)/inc
  LDFLAGS += -L$(NE10_DIR)/lib -lNE10
  LIB_SRCS =
  LIB_OBJS =
else
  # KISS FFT backend (portable)
  FFT_SRC = $(SRC_DIR)/fft_wrapper.c
  CFLAGS += -I./lib/kiss_fft
  LIB_DIR = lib/kiss_fft
  LIB_SRCS = $(LIB_DIR)/kiss_fft.c
  LIB_OBJS = $(patsubst $(LIB_DIR)/%.c,$(OBJ_DIR)/%.o,$(LIB_SRCS))
endif

# Directories
SRC_DIR = src
EXAMPLE_DIR = example
OBJ_DIR = obj
BIN_DIR = bin

# Source files (gain calculation merged into mmse_lsa_denoiser.c)
SRCS = $(SRC_DIR)/mmse_lsa_denoiser.c \
       $(SRC_DIR)/mmse_lsa_freq_denoiser.c \
       $(SRC_DIR)/mcra_noise_estimator.c \
       $(SRC_DIR)/spp_estimator.c \
       $(FFT_SRC)

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

# Link
$(TARGET): $(OBJS) $(LIB_OBJS) $(EXAMPLE_OBJS)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)
	@echo "Build complete: $@"

# Compile source files
$(OBJ_DIR)/%.o: $(SRC_DIR)/%.c
	$(CC) $(CFLAGS) -c -o $@ $<

# Compile library files (KISS FFT only, skipped when using NE10)
ifndef NE10_DIR
$(OBJ_DIR)/%.o: $(LIB_DIR)/%.c
	$(CC) $(CFLAGS) -c -o $@ $<
endif

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

# Build static library
LIB_TARGET = $(BIN_DIR)/libmmse_lsa.a

lib: dirs $(OBJS) $(LIB_OBJS)
	ar rcs $(LIB_TARGET) $(OBJS) $(LIB_OBJS)
	@echo "Static library built: $(LIB_TARGET)"

# Help
help:
	@echo "MMSE-LSA Denoiser Build System"
	@echo ""
	@echo "Targets:"
	@echo "  all      - Build the denoiser executable (default)"
	@echo "  lib      - Build static library"
	@echo "  clean    - Remove build artifacts"
	@echo "  install  - Install to /usr/local/bin"
	@echo "  uninstall - Remove from /usr/local/bin"
	@echo "  test     - Run test (requires test.wav)"
	@echo "  help     - Show this help"
	@echo ""
	@echo "Build Configurations:"
	@echo "  make                                          - Standard build (KISS FFT, fast math)"
	@echo "  make NE10_DIR=/path/to/Ne10                   - NE10 R2C/C2R build (ARM NEON)"
	@echo "  make NE10_DIR=/path CC=aarch64-linux-gnu-gcc  - Cross-compile with NE10"
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

.PHONY: all dirs clean install uninstall test lib help debug
