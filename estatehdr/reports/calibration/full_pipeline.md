# Pełny pipeline przed / po kalibracji

Wejście: `data/synthetic/input`. Konfiguracja przed: `reports/calibration/config_before_full.yaml`, po: `config.yaml`. Ten sam kod, różnią się tylko parametry.

## Preset `neutral`: średnie (serie z GT dla metryk GT)

| metryka | przed | po | zmiana |
|---|---|---|---|
| przepalenia poza nieodzyskiwalnymi [%] | 0.390 | 0.412 | gorzej |
| zaczernienia [%] | 0.002 | 0.003 | gorzej |
| mediana jasności | 0.570 | 0.687 |  |
| pionowość, mediana [°] | 0.070 | 0.097 | gorzej |
| neutralność jasnych powierzchni ΔE (auto) | 4.907 | 3.896 | lepiej |
| neutralność ścian ΔE (GT) | 5.530 | 3.064 | lepiej |
| jasność ścian L* (GT; cel SPEC: neutral 78-88, airy 84-92, premium 74-86) | 62.672 | 75.635 |  |
| jasność widoku okna L* (cel 55-80) | 75.031 | 71.990 |  |
| przepalenia okna odzyskiwalne [%] | 0.000 | 0.000 | = |
| detal okna / GT | 1.064 | 1.036 |  |
| halo przy oknie ΔL* (cel < 4) | -0.687 | -0.898 |  |
| przepalenia poza światłami (GT) [%] | 0.027 | 0.029 | gorzej |
| SSIM do idealnej edycji | 0.917 | 0.889 | gorzej |
| MS-SSIM do idealnej edycji | 0.928 | 0.904 | gorzej |
| gradient-SSIM (krawędzie) do idealnej edycji | 0.905 | 0.879 | gorzej |
| ΔE2000 do idealnej edycji | 10.257 | 13.870 | gorzej |

### Preset `neutral`: serie

| seria | metryka | przed | po |
|---|---|---|---|
| IMG_0000 | clipped_excl_% | 0.075 | 0.060 |
| IMG_0000 | crushed_% | 0.001 | 0.004 |
| IMG_0000 | median_luma | 0.582 | 0.718 |
| IMG_0000 | vert_med_deg | 0.084 | 0.104 |
| IMG_0000 | wall_dE_auto | 4.682 | 3.456 |
| IMG_0000 | wall_dE_gt | 6.059 | 3.144 |
| IMG_0000 | wall_L_gt | 67.081 | 79.099 |
| IMG_0000 | win_L | 75.998 | 72.050 |
| IMG_0000 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0000 | win_detail_ratio | 1.042 | 0.986 |
| IMG_0000 | halo_dL | 0.771 | 0.713 |
| IMG_0000 | clipped_nonlight_% | 0.014 | 0.015 |
| IMG_0000 | ssim | 0.923 | 0.891 |
| IMG_0000 | ms_ssim | 0.938 | 0.919 |
| IMG_0000 | grad_ssim | 0.912 | 0.904 |
| IMG_0000 | dE_ref | 9.792 | 14.192 |
| IMG_0005 | clipped_excl_% | 0.000 | 0.000 |
| IMG_0005 | crushed_% | 0.009 | 0.009 |
| IMG_0005 | median_luma | 0.606 | 0.713 |
| IMG_0005 | vert_med_deg | 0.055 | 0.056 |
| IMG_0005 | wall_dE_auto | 5.412 | 3.578 |
| IMG_0005 | wall_dE_gt | 4.109 | 3.191 |
| IMG_0005 | wall_L_gt | 54.803 | 69.417 |
| IMG_0005 | win_L | 74.375 | 72.082 |
| IMG_0005 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0005 | win_detail_ratio | 1.092 | 1.122 |
| IMG_0005 | halo_dL | 0.138 | -0.137 |
| IMG_0005 | clipped_nonlight_% | 0.060 | 0.062 |
| IMG_0005 | ssim | 0.900 | 0.907 |
| IMG_0005 | ms_ssim | 0.923 | 0.909 |
| IMG_0005 | grad_ssim | 0.909 | 0.878 |
| IMG_0005 | dE_ref | 9.661 | 10.402 |
| IMG_0008 | clipped_excl_% | 0.020 | 0.007 |
| IMG_0008 | crushed_% | 0.000 | 0.002 |
| IMG_0008 | median_luma | 0.583 | 0.716 |
| IMG_0008 | vert_med_deg | 0.155 | 0.175 |
| IMG_0008 | wall_dE_auto | 4.184 | 3.788 |
| IMG_0008 | wall_dE_gt | 6.422 | 2.856 |
| IMG_0008 | wall_L_gt | 66.132 | 78.388 |
| IMG_0008 | win_L | 74.581 | 70.692 |
| IMG_0008 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0008 | win_detail_ratio | 1.057 | 0.999 |
| IMG_0008 | halo_dL | -2.970 | -3.270 |
| IMG_0008 | clipped_nonlight_% | 0.009 | 0.010 |
| IMG_0008 | ssim | 0.928 | 0.869 |
| IMG_0008 | ms_ssim | 0.924 | 0.883 |
| IMG_0008 | grad_ssim | 0.893 | 0.856 |
| IMG_0008 | dE_ref | 11.320 | 17.018 |
| IMG_0015 | clipped_excl_% | 0.000 | 0.000 |
| IMG_0015 | crushed_% | 0.000 | 0.000 |
| IMG_0015 | median_luma | 0.561 | 0.707 |
| IMG_0015 | vert_med_deg | 0.021 | 0.027 |
| IMG_0015 | wall_dE_auto | 3.763 | 0.966 |
| IMG_0018 | clipped_excl_% | 2.119 | 2.300 |
| IMG_0018 | crushed_% | 0.001 | 0.001 |
| IMG_0018 | median_luma | 0.516 | 0.562 |
| IMG_0018 | vert_med_deg | 0.047 | 0.147 |
| IMG_0018 | wall_dE_auto | 7.002 | 7.778 |
| IMG_0018 | win_L | 76.037 | 72.885 |
| NOEXIF_0000 | clipped_excl_% | 0.129 | 0.106 |
| NOEXIF_0000 | crushed_% | 0.000 | 0.002 |
| NOEXIF_0000 | median_luma | 0.573 | 0.709 |
| NOEXIF_0000 | vert_med_deg | 0.058 | 0.075 |
| NOEXIF_0000 | wall_dE_auto | 4.400 | 3.807 |
| NOEXIF_0000 | win_L | 74.164 | 72.239 |

