"""Adapt the visualbruno Hunyuan3D 2.1 wrapper to current Diffusers APIs."""
import argparse
import pathlib


def patched(source):
    changes = (
        ('            use_fast=False\n',
         '            use_fast=False,\n            trust_remote_code=True,\n'),
        ('        pipeline.enable_model_cpu_offload()\n',
         "        # Direct VAE calls in this pipeline require consistent GPU placement.\n"),
        ('        self.pipeline.enable_vae_slicing()\n',
         '        self.pipeline.vae.enable_slicing()\n'),
        ('        self.pipeline.enable_vae_tiling()\n',
         '        self.pipeline.vae.enable_tiling()\n'),
    )
    for old, new in changes:
        if new in source:
            continue
        if source.count(old) != 1:
            raise ValueError('Unsupported Hunyuan wrapper version; source was not changed.')
        source = source.replace(old, new)
    compile(source, 'multiview_utils.py', 'exec')
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comfy-dir', required=True, type=pathlib.Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    target = args.comfy_dir.resolve() / 'custom_nodes/ComfyUI-Hunyuan3d-2-1/hy3dpaint/utils/multiview_utils.py'
    source = target.read_text(encoding='utf-8')
    result = patched(source)
    if result == source:
        print('Hunyuan compatibility settings are already applied.')
    elif args.check:
        raise SystemExit('Compatibility update is required. No files changed.')
    else:
        temporary = target.with_suffix('.compat.tmp')
        temporary.write_text(result, encoding='utf-8')
        temporary.replace(target)
        print('Updated. Restart ComfyUI when its queue is idle.')


if __name__ == '__main__':
    main()
