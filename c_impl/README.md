# ANR V3-2 的 C 建置與驗證

[初始化、每 hop 呼叫與設定](../docs/html/index.html) · [參數調整](../docs/parameter_tuning.md)

## 編譯

### 基本編譯

```bash
make
make SIMD=0  # 強制 NR 與 audiolib 的所有可選 SIMD 路徑走 scalar
```

### 調試版本（關閉所有優化，使用標準數學函數，與 Python 輸出最接近）

```bash
make debug
```

### 靜態記憶體版本（嵌入式，零 malloc）

```bash
make mem              # → bin/<backend>-<config-hash>/denoise_mem（範例 example/main_mem.c），FFT 為 NE10（ARM NEON）
```

輸出檔案位於依 backend + 編譯參數雜湊命名的 `bin/<backend>-<config-hash>/` 目錄；
用 `make print-bin-dir`（帶上與建置相同的參數）取得確切路徑，或
`make publish` 產出穩定的 `dist/<backend>/current/` 交付路徑。

denoiser、MCRA、SPP、FFT **同時**提供 malloc 路徑（`_create`）與靜態記憶體路徑
（`_get_mem_size` + `_init`，與 AEC 的 `aec_get_mem_size`/`aec_init` 命名一致）。
兩條路徑編進同一份 object，沒有編譯期 `#ifdef` 切換；每個 handle 內有 `is_static` flag
（`_create()` 設 0，`_init()` 設 1），`_destroy()` 靠它決定要不要 free。用法：先用
`_get_mem_size()` 問要多少，配一塊記憶體（static 陣列或呼叫端的 platform block），交給
`_init(mem, size, ...)`：

```c
static uint8_t pool[/* >= anr_get_mem_size(&cfg) */] __attribute__((aligned(16)));
size_t need = anr_get_mem_size(&cfg);              // 先問大小
AnrDenoiser* d = anr_init(pool, sizeof pool, &cfg);  // 零 malloc
/* ... 每幀 anr_process()，音訊路徑無任何配置 ... */
anr_destroy(d);                                     // no-op（記憶體由呼叫端持有）
```

static instance 的 `anr_destroy()` 是 no-op：`AnrDenoiser` 不持有 FFT 或 backend heap 資源
（頻域 I/O 由呼叫端的 `FftHandle` 負責）。`fft_init()` 建立的 handle 其 `fft_destroy()` 同樣是
no-op、可重複呼叫：NE10 的 R2C/C2R twiddle cfg 從呼叫端 pool 切出（`audiolib` 的 vendored NE10
external-memory 初始化 `ne10_fft_init_r2c_float32_ext`），沒有 backend-internal malloc。完整範例見
[記憶池範例](../docs/reference/streaming.md) §1.5 的 `create_static_nr`。

演算法與 malloc 版使用同一個處理核心（只差配置方式）：實測 `denoise_mem` 輸出與 `denoise_wav` byte-for-byte 一致：`test_wav/wav/babble_0dB.wav`（48 kHz/1024，四個 level）、
`test_wav/music/fix_gain_noise.wav`（16 kHz，256 與 512 兩個 grid，mild／balanced／aggressive）；其他素材與 grid 未逐一比對。同一機制也覆蓋子模組
`fft_get_mem_size`/`fft_init`、`noise_estimator_get_mem_size`/`noise_estimator_init`、
`spp_get_mem_size`/`spp_init`。

`test_wav/` 內只有 `music/` 的兩個 wav 在 git 內；`wav/`、`opus/`、`scene_change/`、`vctk_demand/` 是本機素材，不入版控。`wav/` 的 48 kHz babble／car／street／clean 檔對應 `opus/` 內同名的 `.opus`，沒有 wav 時可用 `ffmpeg -i test_wav/opus/<name>.opus test_wav/wav/<name>.wav` 解出（範例與 `docs/reference/metrics.md` 的路徑都以這個目錄為準）。

