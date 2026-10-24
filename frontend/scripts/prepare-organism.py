"""Extract a permanent total-wallet core and one reusable active-wallet orb.
Preserve the original Figma dot paths, never partition the core into wallets.
Run from frontend with: python3 scripts/prepare-organism.py
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

root = Path(__file__).resolve().parents[1]
svg = ET.parse(root / 'public/assets/organism-reference.svg').getroot()
core = []
satellite = []
for element in svg.iter():
    if not element.tag.endswith('path'):
        continue
    for path in re.findall(r'M[^M]+', element.attrib['d']):
        numbers = [float(n) for n in re.findall(r'-?\d+(?:\.\d+)?', path)]
        xs, ys = numbers[::2], numbers[1::2]
        x, y = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        if element.attrib['id'] == 'blue':
            satellite.append(path)
        elif x > 410 and y < 225:
            continue
        elif x < 130 and y < 300:
            continue
        else:
            core.append(path)
paths = f'<path id="total-wallet" d="{"".join(core)}"/><path id="active-wallet" d="{"".join(satellite)}"/>'
(root / 'public/assets/wallet-clusters.svg').write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" width="727" height="727" viewBox="0 0 727 727"><defs>'
    + paths + '</defs></svg>')
print(f'Prepared permanent core ({len(core)} dots) and reusable satellite ({len(satellite)} dots).')
