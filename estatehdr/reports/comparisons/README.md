# Porównania przed / po dla presetów

Wygenerowane przez `tools/make_comparisons.py` (pełny pipeline, metryki z `estatehdr/quality`).
Kolumny: klip = % pikseli z kanałem ≥ 254, klip_excl = bez obszarów przepalonych w każdej klatce, zaczernienie = % ≤ 1, pion = mediana odchylenia linii pionowych [°], ściana ΔE = neutralność bieli (CIEDE2000; _gt = maska ścian z GT), win_L = L* widoku za oknem (bez nieodzyskiwalnych pikseli), ssim/dE_ref = zgodność z idealną edycją GT.

## Przed: klatka referencyjna jak z aparatu (podgląd, te same metryki)

| seria | clipped_% | crushed_% | median_luma | vert_med_deg | wall_dE_auto |
|---|---|---|---|---|---|
| syntetyczne/IMG_0000 | 9.551 | 0.001 | 0.327 | 2.874 | 10.066 |
| syntetyczne/IMG_0005 | 15.925 | 0.080 | 0.156 | 2.408 | 8.855 |
| syntetyczne/IMG_0008 | 8.454 | 0.000 | 0.332 | 3.913 | 9.079 |
| syntetyczne/IMG_0015 | 15.645 | 0.000 | 0.505 | 1.035 | 4.970 |
| syntetyczne/IMG_0018 | 5.642 | 0.004 | 0.239 | 1.060 | 9.283 |
| syntetyczne/NOEXIF_0000 | 1.618 | 0.062 | 0.139 | 1.270 | 7.194 |
| hdrplus/HDRP_0000 | 12.362 | 0.000 | 0.332 | 1.431 | 8.598 |
| hdrplus/HDRP_0003 | 8.967 | 0.000 | 0.323 | 1.157 | 10.050 |
| hdrplus/HDRP_0006 | 3.047 | 0.000 | 0.332 | 1.281 | 8.006 |
| hdrplus/HDRP_0009 | 8.997 | 0.000 | 0.329 | 6.489 | 11.181 |
| hdrplus/HDRP_0012 | 5.388 | 0.000 | 0.330 | 3.690 | 8.533 |
| hdrplus/HDRP_0015 | 1.172 | 0.000 | 0.328 | 0.603 | 10.110 |
| opencv/memorial_0 | 1.357 | 0.000 | 0.149 | 4.768 | 13.473 |
| opencv/stlouis_1 | 16.197 | 0.000 | 0.459 | 2.250 | 11.816 |
| portfolio_single/01.BtS2Hkmp | 0.008 | 0.071 | 0.707 | 0.323 | 5.786 |
| portfolio_single/k007.C8MVnAJ9 | 0.110 | 0.012 | 0.689 | 0.197 | 4.348 |
| portfolio_single/k040.wqWqsOuE | 0.095 | 0.013 | 0.650 | 0.232 | 3.401 |

## Po: preset `neutral`

