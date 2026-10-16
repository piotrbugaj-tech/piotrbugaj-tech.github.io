# Porównania przed / po dla presetów

Wygenerowane przez `tools/make_comparisons.py` (pełny pipeline, metryki z `estatehdr/quality`).
Kolumny: klip = % pikseli z kanałem ≥ 254, klip_excl = bez obszarów przepalonych w każdej klatce, zaczernienie = % ≤ 1, pion = mediana odchylenia linii pionowych [°], ściana ΔE = neutralność bieli (CIEDE2000; _gt = maska ścian z GT), win_L = L* widoku za oknem (bez nieodzyskiwalnych pikseli), ssim/dE_ref = zgodność z idealną edycją GT.

## Preset `neutral`

| seria | clipped_% | clipped_excl_% | crushed_% | median_luma | vert_med_deg | wall_dE_auto | wall_dE_gt | wall_L_gt | win_L | win_clip_recov_% | halo_dL | ssim | ms_ssim | dE_ref |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| syntetyczne/IMG_0000 | 0.735 | 0.060 | 0.003 | 0.718 | 0.135 | 3.451 | 3.146 | 79.066 | 71.919 | 0.000 | 0.736 | 0.885 | 0.915 | 14.287 |
| syntetyczne/IMG_0005 | 6.038 | 0.000 | 0.012 | 0.712 | 0.040 | 3.597 | 3.249 | 69.526 | 71.945 | 0.000 | -0.029 | 0.910 | 0.910 | 10.397 |
| syntetyczne/IMG_0008 | 0.554 | 0.007 | 0.002 | 0.716 | 0.120 | 3.785 | 2.867 | 78.187 | 70.632 | 0.000 | -3.106 | 0.871 | 0.886 | 17.067 |
| syntetyczne/IMG_0015 | 3.478 | 0.000 | 0.007 | 0.706 | 0.024 | 0.978 | — | — | — | — | — | — | — | — |
| syntetyczne/IMG_0018 | 6.754 | 6.754 | 0.001 | 0.558 | 0.028 | 7.741 | — | — | — | — | — | — | — | — |
| syntetyczne/NOEXIF_0000 | 2.101 | 0.118 | 0.001 | 0.709 | 0.035 | 3.807 | — | — | — | — | — | — | — | — |
| hdrplus/HDRP_0000 | 8.186 | 0.445 | 0.009 | 0.733 | 0.327 | 4.808 | — | — | — | — | — | — | — | — |
| hdrplus/HDRP_0003 | 9.412 | 2.077 | 0.002 | 0.720 | 0.331 | 8.138 | — | — | — | — | — | — | — | — |
| hdrplus/HDRP_0006 | 0.286 | 0.286 | 0.004 | 0.705 | 0.364 | 4.817 | — | — | — | — | — | — | — | — |
| hdrplus/HDRP_0009 | 0.650 | 0.453 | 0.004 | 0.698 | 7.102 | 5.937 | — | — | — | — | — | — | — | — |
| hdrplus/HDRP_0012 | 0.503 | 0.181 | 0.000 | 0.715 | 1.739 | 6.636 | — | — | — | — | — | — | — | — |
| hdrplus/HDRP_0015 | 0.595 | 0.220 | 0.003 | 0.701 | 0.408 | 5.443 | — | — | — | — | — | — | — | — |
| opencv/memorial_0 | 3.703 | 3.448 | 0.068 | 0.702 | 6.065 | 7.670 | — | — | — | — | — | — | — | — |
| opencv/stlouis_1 | 0.580 | 0.563 | 0.023 | 0.304 | 0.603 | 7.149 | — | — | — | — | — | — | — | — |
| portfolio_single/01.BtS2Hkmp | 0.352 | 0.352 | 0.249 | 0.717 | 0.248 | 2.860 | — | — | — | — | — | — | — | — |
| portfolio_single/k007.C8MVnAJ9 | 0.657 | 0.657 | 0.266 | 0.699 | 0.133 | 1.969 | — | — | — | — | — | — | — | — |
| portfolio_single/k040.wqWqsOuE | 0.692 | 0.692 | 0.162 | 0.658 | 0.139 | 2.656 | — | — | — | — | — | — | — | — |

## Preset `airy`

