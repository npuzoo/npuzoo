# Community model index

`community.json` lists every `.rkllm` file published on Hugging Face, with the
size and SHA-256 Hugging Face reports for it. `npuzoo find` searches it and
`npuzoo get` uses it to verify downloads.

- Rebuilt weekly by `.github/workflows/community-index.yml`
  (`python tools/build_community_index.py`). Do not edit by hand.
- One file per line, so each refresh is a readable diff.
- Only facts Hugging Face publishes are stored. What a file claims (chip,
  weight format, toolkit version) is read from its name when you search.
- The files belong to their authors and stay on Hugging Face; downloads go to
  them. npuzoo has not tested these files. Verified packages are what
  `npuzoo pull` is for.

Want your files left out? Open an issue and we will exclude the repo.
