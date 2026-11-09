"""Copy S3-S6 into one flat folder, prefixing each image with its session."""
import shutil
from pathlib import Path

RAW = Path(r'D:\praktikum_china\fruit_raw')
OUT = Path(r'D:\praktikum_china\fruit_label\batch2_images')

OUT.mkdir(parents=True)  # stops if the folder already exists, so nothing is overwritten
for session in ('S3', 'S4', 'S5', 'S6'):
    for image in sorted((RAW / session).glob('*/images/*.png')):
        shutil.copy2(image, OUT / f'{session}_{image.name}')
print(len(list(OUT.glob('*.png'))), 'images')