## Preset `airy`: średnie (serie z GT dla metryk GT)

| metryka | przed | po | zmiana |
|---|---|---|---|
| przepalenia poza nieodzyskiwalnymi [%] | 0.389 | 0.421 | gorzej |
| zaczernienia [%] | 0.000 | 0.001 | = |
| mediana jasności | 0.625 | 0.823 |  |
| pionowość, mediana [°] | 0.082 | 0.098 | gorzej |
| neutralność jasnych powierzchni ΔE (auto) | 4.758 | 3.813 | lepiej |
| neutralność ścian ΔE (GT) | 5.521 | 3.028 | lepiej |
| jasność ścian L* (GT; cel SPEC: neutral 78-88, airy 84-92, premium 74-86) | 67.695 | 87.107 |  |
| jasność widoku okna L* (cel 55-80) | 79.594 | 76.420 |  |
| przepalenia okna odzyskiwalne [%] | 0.000 | 0.000 | = |
| detal okna / GT | 0.939 | 1.118 |  |
| halo przy oknie ΔL* (cel < 4) | -0.880 | -0.472 |  |
| przepalenia poza światłami (GT) [%] | 0.020 | 0.020 | = |
| SSIM do idealnej edycji | 0.925 | 0.849 | gorzej |
| MS-SSIM do idealnej edycji | 0.928 | 0.864 | gorzej |
| gradient-SSIM (krawędzie) do idealnej edycji | 0.897 | 0.851 | gorzej |
| ΔE2000 do idealnej edycji | 11.554 | 19.001 | gorzej |

### Preset `airy`: serie

