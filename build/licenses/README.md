# Bundled runtime notices

These files contain third-party notices and original license documents. They are
excluded from this project's PolyForm Noncommercial license. Preserve each
upstream document and its applicable terms.

## Python 3.12.10

`Python-3.12.10-LICENSE.txt` is copied byte-for-byte from `LICENSE.txt` in the
official Windows x64 embeddable archive. The same original license remains in
the packaged Python runtime directory.

This project changes runtime configuration (`python312._pth` and `pip.ini`) and
installs application dependencies. It does not modify the Python interpreter
binaries. The Python document retains the PSF and other notices included by
the upstream distribution; Python is not subject to this project's
noncommercial restriction.

Official source and release information:
https://www.python.org/downloads/release/python-31210/

## LZMA SDK and reduced 7-Zip tools

`LZMA-SDK-25.01.txt` and `LZMA-SDK-25.01-installer.txt` are original documents
from the official LZMA SDK 25.01 archive. The installer document retains its
upstream internal heading, "7-Zip for installers 9.38"; it is not rewritten
to claim a different document version.

The SDK documentation places the original SDK code and compiled binaries in
the public domain and explicitly includes the reduced `7zr.exe` and installer
SFX modules. This build uses `bin/7zSD.sfx` from that 25.01 archive. The separately
downloaded `7zr.exe` identifies itself in its PE version resource as version
26.04, "7-Zip Reduced Standalone Console", with the copyright field
"Igor Pavlov : Public domain". The binary hashes are recorded in
`SOURCE_MANIFEST.json`.

These observations concern these reduced tools and the SDK installer module;
they do not assert that every 7-Zip product or binary has the same license.
The public-domain SDK statement does not require distributing corresponding
source. The upstream SDK, including source, is available at:
https://www.7-zip.org/sdk.html
https://www.7-zip.org/a/lzma2501.7z

## NapCat v4.18.41

`NapCat-v4.18.41-LICENSE.txt` is the exact-tag repository license. The upstream
copyright notice is "Copyright © 2024 Mlikiowa". Source and release:
https://github.com/NapNeko/NapCatQQ/tree/v4.18.41
https://github.com/NapNeko/NapCatQQ/releases/tag/v4.18.41

The application bundles the unmodified official Windows Node release. Its
Limited Redistribution License applies separately. Adding this notice does
not change the licenses of its included Node modules or other runtime files;
their existing notices must also remain intact.

## Scope of this collection

`Node-v22.11.0-LICENSE.txt` is the original Node.js license file for the version
reported by the `node.exe` in the official NapCat package. It includes the
upstream Node.js dependency notices. Its exact source URL and hash are recorded
in `SOURCE_MANIFEST.json`; the executable itself is not modified.

`SOURCE_MANIFEST.json` records extraction provenance and file hashes. Local
hashes identify particular files; they are not a substitute for publisher
signature verification. This collection is not an exhaustive license review
of every dependency or asset downloaded during plugin prewarming.

AstrBot's own license remains with its source tree. Installed Python packages
must retain their `.dist-info` metadata and licenses. NapCat's nested
`node_modules` licenses must remain with their packages. A build inventory
should record the versions actually included in a particular installer.
