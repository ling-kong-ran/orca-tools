"""Update VRM license metadata atomically; preserve geometry and binary chunks."""
import json, os, pathlib, struct, uuid

PRESETS = ('commercial_modifiable', 'restrictive')


def license_metadata(document, preset):
    if preset not in PRESETS: raise ValueError('Unsupported VRM license preset.')
    extensions = document.get('extensions', {})
    if ('VRMC_vrm' in extensions) == ('VRM' in extensions):
        raise ValueError('Select a VRM 1.0 or VRM 0.x model with unambiguous metadata.')
    commercial = preset == 'commercial_modifiable'
    if 'VRMC_vrm' in extensions:
        meta = extensions['VRMC_vrm'].get('meta')
        if not isinstance(meta, dict): raise ValueError('VRM metadata is missing.')
        meta.update(avatarPermission='everyone' if commercial else 'onlyAuthor',
                    commercialUsage='corporation' if commercial else 'personalNonProfit',
                    modification='allowModificationRedistribution' if commercial else 'prohibited',
                    allowRedistribution=commercial, creditNotation='required')
        version = '1.0'
    else:
        meta = extensions['VRM'].get('meta')
        if not isinstance(meta, dict): raise ValueError('VRM metadata is missing.')
        meta.update(allowedUserName='Everyone' if commercial else 'OnlyAuthor',
                    commercialUssageName='Allow' if commercial else 'Disallow',
                    licenseName='CC_BY' if commercial else 'Redistribution_Prohibited',
                    otherLicenseUrl='')
        version = '0.0'
    return {'format': version, 'license_preset': preset, 'license': {
        'commercial_use': commercial, 'modification': commercial,
        'redistribution': commercial, 'credit_required': True}}


def set_license(file, preset='commercial_modifiable'):
    file = pathlib.Path(file)
    temporary = file.with_name('.vrm-license-'+uuid.uuid4().hex+'.tmp')
    try:
        with file.open('rb') as source:
            size = os.fstat(source.fileno()).st_size
            header = source.read(20)
            if len(header) != 20: raise ValueError('VRM container is incomplete.')
            magic, version, total, length, kind = struct.unpack('<4sIIII', header)
            if magic != b'glTF' or version != 2 or total != size or kind != 0x4E4F534A or not 0 < length <= 16*1024**2 or length % 4 or 20+length > total:
                raise ValueError('VRM container header is invalid.')
            document = json.loads(source.read(length))
            receipt = license_metadata(document, preset)
            encoded = json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            encoded += b' ' * (-len(encoded) % 4)
            final_size = total-length+len(encoded)
            if final_size > 0xFFFFFFFF: raise ValueError('VRM container exceeds the GLB size limit.')
            with temporary.open('xb') as output:
                output.write(struct.pack('<4sIIII', b'glTF', 2, final_size, len(encoded), kind)); output.write(encoded)
                # Validate and stream every other chunk, without decoding textures
                # or loading a potentially large model into memory.
                remaining = total-20-length
                while remaining:
                    chunk = source.read(8)
                    if len(chunk) != 8: raise ValueError('VRM chunk is incomplete.')
                    chunk_size, chunk_kind = struct.unpack('<II', chunk)
                    if chunk_size % 4 or chunk_size+8 > remaining or chunk_kind == 0x4E4F534A:
                        raise ValueError('VRM chunk is invalid.')
                    output.write(chunk); left = chunk_size
                    while left:
                        data = source.read(min(left, 1024*1024))
                        if not data: raise ValueError('VRM binary chunk is incomplete.')
                        output.write(data); left -= len(data)
                    remaining -= chunk_size+8
                output.flush(); os.fsync(output.fileno())
        temporary.replace(file)
        return {**receipt, 'bytes': file.stat().st_size}
    finally:
        temporary.unlink(missing_ok=True)