| seria | metryka | przed | po |
|---|---|---|---|
| IMG_0000 | clipped_excl_% | 0.067 | 0.049 |
| IMG_0000 | crushed_% | 0.000 | 0.001 |
| IMG_0000 | median_luma | 0.636 | 0.851 |
| IMG_0000 | vert_med_deg | 0.097 | 0.082 |
| IMG_0000 | wall_dE_auto | 4.500 | 3.459 |
| IMG_0000 | wall_dE_gt | 5.944 | 3.011 |
| IMG_0000 | wall_L_gt | 71.706 | 89.166 |
| IMG_0000 | win_L | 80.545 | 76.800 |
| IMG_0000 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0000 | win_detail_ratio | 0.930 | 1.062 |
| IMG_0000 | halo_dL | 0.633 | 1.165 |
| IMG_0000 | clipped_nonlight_% | 0.013 | 0.010 |
| IMG_0000 | ssim | 0.933 | 0.846 |
| IMG_0000 | ms_ssim | 0.938 | 0.869 |
| IMG_0000 | grad_ssim | 0.907 | 0.862 |
| IMG_0000 | dE_ref | 11.789 | 19.262 |
| IMG_0005 | clipped_excl_% | 0.000 | 0.000 |
| IMG_0005 | crushed_% | 0.002 | 0.003 |
| IMG_0005 | median_luma | 0.659 | 0.849 |
| IMG_0005 | vert_med_deg | 0.044 | 0.045 |
| IMG_0005 | wall_dE_auto | 5.167 | 3.632 |
| IMG_0005 | wall_dE_gt | 4.139 | 3.138 |
| IMG_0005 | wall_L_gt | 60.746 | 83.331 |
| IMG_0005 | win_L | 79.086 | 76.780 |
| IMG_0005 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0005 | win_detail_ratio | 0.933 | 1.129 |
| IMG_0005 | halo_dL | -0.317 | 0.437 |
| IMG_0005 | clipped_nonlight_% | 0.040 | 0.031 |
| IMG_0005 | ssim | 0.925 | 0.901 |
| IMG_0005 | ms_ssim | 0.922 | 0.879 |
| IMG_0005 | grad_ssim | 0.896 | 0.849 |
| IMG_0005 | dE_ref | 8.988 | 13.895 |
| IMG_0008 | clipped_excl_% | 0.010 | 0.018 |
| IMG_0008 | crushed_% | 0.000 | 0.000 |
| IMG_0008 | median_luma | 0.637 | 0.849 |
| IMG_0008 | vert_med_deg | 0.194 | 0.114 |
| IMG_0008 | wall_dE_auto | 4.150 | 3.615 |
| IMG_0008 | wall_dE_gt | 6.479 | 2.936 |
| IMG_0008 | wall_L_gt | 70.632 | 88.824 |
| IMG_0008 | win_L | 79.332 | 75.752 |
| IMG_0008 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0008 | win_detail_ratio | 0.954 | 1.163 |
| IMG_0008 | halo_dL | -2.956 | -3.018 |
| IMG_0008 | clipped_nonlight_% | 0.008 | 0.018 |
| IMG_0008 | ssim | 0.916 | 0.800 |
| IMG_0008 | ms_ssim | 0.924 | 0.844 |
| IMG_0008 | grad_ssim | 0.889 | 0.843 |
| IMG_0008 | dE_ref | 13.886 | 23.846 |
| IMG_0015 | clipped_excl_% | 0.000 | 0.000 |
| IMG_0015 | crushed_% | 0.000 | 0.000 |
| IMG_0015 | median_luma | 0.616 | 0.844 |
| IMG_0015 | vert_med_deg | 0.025 | 0.067 |
| IMG_0015 | wall_dE_auto | 3.594 | 0.952 |
| IMG_0018 | clipped_excl_% | 2.145 | 2.326 |
| IMG_0018 | crushed_% | 0.000 | 0.000 |
| IMG_0018 | median_luma | 0.574 | 0.697 |
| IMG_0018 | vert_med_deg | 0.057 | 0.229 |
| IMG_0018 | wall_dE_auto | 6.734 | 7.537 |
| IMG_0018 | win_L | 80.196 | 76.032 |
| NOEXIF_0000 | clipped_excl_% | 0.112 | 0.134 |
| NOEXIF_0000 | crushed_% | 0.000 | 0.000 |
| NOEXIF_0000 | median_luma | 0.627 | 0.847 |
| NOEXIF_0000 | vert_med_deg | 0.074 | 0.051 |
| NOEXIF_0000 | wall_dE_auto | 4.403 | 3.682 |
| NOEXIF_0000 | win_L | 78.810 | 76.735 |

## Preset `premium`: średnie (serie z GT dla metryk GT)

| metryka | przed | po | zmiana |
|---|---|---|---|
| przepalenia poza nieodzyskiwalnymi [%] | 0.399 | 0.458 | gorzej |
| zaczernienia [%] | 0.014 | 0.014 | = |
| mediana jasności | 0.552 | 0.693 |  |
| pionowość, mediana [°] | 0.073 | 0.101 | gorzej |
| neutralność jasnych powierzchni ΔE (auto) | 4.896 | 3.930 | lepiej |
| neutralność ścian ΔE (GT) | 5.577 | 3.143 | lepiej |
| jasność ścian L* (GT; cel SPEC: neutral 78-88, airy 84-92, premium 74-86) | 61.002 | 76.009 |  |
| jasność widoku okna L* (cel 55-80) | 71.546 | 66.529 |  |
| przepalenia okna odzyskiwalne [%] | 0.000 | 0.000 | = |
| detal okna / GT | 1.221 | 1.222 |  |
| halo przy oknie ΔL* (cel < 4) | -0.784 | -0.509 |  |
| przepalenia poza światłami (GT) [%] | 0.043 | 0.034 | lepiej |
| SSIM do idealnej edycji | 0.902 | 0.884 | gorzej |
| MS-SSIM do idealnej edycji | 0.926 | 0.903 | gorzej |
| gradient-SSIM (krawędzie) do idealnej edycji | 0.897 | 0.896 | = |
| ΔE2000 do idealnej edycji | 10.077 | 13.606 | gorzej |

