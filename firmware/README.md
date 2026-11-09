# firmware/

Local copies of the official Novation update images. **Everything in this
folder except this README is git-ignored.** The images are Focusrite/Novation
property: never commit, upload or redistribute them.

Populate it with:

```bash
scripts/fetch-firmware.sh          # Summit firmware + FPGA
scripts/fetch-firmware.sh --all    # also the Peak images, used for comparison
```

| File | Catalogue id | SHA-256 |
|---|---|---|
| `summit-firmware-2.2-build2121.syx` | 154 | `83b28931…d249396f` |
| `summit-fpga-2.1-build778.syx` | 144 | `57fed4df…ca9a0d3b` |
| `peak-firmware-2.2-build2108.syx` | 155 | `f9d50b42…1bc4de26e` |
| `peak-fpga-2.1-build469.syx` | 142 | `317d4866…ad18924d` |

The full hashes are pinned in `scripts/fetch-firmware.sh`; the script also
writes `SHA256SUMS` and a `catalog-snapshot.json` of the public catalogue.
