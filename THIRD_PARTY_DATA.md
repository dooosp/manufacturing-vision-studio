# Third-party data and artifact policy

## Public repository inventory

The reproducible demo and CI use only project-generated synthetic inputs. The
checked-in synthetic fixtures, masks, manifests, screenshots, and release
evidence were generated for this project by its contributors and are released
under the repository's [MIT License](LICENSE), unless a file explicitly says
otherwise.

No customer imagery, proprietary CAD, production capture, personal data, or
third-party benchmark payload is included. Hashes and provenance records prove
byte identity; they do not by themselves prove ownership, consent, or field
validity.

| Source | Included in Git | Default setup/CI | Terms and boundary |
| --- | --- | --- | --- |
| Project-generated synthetic fixtures and truth | Yes, when intentionally reviewed | Yes | Repository MIT license; synthetic demo evidence only |
| Project-generated screenshots and evidence bundle | Yes, in `docs/` | No external download | Repository MIT license; tied to the declared release packet |
| User-supplied images or manifests | No | No | The user must hold all required rights; local input only |
| FreeCAD export manifest or CAD files | No | No | Optional read-only local adapter; source-file terms remain with the user |
| MVTec AD images, annotations, archives, or derivatives | No | No | Optional caller-supplied, non-commercial dataset; never redistributed here |

## MVTec AD boundary

MVTec AD is published separately under
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) and MVTec
states that commercial use is not allowed. The authoritative dataset and terms
are maintained on the
[MVTec AD page](https://www.mvtec.com/research-teaching/datasets/mvtec-ad).
This summary is an engineering control, not legal advice.

The optional `mvs-mvtec` adapter only inventories a path supplied by the user
after an explicit non-commercial-license acknowledgement. The project does
not download the dataset. Raw images, annotations, archives, thumbnails,
transforms, caches, and derived media must remain outside the repository and
outside release assets. Public metrics or screenshots based on MVTec require a
separate license and attribution review.

## Contribution and release controls

Before committing or publishing an artifact, verify all of the following:

1. Its source, owner, generator/adapter version, applicable license, and
   transformation history are known.
2. Publication is permitted for the intended public and commercial context.
3. It contains no customer identifiers, faces, badges, serial numbers,
   credentials, machine paths, proprietary geometry, or embedded metadata that
   should remain private.
4. Any checked-in synthetic artifact has deterministic provenance and a stable
   SHA-256 recorded where the evidence contract requires it.
5. Runtime databases, uploads, environment files, private datasets, and build
   output remain ignored and untracked.
6. MVTec or other externally licensed data is not copied into examples,
   screenshots, evidence bundles, test fixtures, caches, or release archives.

If rights or provenance are ambiguous, do not commit or publish the artifact.
Use a project-owned synthetic substitute and document the limitation instead.

The detailed lineage and data-handling model is in
[`docs/data/data-and-licensing.md`](docs/data/data-and-licensing.md).