| seria | clipped_% | clipped_excl_% | crushed_% | median_luma | vert_med_deg | wall_dE_auto | wall_dE_gt | wall_L_gt | win_L | win_clip_% | win_clip_recov_% | win_detail | halo_dL | ssim | ms_ssim | dE_ref |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| syntetyczne/IMG_0000 | 0.747 | 0.071 | 0.003 | 0.718 | 0.137 | 2.828 | 1.700 | 79.147 | 71.984 | 12.028 | 0.000 | — | 0.651 | 0.891 | 0.917 | 14.006 |
| syntetyczne/IMG_0005 | 6.001 | 0.000 | 0.010 | 0.713 | 0.042 | 2.387 | 1.302 | 69.479 | 72.094 | 41.859 | 0.000 | — | -0.038 | 0.908 | 0.908 | 8.775 |
| syntetyczne/IMG_0008 | 0.551 | 0.005 | 0.003 | 0.717 | 0.114 | 2.659 | 1.867 | 78.221 | 70.682 | 0.000 | 0.000 | — | -3.315 | 0.872 | 0.887 | 16.675 |
| syntetyczne/IMG_0015 | 3.476 | 0.000 | 0.000 | 0.706 | 0.025 | 0.794 | — | — | — | — | — | — | — | — | — | — |
| syntetyczne/IMG_0018 | 1.850 | 1.850 | 0.002 | 0.455 | 0.167 | 7.551 | — | — | 72.442 | 41.241 | — | 0.078 | — | — | — | — |
| syntetyczne/NOEXIF_0000 | 2.171 | 0.171 | 0.001 | 0.707 | 0.086 | 2.562 | — | — | 72.810 | 47.250 | — | 0.093 | — | — | — | — |
| hdrplus/HDRP_0000 | 8.229 | 0.488 | 0.002 | 0.734 | 0.367 | 4.738 | — | — | 79.435 | 60.809 | — | 0.172 | — | — | — | — |
| hdrplus/HDRP_0003 | 9.168 | 1.833 | 0.007 | 0.716 | 0.063 | 8.531 | — | — | 84.695 | 70.244 | — | 0.074 | — | — | — | — |
| hdrplus/HDRP_0006 | 0.202 | 0.202 | 0.001 | 0.707 | 0.350 | 5.175 | — | — | 70.718 | 0.000 | — | 0.202 | — | — | — | — |
| hdrplus/HDRP_0009 | 0.519 | 0.323 | 0.000 | 0.701 | 6.969 | 5.761 | — | — | 71.349 | 1.210 | — | 0.163 | — | — | — | — |
| hdrplus/HDRP_0012 | 0.492 | 0.170 | 0.000 | 0.716 | 1.674 | 6.415 | — | — | 72.952 | 4.701 | — | 0.137 | — | — | — | — |
| hdrplus/HDRP_0015 | 0.595 | 0.221 | 0.000 | 0.701 | 0.371 | 5.423 | — | — | 85.061 | 49.718 | — | 0.231 | — | — | — | — |
| opencv/memorial_0 | 3.233 | 2.977 | 0.088 | 0.706 | 5.484 | 8.252 | — | — | 61.065 | 5.364 | — | 1.251 | — | — | — | — |
| opencv/stlouis_1 | 0.514 | 0.497 | 0.024 | 0.302 | 0.648 | 7.120 | — | — | — | — | — | — | — | — | — | — |
| portfolio_single/01.BtS2Hkmp | 0.021 | 0.021 | 0.335 | 0.716 | 0.165 | 3.759 | — | — | — | — | — | — | — | — | — | — |
| portfolio_single/k007.C8MVnAJ9 | 0.241 | 0.241 | 0.214 | 0.699 | 0.129 | 2.788 | — | — | — | — | — | — | — | — | — | — |
| portfolio_single/k040.wqWqsOuE | 0.054 | 0.054 | 0.159 | 0.658 | 0.150 | 3.024 | — | — | — | — | — | — | — | — | — | — |

## Po: preset `airy`

