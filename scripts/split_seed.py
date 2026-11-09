"""Copy the seed set into dataset/: every 5th image -> val, the rest -> train."""
import shutil
from pathlib import Path

SRC = Path(r'D:\praktikum_china\fruit_label')
DST = Path(__file__).resolve().parent / 'dataset'

images = sorted((SRC / 'images').glob('*.png'))
for i, image in enumerate(images, 1):
    split = 'val' if i % 5 == 0 else 'train'
    for kind, src in (('images', image), ('labels', SRC / 'labels_txt' / (image.stem + '.txt'))):
        folder = DST / kind / split
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, folder / src.name)

for split in ('train', 'val'):
    print(split, len(list((DST / 'images' / split).glob('*.png'))), 'images')