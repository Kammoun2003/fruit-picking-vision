"""Build dataset_fruit01: whole sessions per split (S4 = val, all others = train)."""
import shutil
from pathlib import Path

LABEL = Path(r'D:\praktikum_china\fruit_label')
SOURCES = [(LABEL / 'images', LABEL / 'labels_txt'),                              # S1, S2
           (LABEL / 'batch2_prelabel' / 'review' / 'images', LABEL / 'batch2_labels_txt')]  # S3-S6
VAL_SESSIONS = {'S4'}
DST = Path(__file__).resolve().parent / 'dataset_fruit01'

DST.mkdir()  # stops if it already exists, so nothing is overwritten
for image_dir, label_dir in SOURCES:
    for image in sorted(image_dir.glob('*.png')):
        split = 'val' if image.name.split('_')[0] in VAL_SESSIONS else 'train'
        for kind, src in (('images', image), ('labels', label_dir / (image.stem + '.txt'))):
            folder = DST / kind / split
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, folder / src.name)

names = (Path(__file__).resolve().parent / 'classes.txt').read_text(encoding='utf-8').split()
(DST / 'data.yaml').write_text('path: .\ntrain: images/train\nval: images/val\nnames:\n'
                               + ''.join(f'- {n}\n' for n in names), encoding='utf-8')
for split in ('train', 'val'):
    print(split, len(list((DST / 'images' / split).glob('*.png'))), 'images')