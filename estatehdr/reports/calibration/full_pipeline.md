# Pełny pipeline przed / po kalibracji

Wejście: `data/synthetic/input`. Konfiguracja przed: `reports/calibration/config_before_full.yaml`, po: `config.yaml`. Ten sam kod, różnią się tylko parametry.

## Preset `neutral`: średnie (serie z GT dla metryk GT)

| metryka | przed | po | zmiana |
|---|---|---|---|
| przepalenia poza nieodzyskiwalnymi [%] | 0.354 | 0.349 | lepiej |
| zaczernienia [%] | 0.002 | 0.003 | = |
| mediana jasności | 0.570 | 0.669 |  |
| pionowość, mediana [°] | 0.092 | 0.095 | gorzej |
| neutralność jasnych powierzchni ΔE (auto) | 4.433 | 3.130 | lepiej |
| neutralność ścian ΔE (GT) | 4.956 | 1.623 | lepiej |
| jasność ścian L* (GT; cel SPEC: neutral 78-88, airy 84-92, premium 74-86) | 62.670 | 75.616 |  |
| jasność widoku okna L* (cel 55-80) | 74.828 | 72.002 |  |
| przepalenia okna odzyskiwalne [%] | 0.000 | 0.000 | = |
| detal okna / GT | 1.064 | 1.036 |  |
| halo przy oknie ΔL* (cel < 4) | -0.650 | -0.901 |  |
| przepalenia poza światłami (GT) [%] | 0.026 | 0.025 | lepiej |
| SSIM do idealnej edycji | 0.921 | 0.890 | gorzej |
| MS-SSIM do idealnej edycji | 0.932 | 0.904 | gorzej |
| gradient-SSIM (krawędzie) do idealnej edycji | 0.911 | 0.880 | gorzej |
| ΔE2000 do idealnej edycji | 9.769 | 13.152 | gorzej |

### Preset `neutral`: serie

| seria | metryka | przed | po |
|---|---|---|---|
| IMG_0000 | clipped_excl_% | 0.078 | 0.071 |
| IMG_0000 | crushed_% | 0.002 | 0.003 |
| IMG_0000 | median_luma | 0.582 | 0.718 |
| IMG_0000 | vert_med_deg | 0.103 | 0.137 |
| IMG_0000 | wall_dE_auto | 4.394 | 2.828 |
| IMG_0000 | wall_dE_gt | 5.156 | 1.700 |
| IMG_0000 | wall_L_gt | 67.227 | 79.147 |
| IMG_0000 | win_L | 76.024 | 71.984 |
| IMG_0000 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0000 | win_detail_ratio | 1.040 | 0.987 |
| IMG_0000 | halo_dL | 0.736 | 0.651 |
| IMG_0000 | clipped_nonlight_% | 0.019 | 0.021 |
| IMG_0000 | ssim | 0.926 | 0.891 |
| IMG_0000 | ms_ssim | 0.942 | 0.917 |
| IMG_0000 | grad_ssim | 0.916 | 0.903 |
| IMG_0000 | dE_ref | 9.346 | 14.006 |
| IMG_0005 | clipped_excl_% | 0.000 | 0.000 |
| IMG_0005 | crushed_% | 0.010 | 0.010 |
| IMG_0005 | median_luma | 0.606 | 0.713 |
| IMG_0005 | vert_med_deg | 0.044 | 0.042 |
| IMG_0005 | wall_dE_auto | 5.510 | 2.387 |
| IMG_0005 | wall_dE_gt | 3.620 | 1.302 |
| IMG_0005 | wall_L_gt | 54.809 | 69.479 |
| IMG_0005 | win_L | 74.350 | 72.094 |
| IMG_0005 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0005 | win_detail_ratio | 1.093 | 1.127 |
| IMG_0005 | halo_dL | 0.059 | -0.038 |
| IMG_0005 | clipped_nonlight_% | 0.051 | 0.045 |
| IMG_0005 | ssim | 0.901 | 0.908 |
| IMG_0005 | ms_ssim | 0.923 | 0.908 |
| IMG_0005 | grad_ssim | 0.911 | 0.880 |
| IMG_0005 | dE_ref | 8.911 | 8.775 |
| IMG_0008 | clipped_excl_% | 0.021 | 0.005 |
| IMG_0008 | crushed_% | 0.001 | 0.003 |
| IMG_0008 | median_luma | 0.585 | 0.717 |
| IMG_0008 | vert_med_deg | 0.159 | 0.114 |
| IMG_0008 | wall_dE_auto | 3.810 | 2.659 |
| IMG_0008 | wall_dE_gt | 6.092 | 1.867 |
| IMG_0008 | wall_L_gt | 65.975 | 78.221 |
| IMG_0008 | win_L | 74.585 | 70.682 |
| IMG_0008 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0008 | win_detail_ratio | 1.059 | 0.996 |
| IMG_0008 | halo_dL | -2.746 | -3.315 |
| IMG_0008 | clipped_nonlight_% | 0.009 | 0.008 |
| IMG_0008 | ssim | 0.936 | 0.872 |
| IMG_0008 | ms_ssim | 0.931 | 0.887 |
| IMG_0008 | grad_ssim | 0.907 | 0.858 |
| IMG_0008 | dE_ref | 11.051 | 16.675 |
| IMG_0015 | clipped_excl_% | 0.000 | 0.000 |
| IMG_0015 | crushed_% | 0.000 | 0.000 |
| IMG_0015 | median_luma | 0.561 | 0.706 |
| IMG_0015 | vert_med_deg | 0.023 | 0.025 |
| IMG_0015 | wall_dE_auto | 2.044 | 0.794 |
| IMG_0018 | clipped_excl_% | 1.850 | 1.850 |
| IMG_0018 | crushed_% | 0.002 | 0.002 |
| IMG_0018 | median_luma | 0.517 | 0.455 |
| IMG_0018 | vert_med_deg | 0.181 | 0.167 |
| IMG_0018 | wall_dE_auto | 7.021 | 7.551 |
| IMG_0018 | win_L | 74.176 | 72.442 |
| NOEXIF_0000 | clipped_excl_% | 0.173 | 0.171 |
| NOEXIF_0000 | crushed_% | 0.000 | 0.001 |
| NOEXIF_0000 | median_luma | 0.569 | 0.707 |
| NOEXIF_0000 | vert_med_deg | 0.044 | 0.086 |
| NOEXIF_0000 | wall_dE_auto | 3.817 | 2.562 |
| NOEXIF_0000 | win_L | 75.006 | 72.810 |