### Preset `premium`: serie

| seria | metryka | przed | po |
|---|---|---|---|
| IMG_0000 | clipped_excl_% | 0.092 | 0.076 |
| IMG_0000 | crushed_% | 0.016 | 0.018 |
| IMG_0000 | median_luma | 0.564 | 0.725 |
| IMG_0000 | vert_med_deg | 0.103 | 0.081 |
| IMG_0000 | wall_dE_auto | 4.828 | 3.474 |
| IMG_0000 | wall_dE_gt | 6.137 | 3.256 |
| IMG_0000 | wall_L_gt | 65.947 | 79.614 |
| IMG_0000 | win_L | 72.209 | 66.836 |
| IMG_0000 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0000 | win_detail_ratio | 1.213 | 1.156 |
| IMG_0000 | halo_dL | 0.683 | 1.175 |
| IMG_0000 | clipped_nonlight_% | 0.018 | 0.014 |
| IMG_0000 | ssim | 0.900 | 0.878 |
| IMG_0000 | ms_ssim | 0.935 | 0.916 |
| IMG_0000 | grad_ssim | 0.896 | 0.914 |
| IMG_0000 | dE_ref | 9.183 | 13.975 |
| IMG_0005 | clipped_excl_% | 0.000 | 0.000 |
| IMG_0005 | crushed_% | 0.035 | 0.037 |
| IMG_0005 | median_luma | 0.587 | 0.717 |
| IMG_0005 | vert_med_deg | 0.040 | 0.050 |
| IMG_0005 | wall_dE_auto | 5.339 | 3.394 |
| IMG_0005 | wall_dE_gt | 4.139 | 3.225 |
| IMG_0005 | wall_L_gt | 52.465 | 69.372 |
| IMG_0005 | win_L | 71.315 | 67.127 |
| IMG_0005 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0005 | win_detail_ratio | 1.231 | 1.312 |
| IMG_0005 | halo_dL | 0.029 | 0.421 |
| IMG_0005 | clipped_nonlight_% | 0.099 | 0.074 |
| IMG_0005 | ssim | 0.874 | 0.898 |
| IMG_0005 | ms_ssim | 0.913 | 0.905 |
| IMG_0005 | grad_ssim | 0.891 | 0.896 |
| IMG_0005 | dE_ref | 10.393 | 10.290 |
| IMG_0008 | clipped_excl_% | 0.020 | 0.016 |
| IMG_0008 | crushed_% | 0.013 | 0.019 |
| IMG_0008 | median_luma | 0.565 | 0.725 |
| IMG_0008 | vert_med_deg | 0.163 | 0.107 |
| IMG_0008 | wall_dE_auto | 3.953 | 3.902 |
| IMG_0008 | wall_dE_gt | 6.455 | 2.949 |
| IMG_0008 | wall_L_gt | 64.592 | 79.040 |
| IMG_0008 | win_L | 70.436 | 65.389 |
| IMG_0008 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0008 | win_detail_ratio | 1.219 | 1.197 |
| IMG_0008 | halo_dL | -3.064 | -3.123 |
| IMG_0008 | clipped_nonlight_% | 0.011 | 0.014 |
| IMG_0008 | ssim | 0.933 | 0.876 |
| IMG_0008 | ms_ssim | 0.932 | 0.888 |
| IMG_0008 | grad_ssim | 0.904 | 0.879 |
| IMG_0008 | dE_ref | 10.656 | 16.553 |
| IMG_0015 | clipped_excl_% | 0.000 | 0.181 |
| IMG_0015 | crushed_% | 0.000 | 0.000 |
| IMG_0015 | median_luma | 0.543 | 0.713 |
| IMG_0015 | vert_med_deg | 0.020 | 0.101 |
| IMG_0015 | wall_dE_auto | 3.848 | 1.110 |
| IMG_0018 | clipped_excl_% | 2.152 | 2.314 |
| IMG_0018 | crushed_% | 0.013 | 0.004 |
| IMG_0018 | median_luma | 0.496 | 0.564 |
| IMG_0018 | vert_med_deg | 0.043 | 0.212 |
| IMG_0018 | wall_dE_auto | 7.079 | 7.907 |
| IMG_0018 | win_L | 73.528 | 66.898 |
| NOEXIF_0000 | clipped_excl_% | 0.130 | 0.160 |
| NOEXIF_0000 | crushed_% | 0.007 | 0.007 |
| NOEXIF_0000 | median_luma | 0.555 | 0.716 |
| NOEXIF_0000 | vert_med_deg | 0.068 | 0.053 |
| NOEXIF_0000 | wall_dE_auto | 4.331 | 3.792 |
| NOEXIF_0000 | win_L | 70.240 | 66.394 |