| seria | clipped_% | clipped_excl_% | crushed_% | median_luma | vert_med_deg | wall_dE_auto | wall_dE_gt | wall_L_gt | win_L | win_clip_recov_% | halo_dL | ssim | ms_ssim | dE_ref |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| syntetyczne/IMG_0000 | 0.729 | 0.053 | 0.000 | 0.851 | 0.083 | 3.451 | 3.046 | 89.131 | 76.740 | 0.000 | 1.130 | 0.844 | 0.865 | 19.402 |
| syntetyczne/IMG_0005 | 6.019 | 0.000 | 0.004 | 0.849 | 0.055 | 3.626 | 3.221 | 83.317 | 76.568 | 0.000 | 0.621 | 0.903 | 0.881 | 14.003 |
| syntetyczne/IMG_0008 | 0.562 | 0.016 | 0.000 | 0.849 | 0.140 | 3.618 | 2.958 | 88.803 | 75.686 | 0.000 | -2.880 | 0.798 | 0.842 | 23.971 |
| syntetyczne/IMG_0015 | 3.494 | 0.000 | 0.000 | 0.842 | 0.054 | 0.826 | — | — | — | — | — | — | — | — |
| syntetyczne/IMG_0018 | 6.799 | 6.799 | 0.001 | 0.701 | 0.034 | 7.491 | — | — | — | — | — | — | — | — |
| syntetyczne/NOEXIF_0000 | 1.942 | 0.000 | 0.000 | 0.847 | 0.056 | 3.871 | — | — | — | — | — | — | — | — |
| hdrplus/HDRP_0000 | 8.224 | 0.483 | 0.004 | 0.859 | 0.361 | 4.108 | — | — | — | — | — | — | — | — |
| hdrplus/HDRP_0003 | 9.893 | 2.557 | 0.000 | 0.845 | 0.148 | 7.662 | — | — | — | — | — | — | — | — |
| hdrplus/HDRP_0006 | 0.258 | 0.258 | 0.002 | 0.841 | 0.356 | 4.237 | — | — | — | — | — | — | — | — |
| hdrplus/HDRP_0009 | 0.612 | 0.415 | 0.001 | 0.826 | 7.450 | 5.070 | — | — | — | — | — | — | — | — |
| hdrplus/HDRP_0012 | 0.425 | 0.103 | 0.000 | 0.848 | 0.622 | 5.544 | — | — | — | — | — | — | — | — |
| hdrplus/HDRP_0015 | 0.550 | 0.175 | 0.002 | 0.840 | 0.091 | 5.137 | — | — | — | — | — | — | — | — |
| opencv/memorial_0 | 5.182 | 4.926 | 0.102 | 0.843 | 2.439 | 7.785 | — | — | — | — | — | — | — | — |
| opencv/stlouis_1 | 0.578 | 0.561 | 0.006 | 0.314 | 0.696 | 6.798 | — | — | — | — | — | — | — | — |
| portfolio_single/01.BtS2Hkmp | 0.357 | 0.357 | 0.129 | 0.706 | 0.225 | 2.611 | — | — | — | — | — | — | — | — |
| portfolio_single/k007.C8MVnAJ9 | 0.666 | 0.666 | 0.152 | 0.699 | 0.140 | 1.783 | — | — | — | — | — | — | — | — |
| portfolio_single/k040.wqWqsOuE | 0.667 | 0.667 | 0.090 | 0.697 | 0.189 | 2.502 | — | — | — | — | — | — | — | — |

## Preset `premium`

| seria | clipped_% | clipped_excl_% | crushed_% | median_luma | vert_med_deg | wall_dE_auto | wall_dE_gt | wall_L_gt | win_L | win_clip_recov_% | halo_dL | ssim | ms_ssim | dE_ref |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| syntetyczne/IMG_0000 | 0.756 | 0.081 | 0.019 | 0.725 | 0.133 | 3.470 | 3.279 | 79.579 | 66.670 | 0.000 | 1.227 | 0.864 | 0.907 | 14.134 |
| syntetyczne/IMG_0005 | 6.060 | 0.000 | 0.056 | 0.717 | 0.042 | 3.385 | 3.281 | 69.408 | 66.811 | 0.000 | 0.464 | 0.899 | 0.907 | 10.270 |
| syntetyczne/IMG_0008 | 0.553 | 0.007 | 0.019 | 0.728 | 0.228 | 3.883 | 2.933 | 79.250 | 65.289 | 0.000 | -3.029 | 0.879 | 0.896 | 16.667 |
| syntetyczne/IMG_0015 | 3.487 | 0.000 | 0.026 | 0.714 | 0.021 | 0.995 | — | — | — | — | — | — | — | — |
| syntetyczne/IMG_0018 | 6.782 | 6.782 | 0.008 | 0.561 | 0.042 | 7.913 | — | — | — | — | — | — | — | — |
| syntetyczne/NOEXIF_0000 | 2.140 | 0.157 | 0.008 | 0.715 | 0.064 | 3.785 | — | — | — | — | — | — | — | — |
| hdrplus/HDRP_0000 | 8.253 | 0.511 | 0.030 | 0.737 | 0.343 | 4.833 | — | — | — | — | — | — | — | — |
| hdrplus/HDRP_0003 | 9.751 | 2.416 | 0.011 | 0.718 | 0.090 | 8.394 | — | — | — | — | — | — | — | — |
| hdrplus/HDRP_0006 | 0.307 | 0.307 | 0.029 | 0.711 | 0.230 | 4.857 | — | — | — | — | — | — | — | — |
| hdrplus/HDRP_0009 | 0.743 | 0.547 | 0.008 | 0.688 | 7.116 | 6.003 | — | — | — | — | — | — | — | — |
| hdrplus/HDRP_0012 | 0.548 | 0.225 | 0.003 | 0.718 | 1.946 | 6.662 | — | — | — | — | — | — | — | — |
| hdrplus/HDRP_0015 | 0.588 | 0.214 | 0.015 | 0.705 | 0.439 | 5.585 | — | — | — | — | — | — | — | — |
| opencv/memorial_0 | 4.014 | 3.758 | 0.092 | 0.709 | 5.224 | 7.753 | — | — | — | — | — | — | — | — |
| opencv/stlouis_1 | 0.636 | 0.619 | 0.050 | 0.299 | 0.609 | 7.205 | — | — | — | — | — | — | — | — |
| portfolio_single/01.BtS2Hkmp | 0.366 | 0.366 | 0.394 | 0.725 | 0.189 | 3.037 | — | — | — | — | — | — | — | — |
| portfolio_single/k007.C8MVnAJ9 | 0.800 | 0.800 | 0.286 | 0.707 | 0.127 | 2.061 | — | — | — | — | — | — | — | — |
| portfolio_single/k040.wqWqsOuE | 0.809 | 0.809 | 0.282 | 0.663 | 0.172 | 2.810 | — | — | — | — | — | — | — | — |

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