**零 malloc 保證**：malloc 路徑編進同一份 object，所以 `nm` 一定看得到
`malloc`/`calloc`/`free` 符號（來自 `_create()`）。保證的是**靜態路徑在執行期不呼叫任何配置器**：
`_init()` 只做指標運算 + `memset`，連 exact-percentile 初始化（唯一的初始化方式，沒有近似選項）也用預先配好的
`percentile_scratch`（in-place quickselect）。`example/main_mem.c` 呼叫 `_init()` 系列，執行期 0 malloc。

**FFT 與 fast_math 來自共用的 `../audiolib/common`**（`make` 產出 `libaudio_common.a`，
`c_impl/Makefile` 直接連結；本 repo 不含 NE10 原始碼副本）。FFT 唯一後端是 NE10；handle、
work buffer、twiddle cfg 都在 pool 內，`fft_init()` 到 `fft_destroy()` 全程零 heap，
**每幀音訊路徑零 malloc**。

> **Note:** `make` 預設啟用 4 個優化開關（近似數學的誤差依核准預算驗收），不需要手動指定。

這裡的「fast math」指 `fast_math.h` 與 `USE_*` 選項的近似函式，並非編譯器
`-ffast-math`；後者會被 Makefile 拒絕。std-math C 對 Python 與出貨 C 對
std-math C 分別用數值容差／核准近似預算驗收，不能將出貨結果宣稱為 Python bit-exact。

### FP-contraction 政策

`-ffp-contract=off -fno-math-errno` 是四個 repo（`audiolib`、`NR/c_impl`、`AEC/c_impl`、
`Audio_ALG/pipelines`）的統一政策，套用到每個 TU（含 vendored 的 NE10）。它附加在
`CFLAGS` 組裝的最後一步，呼叫端的 flag 蓋不掉；Makefile 在 parse time 拒絕
`EXTRA_CFLAGS`（或 `CFLAGS=`）內的 `-Ofast`／`-ffast-math`／`-ffp-contract=<任意值>`
（`FP policy conflict`）。`../audiolib/common/scripts/audit_fp_contract.sh` 反組譯
`anr.o`／`noise_estimator.o`／`spp_estimator.o`，出現 fmadd／fmsub／fnmadd／fnmsub／
fmla／fmls 即失敗；其 header 說明檢查範圍。

## 編譯開關說明

ARM32／ARM64 由編譯器 target 自動選擇，不需要修改原始碼。共用的手寫 DSP NEON
kernel 在 AArch64、以及具 NEON＋fused FMA 的 32 位元 ARM（`-mcpu=cortex-a32/a53/a55/a73`、
`-mfpu=neon-vfpv4`、`-mfpu=neon-fp-armv8`）使用 NEON，由 `utility/simd_kernels.h` 的
`SK_HAVE_NEON` 單一決定；無 FMA 的 32 位元 ARM（純 `-mfpu=neon`）走 C fallback。32 位元 ARM 的
向量單元會把次正規數清為零，NEON 與純量版只對有限且非次正規的輸入逐位元相同，比對兩者的測試先呼叫
`SK_MATCH_SCALAR_TO_VECTOR_MODE()`。
`SIMD=0` 是 DSP kernel 的純量覆寫，不是 ABI 選擇器。交叉編譯時必須提供同一套
CC／CXX／AR／RANLIB。靜態 pool 的需求與結構布局屬於該次編譯的 ABI，應在目標版本
呼叫 `_get_mem_size()`，不可沿用 ARM64 的固定 byte 數或跨 ABI 複製 handle 記憶體。

ARM32 請用 `EXTRA_CFLAGS=-mfpu=neon-vfpv4`（AArch32 ARMv8 核心用 `-mfpu=neon-fp-armv8`），
不要用單純的 `-mfpu=neon`：沒有硬體 FMA 時，每個明確的 `fmaf()`（含 FFT 功率譜）都會變成
libm 呼叫，位元結果不變但速度慢很多。ARMv7 Advanced SIMD 會把 subnormal 沖為零並以預設
NaN 取代 NaN payload，因此 ARM32 上 `SIMD=1` 與 `SIMD=0` 對這類值可能不同；NE10 NEON FFT 與
具硬體 FMA 的 ARM32 上所有走 NEON 的共用 kernel（含 NR 用到的）都受影響，NEON 與純量版只對有限且
非次正規的輸入逐位元相同。

