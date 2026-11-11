# Provenance and publication boundary

## Research records

The [research index](../README.md) links all three original artifacts and their threads. These preserve the completed investigations; Amp access may be required. None is a Rex application-source repository.

The Lua and libghostty reports were published directly as artifacts. Their text is preserved in this repository with minor Markdown normalization. The source/API report started from the original bundle's README, updated here with the final artifact's archive/validation details and repository-appropriate navigation. Original version identities and verification limits are retained.

## Original source/API capture

| Field | Value |
| --- | --- |
| Archive | `rex-source-api-map-preview15.tar.gz` |
| Size | 886,766 bytes (about 866 KiB) |
| SHA-256 | `2868bc4e5d5bc3da0876cf7d0f7a2b5d7a34c39adac6f77a4c90a6333e8ee112` |
| Root on extraction | `rex-index/` |
| Original research thread | [Source/API research](https://ampcode.com/threads/T-01a1cc3b-fbc1-7025-8943-110631606e78) |
| Explorer | [Original interactive artifact](https://ampcode.com/artifacts/visuals/rex-api-explorer-7d4684ca-6429-415f-a72e-bc1d98bba436), also `rex-index/index.html` in the archive |
| Runtime inspected | Linux amd64 `0.1.0-preview.15`, commit `99caa8e07107e0ec57eeaa868f9f589ccd8bd7cb`, built `2026-11-10T21:59:52Z`, API revision 13 |
| Website snapshot | `2026-11-11T20:11:44Z`; rolling documentation, not a published Git revision |

The verified original archive was transferred from its research thread and retained privately outside the teerex repository. It is **not** committed, linked as a public release asset, or covered by a teerex license. It contains vendor materials whose redistribution terms were not established. Its hash identifies it but does not grant permission to share it. The original thread is the access route, not an assumed public download endpoint.

## Included metadata

- [source-capture.json](source-capture.json): original acquisition manifest, with URLs, sizes, hashes, runtime identity, commands used, and capture limitations. `input_files` paths refer to the **original capture**; they are not files shipped in teerex.
- [SHA256SUMS.capture](SHA256SUMS.capture): original 83-file integrity list, for verification **inside an extracted original archive**, not at the teerex root. Do not rename or interpret it as checksums for this repository.
- [../api/catalog.json](../api/catalog.json): all 524 original entry names/categories and source locations, with descriptions, required-argument lists, examples, and schema bodies omitted. This derivative is intentionally not byte-identical to the original catalogue; it is not covered by that catalogue's archived checksum.

The original capture includes `API_MAP.md`, the full catalogue, generator `rebuild.py`, explorer template/HTML, website snapshots, packaging, runtime schemas, and evidence. Its index resolves references to available files and explicitly labels unretrieved source references. A mentioned private-tree path is not acquired source.

## Excluded from GitHub content

- The Rex executable and executable archive (the original researcher removed them after discovery).
- Compiled terminfo (`packaging/rex/xterm-rex.bin`) and compressed vendor packaging captures.
- Vendor installer/packaging source, captured website pages, bulk documentation exports, release-generated schema/guide bodies, and third-party evidence responses.
- The original explorer/API map's embedded vendor descriptions/excerpts. They remain preserved with the private original capture and linked artifact, rather than being silently relicensed.
- Personal installed-version observations, terminal screens, connection settings, or credentials.

No redistribution permission for the above is assumed, even for publicly readable downloads. No blanket license has been chosen for original teerex work either. See [RIGHTS.md](../../RIGHTS.md).

## Integrity and reproduction

If you already have authorized access to the original archive, first compare its SHA-256 with the value above. From its extracted `rex-index/` directory, `sha256sum -c SHA256SUMS` checks the 83 original files. On macOS, `shasum -a 256 -c SHA256SUMS` is the corresponding tool. `python3 rebuild.py` rebuilds the original index from that capture's inputs, offline. These commands are not installers and are not expected to run in teerex, which deliberately does not contain those inputs.

The original research validated 524 references/JSON pointers, deterministic generation, a 74-name website/runtime control-method match, and the explorer's search/filter/pagination/detail/empty/mobile states. During teerex preparation, the archive hash and all 83 file checksums were independently verified again, and the metadata-only inventory was compared with the original. These checks validate preservation/indexing, **not every advertised Rex method**, Joshua's machine, or Rivet integration.

For another release, make a new dated capture and retain its own provenance. Do not overwrite this snapshot or label rolling docs as the implementation source. Discovery involving a real machine/server must be scoped and authorized separately.
