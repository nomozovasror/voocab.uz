"""Give every recording the extension its bytes actually deserve.

Cambridge 14 arrived as sixteen AAC/M4A files wearing a .mp3 extension. That
is not cosmetic: libsndfile refuses AAC outright, and CoreAudio's afinfo
trusts the extension and fails on the mismatch, so the files are unreadable by
both of the decoders this pipeline has. The backend has the same weakness from
the other direction -- app/services/storage.py maps extension -> MIME type, so
a mislabelled upload would be stored claiming to be audio/mpeg.

The fix is a rename, never a conversion: transcoding AAC to MP3 would lose
quality to buy nothing, since alignment resamples to 16 kHz mono regardless
and the backend serves M4A happily.

Dry run by default. Nothing is renamed unless the bytes disagree with the
name, and nothing is overwritten.
"""

import argparse
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
MATERIALS = REPO / "Materials"

#: Container signatures, checked against the file's own head. ISO-BMFF (M4A,
#: MP4) carries "ftyp" at offset 4; MP3 is either an ID3 tag or a frame sync.
def sniff(path: pathlib.Path) -> str | None:
    with open(path, "rb") as fh:
        head = fh.read(12)
    if len(head) < 12:
        return None
    if head[4:8] == b"ftyp":
        return ".m4a"
    if head[:3] == b"ID3" or (head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return ".mp3"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return ".wav"
    if head[:4] == b"OggS":
        return ".ogg"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="actually rename (default: dry run)")
    args = ap.parse_args()

    renames, unknown = [], []
    for path in sorted(MATERIALS.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".mp3", ".m4a", ".mp4", ".wav", ".ogg"}:
            continue
        actual = sniff(path)
        if actual is None:
            unknown.append(path)
        elif actual != path.suffix.lower():
            renames.append((path, path.with_suffix(actual)))

    for path in unknown:
        print(f"UNRECOGNISED  {path.relative_to(MATERIALS)}")

    if not renames:
        print("Every file's extension matches its bytes.")
        return 0

    print(f"{len(renames)} file(s) misnamed:\n")
    for src, dst in renames:
        print(f"  {src.suffix} -> {dst.suffix}  {src.relative_to(MATERIALS)}")

    if not args.apply:
        print("\nDry run. Re-run with --apply to rename.")
        return 0

    clashes = [dst for _, dst in renames if dst.exists()]
    if clashes:
        # Renaming onto an existing file would destroy it. Refuse the whole
        # batch rather than leave the folder half-converted.
        for dst in clashes:
            print(f"REFUSING: {dst.relative_to(MATERIALS)} already exists")
        return 1

    for src, dst in renames:
        src.rename(dst)
    print(f"\nRenamed {len(renames)} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