| seria | clipped_% | clipped_excl_% | crushed_% | median_luma | vert_med_deg | wall_dE_auto | wall_dE_gt | wall_L_gt | win_L | win_clip_% | win_clip_recov_% | win_detail | halo_dL | ssim | ms_ssim | dE_ref |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| syntetyczne/IMG_0000 | 0.741 | 0.065 | 0.000 | 0.851 | 0.072 | 2.755 | 1.708 | 88.972 | 76.673 | 12.103 | 0.000 | — | 1.126 | 0.815 | 0.814 | 20.343 |
| syntetyczne/IMG_0005 | 5.998 | 0.000 | 0.003 | 0.849 | 0.048 | 2.119 | 1.473 | 83.309 | 76.733 | 42.117 | 0.000 | — | 0.504 | 0.900 | 0.880 | 13.053 |
| syntetyczne/IMG_0008 | 0.560 | 0.014 | 0.000 | 0.848 | 0.136 | 2.515 | 1.853 | 88.878 | 75.754 | 0.000 | 0.000 | — | -2.936 | 0.796 | 0.836 | 23.715 |
| syntetyczne/IMG_0015 | 3.500 | 0.000 | 0.000 | 0.844 | 0.025 | 0.651 | — | — | — | — | — | — | — | — | — | — |
| syntetyczne/IMG_0018 | 1.837 | 1.837 | 0.000 | 0.603 | 0.211 | 7.813 | — | — | 75.406 | 41.192 | — | 0.070 | — | — | — | — |
| syntetyczne/NOEXIF_0000 | 2.033 | 0.033 | 0.000 | 0.847 | 0.056 | 2.649 | — | — | 77.946 | 46.403 | — | 0.082 | — | — | — | — |
| hdrplus/HDRP_0000 | 8.287 | 0.545 | 0.000 | 0.859 | 0.315 | 4.023 | — | — | 83.115 | 62.097 | — | 0.152 | — | — | — | — |
| hdrplus/HDRP_0003 | 9.218 | 1.882 | 0.000 | 0.846 | 0.047 | 7.205 | — | — | 88.431 | 71.578 | — | 0.066 | — | — | — | — |
| hdrplus/HDRP_0006 | 0.179 | 0.179 | 0.000 | 0.844 | 0.294 | 4.522 | — | — | 75.545 | 0.000 | — | 0.232 | — | — | — | — |
| hdrplus/HDRP_0009 | 0.423 | 0.227 | 0.000 | 0.827 | 7.969 | 4.882 | — | — | 76.272 | 1.415 | — | 0.198 | — | — | — | — |
| hdrplus/HDRP_0012 | 0.419 | 0.097 | 0.000 | 0.849 | 0.739 | 5.336 | — | — | 78.250 | 4.782 | — | 0.181 | — | — | — | — |
| hdrplus/HDRP_0015 | 0.622 | 0.247 | 0.000 | 0.843 | 0.200 | 5.181 | — | — | 88.537 | 48.398 | — | 0.204 | — | — | — | — |
| opencv/memorial_0 | 3.648 | 3.392 | 0.093 | 0.845 | 5.180 | 7.052 | — | — | 64.612 | 5.190 | — | 1.382 | — | — | — | — |
| opencv/stlouis_1 | 0.503 | 0.486 | 0.003 | 0.316 | 0.502 | 6.890 | — | — | — | — | — | — | — | — | — | — |
| portfolio_single/01.BtS2Hkmp | 0.002 | 0.002 | 0.088 | 0.705 | 0.223 | 3.547 | — | — | — | — | — | — | — | — | — | — |
| portfolio_single/k007.C8MVnAJ9 | 0.171 | 0.171 | 0.139 | 0.690 | 0.121 | 2.607 | — | — | — | — | — | — | — | — | — | — |
| portfolio_single/k040.wqWqsOuE | 0.023 | 0.023 | 0.071 | 0.649 | 0.202 | 2.874 | — | — | — | — | — | — | — | — | — | — |

## Po: preset `premium`

