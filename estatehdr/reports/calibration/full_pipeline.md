# Pełny pipeline przed / po kalibracji

Wejście: `data/synthetic/input`. Konfiguracja przed: `reports/calibration/config_before_full.yaml`, po: `config.yaml`. Ten sam kod, różnią się tylko parametry.

## Preset `neutral`: średnie (serie z GT dla metryk GT)

| metryka | przed | po | zmiana |
|---|---|---|---|
| przepalenia poza nieodzyskiwalnymi [%] | 1.146 | 1.157 | gorzej |
| zaczernienia [%] | 0.004 | 0.004 | = |
| mediana jasności | 0.570 | 0.687 |  |
| pionowość, mediana [°] | 0.076 | 0.064 | lepiej |
| neutralność jasnych powierzchni ΔE (auto) | 4.898 | 3.893 | lepiej |
| neutralność ścian ΔE (GT) | 5.567 | 3.087 | lepiej |
| jasność ścian L* (GT; cel SPEC: neutral 78-88, airy 84-92, premium 74-86) | 62.616 | 75.593 |  |
| jasność widoku okna L* (cel 55-80) | 74.951 | 71.499 |  |
| przepalenia okna odzyskiwalne [%] | 0.000 | 0.000 | = |
| detal okna / GT | 1.059 | 1.034 |  |
| halo przy oknie ΔL* (cel < 4) | -0.597 | -0.799 |  |
| przepalenia poza światłami (GT) [%] | 0.032 | 0.028 | lepiej |
| SSIM do idealnej edycji | 0.921 | 0.889 | gorzej |
| MS-SSIM do idealnej edycji | 0.931 | 0.904 | gorzej |
| gradient-SSIM (krawędzie) do idealnej edycji | 0.909 | 0.877 | gorzej |
| ΔE2000 do idealnej edycji | 10.195 | 13.917 | gorzej |

### Preset `neutral`: serie

| seria | metryka | przed | po |
|---|---|---|---|
| IMG_0000 | clipped_excl_% | 0.080 | 0.060 |
| IMG_0000 | crushed_% | 0.002 | 0.003 |
| IMG_0000 | median_luma | 0.582 | 0.718 |
| IMG_0000 | vert_med_deg | 0.113 | 0.135 |
| IMG_0000 | wall_dE_auto | 4.698 | 3.451 |
| IMG_0000 | wall_dE_gt | 6.055 | 3.146 |
| IMG_0000 | wall_L_gt | 67.164 | 79.066 |
| IMG_0000 | win_L | 75.984 | 71.919 |
| IMG_0000 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0000 | win_detail_ratio | 1.040 | 0.978 |
| IMG_0000 | halo_dL | 0.818 | 0.736 |
| IMG_0000 | clipped_nonlight_% | 0.016 | 0.014 |
| IMG_0000 | ssim | 0.927 | 0.885 |
| IMG_0000 | ms_ssim | 0.940 | 0.915 |
| IMG_0000 | grad_ssim | 0.918 | 0.894 |
| IMG_0000 | dE_ref | 9.734 | 14.287 |
| IMG_0005 | clipped_excl_% | 0.000 | 0.000 |
| IMG_0005 | crushed_% | 0.013 | 0.012 |
| IMG_0005 | median_luma | 0.606 | 0.712 |
| IMG_0005 | vert_med_deg | 0.047 | 0.040 |
| IMG_0005 | wall_dE_auto | 5.432 | 3.597 |
| IMG_0005 | wall_dE_gt | 4.179 | 3.249 |
| IMG_0005 | wall_L_gt | 54.892 | 69.526 |
| IMG_0005 | win_L | 74.297 | 71.945 |
| IMG_0005 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0005 | win_detail_ratio | 1.088 | 1.120 |
| IMG_0005 | halo_dL | 0.263 | -0.029 |
| IMG_0005 | clipped_nonlight_% | 0.066 | 0.060 |
| IMG_0005 | ssim | 0.901 | 0.910 |
| IMG_0005 | ms_ssim | 0.921 | 0.910 |
| IMG_0005 | grad_ssim | 0.907 | 0.880 |
| IMG_0005 | dE_ref | 9.607 | 10.397 |
| IMG_0008 | clipped_excl_% | 0.024 | 0.007 |
| IMG_0008 | crushed_% | 0.001 | 0.002 |
| IMG_0008 | median_luma | 0.583 | 0.716 |
| IMG_0008 | vert_med_deg | 0.192 | 0.120 |
| IMG_0008 | wall_dE_auto | 4.184 | 3.785 |
| IMG_0008 | wall_dE_gt | 6.465 | 2.867 |
| IMG_0008 | wall_L_gt | 65.793 | 78.187 |
| IMG_0008 | win_L | 74.573 | 70.632 |
| IMG_0008 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0008 | win_detail_ratio | 1.048 | 1.003 |
| IMG_0008 | halo_dL | -2.873 | -3.106 |
| IMG_0008 | clipped_nonlight_% | 0.013 | 0.009 |
| IMG_0008 | ssim | 0.935 | 0.871 |
| IMG_0008 | ms_ssim | 0.932 | 0.886 |
| IMG_0008 | grad_ssim | 0.902 | 0.858 |
| IMG_0008 | dE_ref | 11.243 | 17.067 |
| IMG_0015 | clipped_excl_% | 0.000 | 0.000 |
| IMG_0015 | crushed_% | 0.005 | 0.007 |
| IMG_0015 | median_luma | 0.560 | 0.706 |
| IMG_0015 | vert_med_deg | 0.022 | 0.024 |
| IMG_0015 | wall_dE_auto | 3.852 | 0.978 |
| IMG_0018 | clipped_excl_% | 6.647 | 6.754 |
| IMG_0018 | crushed_% | 0.001 | 0.001 |
| IMG_0018 | median_luma | 0.516 | 0.558 |
| IMG_0018 | vert_med_deg | 0.020 | 0.028 |
| IMG_0018 | wall_dE_auto | 6.834 | 7.741 |
| NOEXIF_0000 | clipped_excl_% | 0.129 | 0.118 |
| NOEXIF_0000 | crushed_% | 0.000 | 0.001 |
| NOEXIF_0000 | median_luma | 0.572 | 0.709 |
| NOEXIF_0000 | vert_med_deg | 0.062 | 0.035 |
| NOEXIF_0000 | wall_dE_auto | 4.386 | 3.807 |

