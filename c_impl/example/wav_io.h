/* Shared WAV I/O shim. NR output uses PCM16 with truncation of
 * sample * 32767.0f. WAV_IO_WRITER_STYLE=2 selects that writer. */
#ifndef NR_WAV_IO_SHIM_H
#define NR_WAV_IO_SHIM_H
/* Use a distinct guard so the shared header is included. */

#ifndef WAV_IO_WRITER_STYLE
#define WAV_IO_WRITER_STYLE 2  /* WAV_IO_WRITER_NR */
#endif

/* Support sibling and Audio_ALG submodule checkouts. */
#if defined(__has_include)
#  if __has_include("../../../audiolib/common/include/wav_io.h")
#    include "../../../audiolib/common/include/wav_io.h"
#  elif __has_include("../../../../../audiolib/common/include/wav_io.h")
#    include "../../../../../audiolib/common/include/wav_io.h"
#  else
#    error "wav_io.h: cannot locate audiolib/common/include/wav_io.h -- expected it as a sibling of this repo (SE/audiolib/common) or two levels up from an Audio_ALG submodule checkout (Audio_ALG/lib/nr -> SE/audiolib/common)"
#  endif
#else
#  error "wav_io.h: compiler lacks __has_include -- add an explicit #include for audiolib/common/include/wav_io.h"
#endif

#endif // NR_WAV_IO_SHIM_H
