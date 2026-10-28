import json,pathlib,struct,tempfile,unittest
from native_vrm import set_license


def container(version='1.0', binary=b'geometryTEXTURES'):
    extension='VRMC_vrm' if version=='1.0' else 'VRM'
    document={'asset':{'version':'2.0'},'extensions':{extension:{'meta':{'name':'Keep title','authors':['Artist'],'thumbnailImage':3}}}}
    encoded=json.dumps(document).encode();encoded+=b' '*(-len(encoded)%4)
    binary+=b'\0'*(-len(binary)%4)
    return struct.pack('<4sIIII',b'glTF',2,28+len(encoded)+len(binary),len(encoded),0x4e4f534a)+encoded+struct.pack('<II',len(binary),0x004e4942)+binary


def read_document(data):
    size=struct.unpack_from('<I',data,12)[0]
    return json.loads(data[20:20+size]),data[20+size:]


class LicenseTests(unittest.TestCase):
    def test_both_versions_default_to_commercial_modifiable_and_keep_binary_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            file=pathlib.Path(folder)/'avatar.vrm'
            for version in ('1.0','0.0'):
                original=container(version);file.write_bytes(original)
                result=set_license(file);document,tail=read_document(file.read_bytes())
                self.assertEqual(tail,read_document(original)[1]);self.assertEqual(result['format'],version)
                self.assertTrue(result['license']['commercial_use']);self.assertTrue(result['license']['modification'])
                self.assertTrue(result['license']['redistribution']);self.assertTrue(result['license']['credit_required'])
                meta=document['extensions']['VRMC_vrm' if version=='1.0' else 'VRM']['meta']
                self.assertEqual(meta['name'],'Keep title');self.assertEqual(meta['authors'],['Artist'])
                if version=='1.0':
                    self.assertEqual(meta['commercialUsage'],'corporation');self.assertEqual(meta['modification'],'allowModificationRedistribution')
                else:self.assertEqual(meta['licenseName'],'CC_BY');self.assertEqual(meta['commercialUssageName'],'Allow')
                self.assertEqual(struct.unpack_from('<I',file.read_bytes(),8)[0],file.stat().st_size)
                restricted=set_license(file,'restrictive');self.assertFalse(restricted['license']['commercial_use'])

    def test_corrupt_chunks_and_unknown_license_leave_original_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            file=pathlib.Path(folder)/'avatar.vrm'
            for invalid in (b'bad',container()[:-1],container()+b'junk'):
                file.write_bytes(invalid)
                with self.assertRaises(ValueError):set_license(file)
                self.assertEqual(file.read_bytes(),invalid)
                self.assertFalse(list(file.parent.glob('*.tmp')))
            file.write_bytes(container())
            with self.assertRaises(ValueError):set_license(file,'unknown')
            self.assertEqual(file.read_bytes(),container())


if __name__=='__main__':unittest.main()