## Preset `airy`: średnie (serie z GT dla metryk GT)

| metryka | przed | po | zmiana |
|---|---|---|---|
| przepalenia poza nieodzyskiwalnymi [%] | 1.144 | 1.145 | = |
| zaczernienia [%] | 0.001 | 0.001 | = |
| mediana jasności | 0.625 | 0.823 |  |
| pionowość, mediana [°] | 0.064 | 0.070 | gorzej |
| neutralność jasnych powierzchni ΔE (auto) | 4.742 | 3.814 | lepiej |
| neutralność ścian ΔE (GT) | 5.550 | 3.075 | lepiej |
| jasność ścian L* (GT; cel SPEC: neutral 78-88, airy 84-92, premium 74-86) | 67.714 | 87.084 |  |
| jasność widoku okna L* (cel 55-80) | 79.674 | 76.332 |  |
| przepalenia okna odzyskiwalne [%] | 0.000 | 0.000 | = |
| detal okna / GT | 0.936 | 1.106 |  |
| halo przy oknie ΔL* (cel < 4) | -0.856 | -0.376 |  |
| przepalenia poza światłami (GT) [%] | 0.023 | 0.026 | gorzej |
| SSIM do idealnej edycji | 0.927 | 0.848 | gorzej |
| MS-SSIM do idealnej edycji | 0.928 | 0.863 | gorzej |
| gradient-SSIM (krawędzie) do idealnej edycji | 0.900 | 0.852 | gorzej |
| ΔE2000 do idealnej edycji | 11.559 | 19.125 | gorzej |

### Preset `airy`: serie