## Preset `airy`: średnie (serie z GT dla metryk GT)

| metryka | przed | po | zmiana |
|---|---|---|---|
| przepalenia poza nieodzyskiwalnymi [%] | 0.349 | 0.325 | lepiej |
| zaczernienia [%] | 0.000 | 0.001 | = |
| mediana jasności | 0.625 | 0.807 |  |
| pionowość, mediana [°] | 0.091 | 0.091 | = |
| neutralność jasnych powierzchni ΔE (auto) | 4.297 | 3.084 | lepiej |
| neutralność ścian ΔE (GT) | 4.915 | 1.678 | lepiej |
| jasność ścian L* (GT; cel SPEC: neutral 78-88, airy 84-92, premium 74-86) | 67.795 | 87.053 |  |
| jasność widoku okna L* (cel 55-80) | 79.285 | 76.502 |  |
| przepalenia okna odzyskiwalne [%] | 0.000 | 0.000 | = |
| detal okna / GT | 0.938 | 1.128 |  |
| halo przy oknie ΔL* (cel < 4) | -0.853 | -0.435 |  |
| przepalenia poza światłami (GT) [%] | 0.020 | 0.023 | gorzej |
| SSIM do idealnej edycji | 0.923 | 0.837 | gorzej |
| MS-SSIM do idealnej edycji | 0.927 | 0.843 | gorzej |
| gradient-SSIM (krawędzie) do idealnej edycji | 0.896 | 0.841 | gorzej |
| ΔE2000 do idealnej edycji | 11.101 | 19.037 | gorzej |

### Preset `airy`: serie

