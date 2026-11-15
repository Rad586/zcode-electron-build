"""Filter locale bundles in Chromium's little-endian ICU data package."""
from pathlib import Path
import struct
import sys
import re

CATEGORIES = {'coll', 'curr', 'lang', 'rbnf', 'region', 'unit', 'zone'}


def keep_locale(name):
    return name in {'root', 'pool', 'res_index'} or name.split('_')[0] in {'en', 'zh'}


def entries(data):
    if data[2:4] != b'\xda\x27' or data[8] != 0 or data[12:16] != b'CmnD':
        raise ValueError('Expected a little-endian ICU common package')
    header = struct.unpack_from('<H', data)[0]
    count = struct.unpack_from('<I', data, header)[0]
    rows = []
    for index in range(count):
        name, offset = struct.unpack_from('<II', data, header + 4 + 8 * index)
        name = data[header + name:data.index(0, header + name)].decode('ascii')
        rows.append((name, offset))
    ends = dict(zip(sorted({offset for _, offset in rows}),
                    sorted({offset for _, offset in rows})[1:] + [len(data) - header]))
    return data[:header], [(name, data[header + offset:header + ends[offset]])
                           for name, offset in rows]


def filter_index(data):
    data = bytearray(data)
    header = struct.unpack_from('<H', data)[0]
    if data[12:16] != b'ResB' or data[16] != 2:
        raise ValueError('Expected ICU resource format 2')
    root, length, keys_top = struct.unpack_from('<III', data, header)
    if root >> 28 != 2 or length != 7:
        raise ValueError('Unexpected ICU locale index root')
    table = header + (root & 0xfffffff) * 4
    count = struct.unpack_from('<H', data, table)[0]
    keys = struct.unpack_from('<' + 'H' * count, data, table + 2)
    values = (table + 2 + count * 2 + 3) & ~3
    for index, key in enumerate(keys):
        name = data[header + key:data.index(0, header + key)].decode('ascii')
        if name not in {'InstalledLocales', 'AliasLocales'}:
            continue
        value = struct.unpack_from('<I', data, values + index * 4)[0]
        if value == 0x20000000:
            continue
        if value >> 28 != 5:
            raise ValueError('Expected a table16 locale index')
        offset = header + keys_top * 4 + (value & 0xfffffff) * 2
        size = struct.unpack_from('<H', data, offset)[0]
        key_offsets = struct.unpack_from('<' + 'H' * size, data, offset + 2)
        strings = struct.unpack_from('<' + 'H' * size, data, offset + 2 + size * 2)
        selected = [(key, string) for key, string in zip(key_offsets, strings)
                    if keep_locale(data[header + key:data.index(0, header + key)].decode('ascii'))]
        packed = [len(selected), *(key for key, _ in selected),
                  *(string for _, string in selected)]
        struct.pack_into('<' + 'H' * len(packed), data, offset, *packed)
    return bytes(data)


def trim(data):
    header, records = entries(data)
    selected = []
    for name, payload in records:
        parts = name.split('/')[1:]
        locale_bundle = len(parts) == 1 or (len(parts) == 2 and parts[0] in CATEGORIES)
        if locale_bundle and parts[-1].endswith('.res'):
            stem = parts[-1][:-4]
            is_locale = re.fullmatch(r'[a-z]{2,3}(?:_[A-Za-z0-9]+)*', stem)
            if (len(parts) == 2 or is_locale) and not keep_locale(stem):
                continue
            if stem == 'res_index':
                payload = filter_index(payload)
        selected.append((name, payload))
    names = bytearray()
    table_end = 4 + 8 * len(selected)
    name_offsets = []
    for name, _ in selected:
        name_offsets.append(table_end + len(names))
        names.extend(name.encode('ascii') + b'\0')
    result = bytearray(header)
    result.extend(struct.pack('<I', len(selected)))
    table = len(result)
    result.extend(b'\0' * (8 * len(selected)))
    result.extend(names)
    for index, ((_, payload), name) in enumerate(zip(selected, name_offsets)):
        result.extend(b'\xaa' * ((-len(result)) % 16))
        offset = len(result) - len(header)
        struct.pack_into('<II', result, table + 8 * index, name, offset)
        result.extend(payload)
    result.extend(b'\xaa' * ((-len(result)) % 16))
    return bytes(result)


def main():
    source = Path(sys.argv[1])
    result = trim(source.read_bytes())
    source.write_bytes(result)
    print('Filtered ICU locale bundles to English and Chinese.')


if __name__ == '__main__':
    main()