| seria | metryka | przed | po |
|---|---|---|---|
| IMG_0000 | clipped_excl_% | 0.066 | 0.053 |
| IMG_0000 | crushed_% | 0.000 | 0.000 |
| IMG_0000 | median_luma | 0.636 | 0.851 |
| IMG_0000 | vert_med_deg | 0.075 | 0.083 |
| IMG_0000 | wall_dE_auto | 4.512 | 3.451 |
| IMG_0000 | wall_dE_gt | 5.960 | 3.046 |
| IMG_0000 | wall_L_gt | 71.716 | 89.131 |
| IMG_0000 | win_L | 80.574 | 76.740 |
| IMG_0000 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0000 | win_detail_ratio | 0.929 | 1.054 |
| IMG_0000 | halo_dL | 0.633 | 1.130 |
| IMG_0000 | clipped_nonlight_% | 0.010 | 0.011 |
| IMG_0000 | ssim | 0.937 | 0.844 |
| IMG_0000 | ms_ssim | 0.940 | 0.865 |
| IMG_0000 | grad_ssim | 0.913 | 0.862 |
| IMG_0000 | dE_ref | 11.775 | 19.402 |
| IMG_0005 | clipped_excl_% | 0.000 | 0.000 |
| IMG_0005 | crushed_% | 0.003 | 0.004 |
| IMG_0005 | median_luma | 0.658 | 0.849 |
| IMG_0005 | vert_med_deg | 0.053 | 0.055 |
| IMG_0005 | wall_dE_auto | 5.160 | 3.626 |
| IMG_0005 | wall_dE_gt | 4.193 | 3.221 |
| IMG_0005 | wall_L_gt | 60.751 | 83.317 |
| IMG_0005 | win_L | 79.083 | 76.568 |
| IMG_0005 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0005 | win_detail_ratio | 0.929 | 1.114 |
| IMG_0005 | halo_dL | -0.306 | 0.621 |
| IMG_0005 | clipped_nonlight_% | 0.049 | 0.048 |
| IMG_0005 | ssim | 0.927 | 0.903 |
| IMG_0005 | ms_ssim | 0.923 | 0.881 |
| IMG_0005 | grad_ssim | 0.896 | 0.850 |
| IMG_0005 | dE_ref | 8.948 | 14.003 |
| IMG_0008 | clipped_excl_% | 0.009 | 0.016 |
| IMG_0008 | crushed_% | 0.000 | 0.000 |
| IMG_0008 | median_luma | 0.638 | 0.849 |
| IMG_0008 | vert_med_deg | 0.136 | 0.140 |
| IMG_0008 | wall_dE_auto | 4.150 | 3.618 |
| IMG_0008 | wall_dE_gt | 6.496 | 2.958 |
| IMG_0008 | wall_L_gt | 70.673 | 88.803 |
| IMG_0008 | win_L | 79.365 | 75.686 |
| IMG_0008 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0008 | win_detail_ratio | 0.949 | 1.152 |
| IMG_0008 | halo_dL | -2.895 | -2.880 |
| IMG_0008 | clipped_nonlight_% | 0.011 | 0.019 |
| IMG_0008 | ssim | 0.917 | 0.798 |
| IMG_0008 | ms_ssim | 0.921 | 0.842 |
| IMG_0008 | grad_ssim | 0.891 | 0.842 |
| IMG_0008 | dE_ref | 13.955 | 23.971 |
| IMG_0015 | clipped_excl_% | 0.000 | 0.000 |
| IMG_0015 | crushed_% | 0.000 | 0.000 |
| IMG_0015 | median_luma | 0.616 | 0.842 |
| IMG_0015 | vert_med_deg | 0.025 | 0.054 |
| IMG_0015 | wall_dE_auto | 3.688 | 0.826 |
| IMG_0018 | clipped_excl_% | 6.672 | 6.799 |
| IMG_0018 | crushed_% | 0.000 | 0.001 |
| IMG_0018 | median_luma | 0.574 | 0.701 |
| IMG_0018 | vert_med_deg | 0.041 | 0.034 |
| IMG_0018 | wall_dE_auto | 6.561 | 7.491 |
| NOEXIF_0000 | clipped_excl_% | 0.116 | 0.000 |
| NOEXIF_0000 | crushed_% | 0.000 | 0.000 |
| NOEXIF_0000 | median_luma | 0.627 | 0.847 |
| NOEXIF_0000 | vert_med_deg | 0.055 | 0.056 |
| NOEXIF_0000 | wall_dE_auto | 4.381 | 3.871 |

## Preset `premium`: średnie (serie z GT dla metryk GT)

| metryka | przed | po | zmiana |
|---|---|---|---|
| przepalenia poza nieodzyskiwalnymi [%] | 1.154 | 1.171 | gorzej |
| zaczernienia [%] | 0.025 | 0.023 | lepiej |
| mediana jasności | 0.552 | 0.693 |  |
| pionowość, mediana [°] | 0.071 | 0.088 | gorzej |
| neutralność jasnych powierzchni ΔE (auto) | 4.893 | 3.905 | lepiej |
| neutralność ścian ΔE (GT) | 5.602 | 3.165 | lepiej |
| jasność ścian L* (GT; cel SPEC: neutral 78-88, airy 84-92, premium 74-86) | 61.098 | 76.079 |  |
| jasność widoku okna L* (cel 55-80) | 71.270 | 66.257 |  |
| przepalenia okna odzyskiwalne [%] | 0.000 | 0.000 | = |
| detal okna / GT | 1.219 | 1.209 |  |
| halo przy oknie ΔL* (cel < 4) | -0.748 | -0.446 |  |
| przepalenia poza światłami (GT) [%] | 0.044 | 0.037 | lepiej |
| SSIM do idealnej edycji | 0.906 | 0.881 | gorzej |
| MS-SSIM do idealnej edycji | 0.926 | 0.903 | gorzej |
| gradient-SSIM (krawędzie) do idealnej edycji | 0.901 | 0.890 | gorzej |
| ΔE2000 do idealnej edycji | 10.074 | 13.690 | gorzej |