| seria | metryka | przed | po |
|---|---|---|---|
| IMG_0000 | clipped_excl_% | 0.066 | 0.065 |
| IMG_0000 | crushed_% | 0.000 | 0.000 |
| IMG_0000 | median_luma | 0.636 | 0.851 |
| IMG_0000 | vert_med_deg | 0.096 | 0.072 |
| IMG_0000 | wall_dE_auto | 4.196 | 2.755 |
| IMG_0000 | wall_dE_gt | 5.050 | 1.708 |
| IMG_0000 | wall_L_gt | 71.794 | 88.972 |
| IMG_0000 | win_L | 80.571 | 76.673 |
| IMG_0000 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0000 | win_detail_ratio | 0.928 | 1.093 |
| IMG_0000 | halo_dL | 0.659 | 1.126 |
| IMG_0000 | clipped_nonlight_% | 0.012 | 0.023 |
| IMG_0000 | ssim | 0.935 | 0.815 |
| IMG_0000 | ms_ssim | 0.938 | 0.814 |
| IMG_0000 | grad_ssim | 0.909 | 0.837 |
| IMG_0000 | dE_ref | 11.482 | 20.343 |
| IMG_0005 | clipped_excl_% | 0.000 | 0.000 |
| IMG_0005 | crushed_% | 0.002 | 0.003 |
| IMG_0005 | median_luma | 0.659 | 0.849 |
| IMG_0005 | vert_med_deg | 0.038 | 0.048 |
| IMG_0005 | wall_dE_auto | 5.263 | 2.119 |
| IMG_0005 | wall_dE_gt | 3.603 | 1.473 |
| IMG_0005 | wall_L_gt | 60.739 | 83.309 |
| IMG_0005 | win_L | 79.109 | 76.733 |
| IMG_0005 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0005 | win_detail_ratio | 0.933 | 1.128 |
| IMG_0005 | halo_dL | -0.234 | 0.504 |
| IMG_0005 | clipped_nonlight_% | 0.038 | 0.029 |
| IMG_0005 | ssim | 0.925 | 0.900 |
| IMG_0005 | ms_ssim | 0.922 | 0.880 |
| IMG_0005 | grad_ssim | 0.897 | 0.848 |
| IMG_0005 | dE_ref | 8.090 | 13.053 |
| IMG_0008 | clipped_excl_% | 0.014 | 0.014 |
| IMG_0008 | crushed_% | 0.000 | 0.000 |
| IMG_0008 | median_luma | 0.639 | 0.848 |
| IMG_0008 | vert_med_deg | 0.152 | 0.136 |
| IMG_0008 | wall_dE_auto | 3.769 | 2.515 |
| IMG_0008 | wall_dE_gt | 6.092 | 1.853 |
| IMG_0008 | wall_L_gt | 70.851 | 88.878 |
| IMG_0008 | win_L | 79.318 | 75.754 |
| IMG_0008 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0008 | win_detail_ratio | 0.953 | 1.164 |
| IMG_0008 | halo_dL | -2.983 | -2.936 |
| IMG_0008 | clipped_nonlight_% | 0.008 | 0.016 |
| IMG_0008 | ssim | 0.908 | 0.796 |
| IMG_0008 | ms_ssim | 0.920 | 0.836 |
| IMG_0008 | grad_ssim | 0.880 | 0.838 |
| IMG_0008 | dE_ref | 13.732 | 23.715 |
| IMG_0015 | clipped_excl_% | 0.000 | 0.000 |
| IMG_0015 | crushed_% | 0.000 | 0.000 |
| IMG_0015 | median_luma | 0.616 | 0.844 |
| IMG_0015 | vert_med_deg | 0.025 | 0.025 |
| IMG_0015 | wall_dE_auto | 1.909 | 0.651 |
| IMG_0018 | clipped_excl_% | 1.835 | 1.837 |
| IMG_0018 | crushed_% | 0.000 | 0.000 |
| IMG_0018 | median_luma | 0.574 | 0.603 |
| IMG_0018 | vert_med_deg | 0.186 | 0.211 |
| IMG_0018 | wall_dE_auto | 6.947 | 7.813 |
| IMG_0018 | win_L | 77.906 | 75.406 |
| NOEXIF_0000 | clipped_excl_% | 0.179 | 0.033 |
| NOEXIF_0000 | crushed_% | 0.000 | 0.000 |
| NOEXIF_0000 | median_luma | 0.624 | 0.847 |
| NOEXIF_0000 | vert_med_deg | 0.048 | 0.056 |
| NOEXIF_0000 | wall_dE_auto | 3.698 | 2.649 |
| NOEXIF_0000 | win_L | 79.521 | 77.946 |

## Preset `premium`: średnie (serie z GT dla metryk GT)

| metryka | przed | po | zmiana |
|---|---|---|---|
| przepalenia poza nieodzyskiwalnymi [%] | 0.362 | 0.354 | lepiej |
| zaczernienia [%] | 0.013 | 0.014 | = |
| mediana jasności | 0.552 | 0.675 |  |
| pionowość, mediana [°] | 0.085 | 0.119 | gorzej |
| neutralność jasnych powierzchni ΔE (auto) | 4.454 | 3.202 | lepiej |
| neutralność ścian ΔE (GT) | 5.022 | 1.682 | lepiej |
| jasność ścian L* (GT; cel SPEC: neutral 78-88, airy 84-92, premium 74-86) | 60.955 | 76.008 |  |
| jasność widoku okna L* (cel 55-80) | 71.241 | 67.158 |  |
| przepalenia okna odzyskiwalne [%] | 0.000 | 0.000 | = |
| detal okna / GT | 1.220 | 1.219 |  |
| halo przy oknie ΔL* (cel < 4) | -0.780 | -0.531 |  |
| przepalenia poza światłami (GT) [%] | 0.036 | 0.022 | lepiej |
| SSIM do idealnej edycji | 0.907 | 0.883 | gorzej |
| MS-SSIM do idealnej edycji | 0.928 | 0.902 | gorzej |
| gradient-SSIM (krawędzie) do idealnej edycji | 0.903 | 0.895 | gorzej |
| ΔE2000 do idealnej edycji | 9.617 | 12.906 | gorzej |