### 預設啟用（`make` 即啟用）

| 開關 | 說明 | 相關度 |
|------|------|--------|
| `USE_FAST_GAIN_SMOOTHING` | 在 log 域直接 clamp，省略 exp→log 轉換 | 公式等價；fast-math 下不保證 bit-exact |
| `USE_SHARED_XI_RATIO` | SPP 和 Gain 共用 v 計算結果，每頻點省 1 次除法 | 公式等價；≤1 ulp，不保證 bit-exact |
| `USE_OPTIMIZED_E1` | E1(v) 指數積分分支重排 + 共用 log10 | 100% |
| `USE_SINGLE_CLAMP` | 移除冗餘的 gain clamp；只在 `USE_FAST_GAIN_SMOOTHING` **關閉**時有作用，預設組合下是 no-op | 100% |

### 調試用

| 開關 | 說明 |
|------|------|
| `USE_STANDARD_MATH` | 使用標準數學函數（expf/logf/sqrtf），`make debug` 自動啟用 |

### 推薦配置

| 場景 | 配置 |
|------|------|
| 調試/驗證 | `make debug` |
| 標準使用 | `make` |
| 嵌入式/零 malloc（呼叫端提供記憶體） | `make mem`（`_get_mem_size`/`_init`，見上「靜態記憶體版本」） |

## 執行期設定

### 執行期重設定（running instance 上換 tuning）

```c
int anr_reconfigure(AnrDenoiser* self, const AnrConfig* target);
int anr_set_level(AnrDenoiser* self, AnrLevel level);
```

兩者都不重新配置任何記憶體，所以格點（`sample_rate` / `frame_size` / `hop_size` /
`fft_size`）與兩個決定 pool 大小的欄位（`L`、`num_init_frames`）**必須等於實例當下的
值**，`target` 另外還要完整通過 `anr_validate_config()`。回 `0`，或 `-1`
（NULL、target 無效、幾何不符）；`-1` 時**什麼都不寫**。在兩個 hop 之間呼叫、與
`anr_process()` 序列化；**非 thread-safe**。

**狀態是刻意保留的**：追蹤中的噪聲底、MCRA 最小值追蹤環與它的 scene-change run
length、SPP 的 a-priori-SNR 歷史、增益平滑歷史，全部繼續跑。換強度不是重啟——
把噪聲估計在串流中途丟掉，造成的 artefact 比原本想調掉的東西更糟。真的要重啟請用
`anr_reset()`。

**`anr_reconfigure()` 逐字採用 `target`**：不做 level 查表、不做 overlay 疊加。
這是刻意的——組態是「level 加上自己的覆寫」的呼叫端，必須自己重建整份組合再傳進來，
否則那些覆寫會被悄悄還原回 canonical level 的值。

**`anr_set_level()` 只適用於組態等於 canonical level 的實例**：它替該 level 組出 canonical
組態（`anr_config_for_level_grid()`，`L` 為函式庫預設）、交給 `anr_reconfigure()`。回 `0`，
或 `-1`（NULL、超出 enum 的 level、target 被拒）。

> **對疊了自己覆寫的實例，不要用 `anr_set_level()`。** 以 `anr_config_for_level_grid()` 建出、
> 沒有改動任何欄位的實例，可以直接用 `anr_set_level()` 換強度。若建立實例時在 canonical
> level 上改過欄位，裸的 canonical level 會把非 pool 欄位的覆寫悄悄還原，而改過 `L` 或
> `num_init_frames` 時整個呼叫會被**拒絕**（pool 大小不符）。這種實例請自己重組
> 完整組態再呼叫 `anr_reconfigure()`。

