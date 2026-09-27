# Vendored, not canonical

This is the Docker-reachable copy of `seed/wordlists/` (only `backend/` is
bind-mounted into the `backend`/`worker` containers and copied into a built
image — see `docker-compose.yml` and `backend/Dockerfile`). Provenance,
licences and how each file was produced live in `seed/wordlists/README.md`;
this directory is a byte-for-byte copy of the files the lexicon build and
`app.worker`'s lexicon loop actually read (`app.services.lexicon.WORDLISTS`).

Re-vendoring a list there means copying it here too — there is no symlink,
because `backend/` has to stay a self-contained Docker build context.