### Preset `premium`: serie

| seria | metryka | przed | po |
|---|---|---|---|
| IMG_0000 | clipped_excl_% | 0.089 | 0.076 |
| IMG_0000 | crushed_% | 0.016 | 0.019 |
| IMG_0000 | median_luma | 0.565 | 0.725 |
| IMG_0000 | vert_med_deg | 0.095 | 0.158 |
| IMG_0000 | wall_dE_auto | 4.531 | 2.871 |
| IMG_0000 | wall_dE_gt | 5.252 | 1.786 |
| IMG_0000 | wall_L_gt | 65.829 | 79.615 |
| IMG_0000 | win_L | 72.202 | 66.840 |
| IMG_0000 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0000 | win_detail_ratio | 1.209 | 1.153 |
| IMG_0000 | halo_dL | 0.663 | 1.075 |
| IMG_0000 | clipped_nonlight_% | 0.018 | 0.015 |
| IMG_0000 | ssim | 0.908 | 0.878 |
| IMG_0000 | ms_ssim | 0.939 | 0.916 |
| IMG_0000 | grad_ssim | 0.907 | 0.915 |
| IMG_0000 | dE_ref | 8.785 | 13.784 |
| IMG_0005 | clipped_excl_% | 0.000 | 0.000 |
| IMG_0005 | crushed_% | 0.033 | 0.034 |
| IMG_0005 | median_luma | 0.587 | 0.718 |
| IMG_0005 | vert_med_deg | 0.053 | 0.049 |
| IMG_0005 | wall_dE_auto | 5.427 | 2.356 |
| IMG_0005 | wall_dE_gt | 3.683 | 1.317 |
| IMG_0005 | wall_L_gt | 52.435 | 69.448 |
| IMG_0005 | win_L | 71.373 | 67.102 |
| IMG_0005 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0005 | win_detail_ratio | 1.235 | 1.308 |
| IMG_0005 | halo_dL | 0.030 | 0.482 |
| IMG_0005 | clipped_nonlight_% | 0.081 | 0.039 |
| IMG_0005 | ssim | 0.878 | 0.896 |
| IMG_0005 | ms_ssim | 0.915 | 0.904 |
| IMG_0005 | grad_ssim | 0.897 | 0.892 |
| IMG_0005 | dE_ref | 9.707 | 8.690 |
| IMG_0008 | clipped_excl_% | 0.025 | 0.013 |
| IMG_0008 | crushed_% | 0.015 | 0.019 |
| IMG_0008 | median_luma | 0.566 | 0.725 |
| IMG_0008 | vert_med_deg | 0.139 | 0.204 |
| IMG_0008 | wall_dE_auto | 3.630 | 2.769 |
| IMG_0008 | wall_dE_gt | 6.132 | 1.944 |
| IMG_0008 | wall_L_gt | 64.601 | 78.961 |
| IMG_0008 | win_L | 70.438 | 65.379 |
| IMG_0008 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0008 | win_detail_ratio | 1.217 | 1.197 |
| IMG_0008 | halo_dL | -3.031 | -3.151 |
| IMG_0008 | clipped_nonlight_% | 0.011 | 0.013 |
| IMG_0008 | ssim | 0.934 | 0.876 |
| IMG_0008 | ms_ssim | 0.928 | 0.886 |
| IMG_0008 | grad_ssim | 0.904 | 0.879 |
| IMG_0008 | dE_ref | 10.360 | 16.243 |
| IMG_0015 | clipped_excl_% | 0.000 | 0.000 |
| IMG_0015 | crushed_% | 0.000 | 0.000 |
| IMG_0015 | median_luma | 0.543 | 0.714 |
| IMG_0015 | vert_med_deg | 0.020 | 0.016 |
| IMG_0015 | wall_dE_auto | 2.069 | 0.808 |
| IMG_0018 | clipped_excl_% | 1.853 | 1.852 |
| IMG_0018 | crushed_% | 0.006 | 0.005 |
| IMG_0018 | median_luma | 0.497 | 0.454 |
| IMG_0018 | vert_med_deg | 0.143 | 0.203 |
| IMG_0018 | wall_dE_auto | 7.268 | 7.855 |
| IMG_0018 | win_L | 70.709 | 69.022 |
| NOEXIF_0000 | clipped_excl_% | 0.203 | 0.186 |
| NOEXIF_0000 | crushed_% | 0.009 | 0.007 |
| NOEXIF_0000 | median_luma | 0.551 | 0.714 |
| NOEXIF_0000 | vert_med_deg | 0.057 | 0.083 |
| NOEXIF_0000 | wall_dE_auto | 3.799 | 2.552 |
| NOEXIF_0000 | win_L | 71.483 | 67.446 |

