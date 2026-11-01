"""OCR the tw person/evidence name sprites -> data/names.json"""
import json
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'guide'))
import ocr  # noqa: E402

TXT = os.path.join(HERE, '..', 'data', 'img', 'pc', 'tw', 'game', 'note', 'text')

PLACES = {1: '私立櫻羽女學院', 2: '月世界', 3: '井之頭公園', 4: '朽木病理學研究所', 5: '高城醫院',
          6: '新宿站前', 7: '時坂偵探事務所', 8: '上野站', 9: '東京都美術館', 10: '高城偵探事務所'}


def cell_text(im, x, y, w, h):
    c = im.crop((x, y, x + w, y + h))
    bg = Image.new('RGBA', c.size, (255, 255, 255, 255))
    bg.alpha_composite(c)
    big = Image.new('RGB', (w + 40, h + 40), (255, 255, 255))
    big.paste(bg.convert('RGB'), (20, 20))
    lines = ocr.recognize(big, scale=3)
    return ''.join(t for t, _ in lines).strip()


def main():
    out = {'person': {}, 'evidence': {}, 'places': PLACES}
    im = Image.open(os.path.join(TXT, 'note_name1_g.png')).convert('RGBA')
    for i in range(im.height // 22):
        out['person'][i] = cell_text(im, 0, i * 22, 209, 22)
    im = Image.open(os.path.join(TXT, 'note_proof1_g.png')).convert('RGBA')
    for col in range(im.width // 209):
        for row in range(20):
            t = cell_text(im, col * 209, row * 22, 209, 22)
            if t:
                out['evidence'][col * 20 + row] = t
    with open(os.path.join(HERE, '..', 'data', 'names.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(out['person'])
    print(out['evidence'])


if __name__ == '__main__':
    main()