### Preset `premium`: serie

| seria | metryka | przed | po |
|---|---|---|---|
| IMG_0000 | clipped_excl_% | 0.090 | 0.081 |
| IMG_0000 | crushed_% | 0.016 | 0.019 |
| IMG_0000 | median_luma | 0.564 | 0.725 |
| IMG_0000 | vert_med_deg | 0.093 | 0.133 |
| IMG_0000 | wall_dE_auto | 4.824 | 3.470 |
| IMG_0000 | wall_dE_gt | 6.162 | 3.279 |
| IMG_0000 | wall_L_gt | 65.872 | 79.579 |
| IMG_0000 | win_L | 72.177 | 66.670 |
| IMG_0000 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0000 | win_detail_ratio | 1.207 | 1.139 |
| IMG_0000 | halo_dL | 0.746 | 1.227 |
| IMG_0000 | clipped_nonlight_% | 0.018 | 0.013 |
| IMG_0000 | ssim | 0.913 | 0.864 |
| IMG_0000 | ms_ssim | 0.941 | 0.907 |
| IMG_0000 | grad_ssim | 0.913 | 0.893 |
| IMG_0000 | dE_ref | 9.118 | 14.134 |
| IMG_0005 | clipped_excl_% | 0.000 | 0.000 |
| IMG_0005 | crushed_% | 0.046 | 0.056 |
| IMG_0005 | median_luma | 0.587 | 0.717 |
| IMG_0005 | vert_med_deg | 0.041 | 0.042 |
| IMG_0005 | wall_dE_auto | 5.342 | 3.385 |
| IMG_0005 | wall_dE_gt | 4.185 | 3.281 |
| IMG_0005 | wall_L_gt | 52.504 | 69.408 |
| IMG_0005 | win_L | 71.216 | 66.811 |
| IMG_0005 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0005 | win_detail_ratio | 1.233 | 1.300 |
| IMG_0005 | halo_dL | 0.077 | 0.464 |
| IMG_0005 | clipped_nonlight_% | 0.104 | 0.087 |
| IMG_0005 | ssim | 0.881 | 0.899 |
| IMG_0005 | ms_ssim | 0.917 | 0.907 |
| IMG_0005 | grad_ssim | 0.898 | 0.894 |
| IMG_0005 | dE_ref | 10.290 | 10.270 |
| IMG_0008 | clipped_excl_% | 0.023 | 0.007 |
| IMG_0008 | crushed_% | 0.012 | 0.019 |
| IMG_0008 | median_luma | 0.565 | 0.728 |
| IMG_0008 | vert_med_deg | 0.170 | 0.228 |
| IMG_0008 | wall_dE_auto | 3.942 | 3.883 |
| IMG_0008 | wall_dE_gt | 6.458 | 2.933 |
| IMG_0008 | wall_L_gt | 64.918 | 79.250 |
| IMG_0008 | win_L | 70.418 | 65.289 |
| IMG_0008 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0008 | win_detail_ratio | 1.216 | 1.188 |
| IMG_0008 | halo_dL | -3.067 | -3.029 |
| IMG_0008 | clipped_nonlight_% | 0.010 | 0.012 |
| IMG_0008 | ssim | 0.924 | 0.879 |
| IMG_0008 | ms_ssim | 0.921 | 0.896 |
| IMG_0008 | grad_ssim | 0.892 | 0.884 |
| IMG_0008 | dE_ref | 10.813 | 16.667 |
| IMG_0015 | clipped_excl_% | 0.000 | 0.000 |
| IMG_0015 | crushed_% | 0.058 | 0.026 |
| IMG_0015 | median_luma | 0.543 | 0.714 |
| IMG_0015 | vert_med_deg | 0.018 | 0.021 |
| IMG_0015 | wall_dE_auto | 3.974 | 0.995 |
| IMG_0018 | clipped_excl_% | 6.683 | 6.782 |
| IMG_0018 | crushed_% | 0.009 | 0.008 |
| IMG_0018 | median_luma | 0.496 | 0.561 |
| IMG_0018 | vert_med_deg | 0.042 | 0.042 |
| IMG_0018 | wall_dE_auto | 6.965 | 7.913 |
| NOEXIF_0000 | clipped_excl_% | 0.129 | 0.157 |
| NOEXIF_0000 | crushed_% | 0.007 | 0.008 |
| NOEXIF_0000 | median_luma | 0.554 | 0.715 |
| NOEXIF_0000 | vert_med_deg | 0.061 | 0.064 |
| NOEXIF_0000 | wall_dE_auto | 4.313 | 3.785 |

