# Self-hosted fonts

These Latin, normal-style variable fonts are unmodified Fontsource files, renamed locally to identify their width and weight axes. Both the font bytes and accompanying licenses were compared with the exact npm package tarballs below on 2026-11-04.

| Local font | Source package | Original file inside the package |
| --- | --- | --- |
| `zalando-sans-latin-wdth-wght.woff2` | [`@fontsource-variable/zalando-sans@5.3.0`](https://www.npmjs.com/package/@fontsource-variable/zalando-sans/v/5.3.0) | `files/zalando-sans-latin-standard-normal.woff2` |
| `martian-mono-latin-wdth-wght.woff2` | [`@fontsource-variable/martian-mono@5.3.0`](https://www.npmjs.com/package/@fontsource-variable/martian-mono/v/5.3.0) | `files/martian-mono-latin-standard-normal.woff2` |

Zalando Sans supplies width 75–125 and weight 200–900; Martian Mono supplies width 75–112.5 and weight 100–800. These files contain the packages' Latin subsets, not their full character sets. UI check and cross marks use SVG rather than assuming those glyphs are present.

Both families use the SIL Open Font License 1.1. Each package's `LICENSE` is copied verbatim as [OFL-ZalandoSans.txt](OFL-ZalandoSans.txt) or [OFL-MartianMono.txt](OFL-MartianMono.txt), including its copyright notice. Upstream projects: [Zalando Sans](https://github.com/zalando/sans) and [Martian Mono](https://github.com/evilmartians/mono).

## Checksums and mirrors

[SHA256SUMS](SHA256SUMS) pins all four redistributed files. Its paths are relative to the repository root:

| File | SHA256 |
| --- | --- |
| `zalando-sans-latin-wdth-wght.woff2` | `b6c643588e488111e13d703d8f69e4bba958efed99996912ab6073a889f60bba` |
| `martian-mono-latin-wdth-wght.woff2` | `f9c1655c2c9d1ed5bb8b301a57d1169a1123ffef1a588dc50a7a487810f7d732` |
| `OFL-ZalandoSans.txt` | `aef4b7266d8333367fbd9ba508d12042bf04d4df7a85eb09f0a73389dd8d9f5a` |
| `OFL-MartianMono.txt` | `bd7d799f6a67b704f9546422ee83d69b4dc5e4ae289d5eabc22581251dd7150a` |

The Inspector keeps byte-identical copies in `web/inspector-ui/src/app/fonts/` because its Next.js build resolves local fonts inside that project. Verify the pinned files and both font/license mirrors from the repository root:

```sh
sha256sum -c docs/assets/fonts/SHA256SUMS
for font_file in docs/assets/fonts/*.woff2 docs/assets/fonts/OFL-*.txt; do
  cmp "$font_file" "web/inspector-ui/src/app/fonts/${font_file##*/}" || exit 1
done
```

For source verification, fetch the exact packages into a scratch directory with `npm pack --ignore-scripts @fontsource-variable/zalando-sans@5.3.0 @fontsource-variable/martian-mono@5.3.0`; unpack each archive separately, then compare the original files listed above and each `LICENSE` with the local copies. No package installation is needed. The verified archive SHA256 values are:

| Archive | SHA256 |
| --- | --- |
| `fontsource-variable-zalando-sans-5.3.0.tgz` | `5de8b73a6fcec859383c07f8033f0e174bb9826e6edea69ff287d34eaf44fda9` |
| `fontsource-variable-martian-mono-5.3.0.tgz` | `afc3bc6b2430884732c11a04433f2d98db2811e000d0f74aeb4fdee9c2b9f868` |

When updating fonts, update the exact source versions, licenses, checksum manifest and Inspector copies together.
