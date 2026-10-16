# Kalibracja (cele z opisu + GT syntetyczne), preset `airy`

Funkcja celu: 3.5573 -> 2.7935 (6 zaakceptowanych kroków, 914 s).

| parametr | przed | po |
|---|---|---|
| tonemap.target_key | 0.76 | 0.85 |
| tonemap.compress_shadows | 0.54 | 0.78 |
| tonemap.compress_highlights | 0.59 | 0.59 |
| windows.exterior_target | 0.655 | 0.655 |

| seria | metryka | przed | po |
|---|---|---|---|
| IMG_0000 | wall_dE_gt | 2.987 | 3.029 |
| IMG_0000 | wall_L_gt | 82.867 | 89.165 |
| IMG_0000 | win_L | 77.737 | 76.758 |
| IMG_0000 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0000 | clipped_nonlight_% | 0.001 | 0.000 |
| IMG_0000 | halo_dL | -1.196 | -0.949 |
| IMG_0000 | ssim | 0.879 | 0.845 |
| IMG_0000 | dE_ref | 16.287 | 19.232 |
| IMG_0005 | wall_dE_gt | 3.195 | 3.164 |
| IMG_0005 | wall_L_gt | 74.759 | 83.471 |
| IMG_0005 | win_L | 78.034 | 76.649 |
| IMG_0005 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0005 | clipped_nonlight_% | 0.023 | 0.012 |
| IMG_0005 | halo_dL | -0.732 | 0.118 |
| IMG_0005 | ssim | 0.914 | 0.894 |
| IMG_0005 | dE_ref | 11.773 | 13.969 |
| IMG_0008 | wall_dE_gt | 2.728 | 2.887 |
| IMG_0008 | wall_L_gt | 82.093 | 88.873 |
| IMG_0008 | win_L | 76.589 | 75.625 |
| IMG_0008 | win_clip_recov_% | 0.000 | 0.000 |
| IMG_0008 | clipped_nonlight_% | 0.000 | 0.000 |
| IMG_0008 | halo_dL | -3.185 | -2.939 |
| IMG_0008 | ssim | 0.831 | 0.794 |
| IMG_0008 | dE_ref | 20.211 | 23.890 |