```c
/* 組態等於 canonical level：直接換強度，噪聲底與平滑歷史保留 */
if (anr_set_level(denoiser, ANR_LEVEL_AGGRESSIVE) != 0) { /* 引數不合法 */ }

/* 自己疊了覆寫的呼叫端：重組整份組態再交出去 */
AnrConfig target = anr_config_for_level_grid(
    sr, fft_size, ANR_LEVEL_AGGRESSIVE);
target.noise_over_subtraction = 1.2f;   /* 範例覆寫；每次都要重新疊上去 */
if (anr_reconfigure(denoiser, &target) != 0) { /* 幾何不符或 target 無效 */ }
```

回歸測試：`make test-reconfigure`（`test/test_reconfigure.c`）。

### Python↔C 數值對齊驗證 (parity harness)

`python/tools/parity_nr.py` + `example/parity_runner.c` 提供可重現的埠正確性驗證，
**隔離 FFT 差異**：兩端餵入 byte-identical 的逐幀複數頻譜，只比 gain/SPP/MCRA 運算。

Python dump 可用 `--fft-size` 明確選 grid：A＝16k/256/128、
B＝16k/512/256、C＝48k/1024/512。NRP2 header 記錄輸入 sample rate，
`n_freqs` 決定 FFT size；C runner 從這兩者重建相同 grid。
`compare` 回報絕對 gain 差異的 worst／median／mean；Python/C 比較是
float64／float32 與數學近似的數值容差檢查，不宣稱 bit-exact。

```bash
# 0. 輸出夾（repo 根目錄的 results/，benchmark 工具也寫這裡）
mkdir -p ../results

# 1. Python 端 dump 參考頻譜 + gain
python3 ../python/tools/parity_nr.py dump --wav ../test_wav/wav/babble_10dB.wav --out ../results/parity_in.bin

# 2a. C 端 fast-math（bin 目錄依 build flags 雜湊）
ac=$(make -s --no-print-directory -C ../../audiolib/common print-lib-path)
make DEBUG=0 COMMON_LIB="$ac" parity
bin_dir=$(make -s DEBUG=0 COMMON_LIB="$ac" print-bin-dir)
"$bin_dir/parity_runner" ../results/parity_in.bin ../results/g_fast.bin
python3 ../python/tools/parity_nr.py compare --ref ../results/parity_in.bin --c-gains ../results/g_fast.bin

# 2b. C 端 standard-math（檢查 float32/float64 殘差）
make DEBUG=1 COMMON_LIB="$ac" parity
bin_dir=$(make -s DEBUG=1 COMMON_LIB="$ac" print-bin-dir)
"$bin_dir/parity_runner" ../results/parity_in.bin ../results/g_debug.bin
python3 ../python/tools/parity_nr.py compare --ref ../results/parity_in.bin --c-gains ../results/g_debug.bin
```

NRP2 dump header 會攜帶 `sample_rate`；C 端據此建立完全相同的 signal grid
與 wall-clock-retimed EMA/count。NRP1 header 視為 16 kHz。實測
（48 kHz babble_10dB.wav，3480 幀 × 513 bin）：

| build | worst &#124;Δgain&#124; | median &#124;Δgain&#124; | mean &#124;Δgain&#124; |
|-------|--------------|---------------|-------------|
| standard-math (`-DUSE_STANDARD_MATH`) | 1.192e-5 | 1.490e-8 | 4.593e-8 |
| fast-math (預設) | 7.277e-3 | 1.113e-4 | 2.268e-4 |

上表的 standard-math 使用 `DEBUG=0 EXTRA_CFLAGS=-DUSE_STANDARD_MATH`，
與上方 `DEBUG=1` 指令不同；DEBUG=1 同時關閉四個 production 優化開關。
上表是該素材的實測殘差，不是所有輸入的通用容差上限。standard-math 仍有
float32/float64 誤差；fast-math 另外包含 `fast_exp`（LUT +
Taylor，相對誤差 ≤ 0.39%）與 degree-4 minimax `fast_log`（絕對誤差 < 1e-4），兩者都是
有界的近似（NR 不呼叫 `fast_sqrt`）。
