/* C++ header/link smoke for the C library lifecycle and reconfiguration API. */
#include "anr.h"
#include <cstdio>

int main() {
    AnrConfig config = anr_config_for_level_grid(16000, 512, ANR_LEVEL_BALANCED);
    if (!anr_validate_config(&config)) return 1;
    AnrDenoiser* denoiser = anr_create(&config);
    if (!denoiser) return 1;

    config = anr_config_for_level_grid(16000, 512, ANR_LEVEL_AGGRESSIVE);
    int status = anr_reconfigure(denoiser, &config);
    if (status == 0) status = anr_set_level(denoiser, ANR_LEVEL_MILD);
    if (status == 0 && (anr_get_n_freqs(denoiser) != 257 ||
                       anr_get_hop_size(denoiser) != 256)) status = -1;
    // The legacy AnrMode type and ANR_MODE_* names must stay interchangeable with AnrLevel in C++.
    AnrMode legacy = ANR_MODE_BALANCED;
    if (status == 0) status = anr_set_level(denoiser, legacy);
    AnrLevel level = ANR_MODE_AGGRESSIVE;
    if (status == 0) status = anr_set_level(denoiser, level);
    anr_destroy(denoiser);
    if (status != 0) return 1;
    std::puts("ANR C++ API smoke PASS");
    return 0;
}