| seria | clipped_% | clipped_excl_% | crushed_% | median_luma | vert_med_deg | wall_dE_auto | wall_dE_gt | wall_L_gt | win_L | win_clip_% | win_clip_recov_% | win_detail | halo_dL | ssim | ms_ssim | dE_ref |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| syntetyczne/IMG_0000 | 0.752 | 0.076 | 0.019 | 0.725 | 0.158 | 2.871 | 1.786 | 79.615 | 66.840 | 12.048 | 0.000 | — | 1.075 | 0.878 | 0.916 | 13.784 |
| syntetyczne/IMG_0005 | 6.009 | 0.000 | 0.034 | 0.718 | 0.049 | 2.356 | 1.317 | 69.448 | 67.102 | 41.752 | 0.000 | — | 0.482 | 0.896 | 0.904 | 8.690 |
| syntetyczne/IMG_0008 | 0.559 | 0.013 | 0.019 | 0.725 | 0.204 | 2.769 | 1.944 | 78.961 | 65.379 | 0.000 | 0.000 | — | -3.151 | 0.876 | 0.886 | 16.243 |
| syntetyczne/IMG_0015 | 3.490 | 0.000 | 0.000 | 0.714 | 0.016 | 0.808 | — | — | — | — | — | — | — | — | — | — |
| syntetyczne/IMG_0018 | 1.852 | 1.852 | 0.005 | 0.454 | 0.203 | 7.855 | — | — | 69.022 | 41.327 | — | 0.086 | — | — | — | — |
| syntetyczne/NOEXIF_0000 | 2.186 | 0.186 | 0.007 | 0.714 | 0.083 | 2.552 | — | — | 67.446 | 47.431 | — | 0.105 | — | — | — | — |
| hdrplus/HDRP_0000 | 8.289 | 0.548 | 0.017 | 0.738 | 0.311 | 4.767 | — | — | 76.069 | 60.887 | — | 0.199 | — | — | — | — |
| hdrplus/HDRP_0003 | 9.355 | 2.019 | 0.021 | 0.721 | 0.103 | 8.533 | — | — | 83.836 | 70.628 | — | 0.078 | — | — | — | — |
| hdrplus/HDRP_0006 | 0.220 | 0.220 | 0.009 | 0.712 | 0.302 | 5.197 | — | — | 65.515 | 0.000 | — | 0.218 | — | — | — | — |
| hdrplus/HDRP_0009 | 0.576 | 0.379 | 0.002 | 0.692 | 7.217 | 5.899 | — | — | 66.399 | 1.201 | — | 0.191 | — | — | — | — |
| hdrplus/HDRP_0012 | 0.536 | 0.214 | 0.001 | 0.720 | 1.835 | 6.451 | — | — | 68.807 | 4.742 | — | 0.183 | — | — | — | — |
| hdrplus/HDRP_0015 | 0.592 | 0.217 | 0.004 | 0.704 | 0.287 | 5.611 | — | — | 83.254 | 49.538 | — | 0.272 | — | — | — | — |
| opencv/memorial_0 | 3.389 | 3.133 | 0.104 | 0.712 | 2.851 | 8.173 | — | — | 58.539 | 5.423 | — | 1.328 | — | — | — | — |
| opencv/stlouis_1 | 0.552 | 0.535 | 0.062 | 0.299 | 0.677 | 7.134 | — | — | — | — | — | — | — | — | — | — |
| portfolio_single/01.BtS2Hkmp | 0.026 | 0.026 | 0.539 | 0.724 | 0.182 | 3.993 | — | — | — | — | — | — | — | — | — | — |
| portfolio_single/k007.C8MVnAJ9 | 0.337 | 0.337 | 0.241 | 0.707 | 0.123 | 2.875 | — | — | — | — | — | — | — | — | — | — |
| portfolio_single/k040.wqWqsOuE | 0.088 | 0.088 | 0.206 | 0.664 | 0.155 | 3.246 | — | — | — | — | — | — | — | — | — | — |

## Zestawienia (przed | neutral | airy | premium)

![hdrplus__HDRP_0000.jpg](hdrplus__HDRP_0000.jpg)
![hdrplus__HDRP_0003.jpg](hdrplus__HDRP_0003.jpg)
![hdrplus__HDRP_0006.jpg](hdrplus__HDRP_0006.jpg)
![hdrplus__HDRP_0009.jpg](hdrplus__HDRP_0009.jpg)
![hdrplus__HDRP_0012.jpg](hdrplus__HDRP_0012.jpg)
![hdrplus__HDRP_0015.jpg](hdrplus__HDRP_0015.jpg)
![opencv__memorial_0.jpg](opencv__memorial_0.jpg)
![opencv__stlouis_1.jpg](opencv__stlouis_1.jpg)
![portfolio_single__01.BtS2Hkmp.jpg](portfolio_single__01.BtS2Hkmp.jpg)
![portfolio_single__k007.C8MVnAJ9.jpg](portfolio_single__k007.C8MVnAJ9.jpg)
![portfolio_single__k040.wqWqsOuE.jpg](portfolio_single__k040.wqWqsOuE.jpg)
![syntetyczne__IMG_0000.jpg](syntetyczne__IMG_0000.jpg)
![syntetyczne__IMG_0005.jpg](syntetyczne__IMG_0005.jpg)
![syntetyczne__IMG_0008.jpg](syntetyczne__IMG_0008.jpg)
![syntetyczne__IMG_0015.jpg](syntetyczne__IMG_0015.jpg)
![syntetyczne__IMG_0018.jpg](syntetyczne__IMG_0018.jpg)
![syntetyczne__NOEXIF_0000.jpg](syntetyczne__NOEXIF_0000.jpg)
