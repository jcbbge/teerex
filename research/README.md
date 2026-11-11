# Research index

Checked **11 November 2026**. These are completed investigations, not completed extensions. Read each finding's verification limits before treating a documented capability as observed behavior.

| Investigation | Read locally | Original record |
| --- | --- | --- |
| Lua automation and a terminal-first Rivet workspace | [Lua findings](lua.md) | [Artifact, revision 2](https://ampcode.com/artifacts/rex-lua-capabilities-4e3a48f6-dbe2-41f1-acd7-2a8995dcf1b2); [research thread](https://ampcode.com/threads/T-01a1cc3b-ed75-76d2-979b-4b7587dc59de) |
| libghostty's entry and ownership boundary | [libghostty findings](libghostty.md) | [Artifact, revision 1](https://ampcode.com/artifacts/rex-libghostty-entry-87eb8f83-5e98-4256-a675-7d23a1c8cf57); [research thread](https://ampcode.com/threads/T-01a1cc3b-f593-71b9-910e-5c10555d0ed2) |
| Official sources, protocol, API map, and gaps | [Source/API findings](source-api.md) | [Artifact, revision 2](https://ampcode.com/artifacts/rex-source-findings-07a0ace3-a37f-470a-83e6-4a80e73ecabc); [research thread](https://ampcode.com/threads/T-01a1cc3b-fbc1-7025-8943-110631606e78) |
| Searchable explorer | [Inventory metadata](api/catalog.json) | [Original explorer](https://ampcode.com/artifacts/visuals/rex-api-explorer-7d4684ca-6429-415f-a72e-bc1d98bba436), also in the privately retained capture |

The original Amp records may require permission to open; they are not public GitHub assets. The local findings remain readable without Amp access. Lua/libghostty text is preserved with minor Markdown normalization; the source report has an updated navigation section for this repository and includes the final published validation/archive details. In-report capture paths remain historical references, not missing teerex application files.

## Confidence labels

- **Documented:** stated by official documentation. Not necessarily exercised.
- **Observed in the research capture:** discovery and metadata exercised against Linux preview.15 in an isolated environment, not Joshua's installation.
- **Proposed:** a possible helper or integration; no implementation implied.
- **Unknown:** the evidence did not establish the contract, availability, or permission.

## Conclusions to retain

- Lua, terminal blocks, custom actions, and documented control/data APIs are practical surfaces to investigate for a terminal-first Rivet client.
- The captured custom-client wire protocol is available; Rex application implementation source is not. Official packaging code is not the application source.
- libghostty handles terminal emulation. Its API does not establish arbitrary widgets or renderer injection into Rex's shipped clients.
- OSC 7501 is a status channel, not a permission/approval API.
- Neither Rivet's transport/authentication nor a working Rex–Rivet integration was established here.
- Use the installed server's discovery output before designing against a website or this historical index.

## Inventory and complete capture

[catalog.json](api/catalog.json) retains all **524** original entry identities/categories and original capture locations. It intentionally excludes vendor descriptions, schemas, and examples. Its `path`, line ranges, and `pointer` fields address files inside the separately retained `rex-index/` bundle, **not this repository**. Some entries explicitly describe unretrieved source references or unresolved contracts; their existence in the index does not mean those files were acquired.

[Provenance](provenance/README.md) records the archive hash, acquisition manifest, capture checksums, and publication exclusions. Keep new-version observations separate rather than overwriting this capture. Start with the [level-one walkthrough](../docs/learning/level-1.md).
