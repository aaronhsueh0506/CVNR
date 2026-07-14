/**
 * wav_io.h - NR thin shim onto the shared, hardened WAV I/O (F06 remediation)
 *
 * The actual reader/writer implementation moved to the single canonical
 * audio_common/include/wav_io.h (hardened parser + shared writer -- see
 * that file's header comment for the full rationale: fmt-chunk-size
 * validation, format/channels/bits/sample_rate/block_align/byte_rate
 * checks, RIFF odd-chunk pad-byte handling, file-size bounds checks on
 * every chunk_sz, and float32 NaN/Inf sanitize on read).
 *
 * This shim exists so that main.c's / main_mem.c's `#include "wav_io.h"`
 * keeps resolving with zero source changes, and to pin NR's historical
 * writer behavior:
 *   - ALWAYS PCM16 output (no float32 path, unlike AEC's writer).
 *   - PCM16 quantization is plain truncation (`sample*32767.0f` cast to
 *     int16_t), NOT rounding.
 * (2 == WAV_IO_WRITER_NR in audio_common/include/wav_io.h; duplicated as a
 * literal here because that symbolic name isn't defined until AFTER the
 * #include below -- see the canonical header's WAV_IO_WRITER_STYLE doc.)
 */
#ifndef NR_WAV_IO_SHIM_H
#define NR_WAV_IO_SHIM_H
/* NOTE: deliberately NOT guarded as WAV_IO_H -- that guard belongs to the
 * canonical audio_common/include/wav_io.h included below. Reusing it here
 * would make the canonical #include below a silent no-op (its own
 * #ifndef WAV_IO_H would see the guard already "defined" by this file and
 * skip its entire body). See AEC's copy of this shim for the matching
 * #include_next pitfall this same reasoning ruled out. */

#ifndef WAV_IO_WRITER_STYLE
#define WAV_IO_WRITER_STYLE 2  /* WAV_IO_WRITER_NR */
#endif

/* Locate audio_common/include/wav_io.h with an explicit relative path,
 * resolved with __has_include the same way this repo's own Makefile
 * resolves AC_DIR (`$(wildcard ../../audio_common ../../../../audio_common)`
 * from c_impl/ -- one directory deeper here since this file lives in
 * c_impl/example/, not c_impl/ itself): the first candidate is the normal
 * sibling-repo checkout (SE/NR next to SE/audio_common), the second is
 * this repo vendored two levels deeper as an Audio_ALG submodule
 * (Audio_ALG/lib/nr/c_impl/example -> SE/audio_common).
 */
#if defined(__has_include)
#  if __has_include("../../../audio_common/include/wav_io.h")
#    include "../../../audio_common/include/wav_io.h"
#  elif __has_include("../../../../../audio_common/include/wav_io.h")
#    include "../../../../../audio_common/include/wav_io.h"
#  else
#    error "wav_io.h: cannot locate audio_common/include/wav_io.h -- expected it as a sibling of this repo (SE/audio_common) or two levels up from an Audio_ALG submodule checkout (Audio_ALG/lib/nr -> SE/audio_common)"
#  endif
#else
#  error "wav_io.h: compiler lacks __has_include -- add an explicit #include for audio_common/include/wav_io.h"
#endif

#endif // NR_WAV_IO_SHIM_H
