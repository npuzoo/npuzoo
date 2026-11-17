# Community model index

`community.json` lists every `.rkllm` file published on Hugging Face and on
ModelScope (魔搭), with the size and SHA-256 each site reports for it. Each entry
says which site it came from (`source`). `npuzoo find` searches it and
`npuzoo get` uses it to verify downloads.

- Rebuilt weekly by `.github/workflows/community-index.yml`
  (`python tools/build_community_index.py`). Do not edit by hand.
- One file per line, so each refresh is a readable diff.
- Only facts Hugging Face publishes are stored. What a file claims (chip,
  weight format, toolkit version) is read from its name when you search.
- The files belong to their authors and stay where they were published;
  downloads go to them. ModelScope reports total downloads, Hugging Face the
  last 30 days, so the two are not compared. npuzoo has not tested these files. Verified packages are what
  `npuzoo pull` is for.

Want your files left out? Open an issue and we will exclude the repo.
