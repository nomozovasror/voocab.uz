# Seed run on the Windows RTX 3060 (driven from the Mac over SSH)

Topology: the Mac keeps the dev Postgres and `backend/media`. The 3060 runs
`scripts.seed_tts` against the Mac's database through an SSH **reverse tunnel**
(Postgres is never exposed to the LAN), writes files to a LOCAL Windows folder,
and the files are copied to the Mac with `tar | ssh`. Nothing is on GitHub or
SMB. `win` below is the SSH host alias of the Windows machine.

Windows paths used here: code `D:\voocab`, media `D:\voocab-media`. Change freely
(short paths; torch has deep ones).

## 0. One-time, Windows (owner, at the machine)

```powershell
# OpenSSH server (admin PowerShell)
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd; Set-Service sshd -StartupType Automatic
# never sleep during the run
powercfg /change standby-timeout-ac 0
# uv + Python 3.14
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv python install 3.14
mkdir D:\voocab, D:\voocab-media
```

Leave the default SSH shell as **cmd.exe**: PowerShell as default shell can
mangle binary stdin, and the file copies below pipe raw `tar`. Run PowerShell
explicitly when you need it: `ssh win powershell -NoProfile -Command "..."`.
Use key auth (`administrators_authorized_keys` for an admin account).
NVIDIA driver 570+ (CUDA 12.8 torch); `nvidia-smi` must work.

## 1. Mac: tunnel, code, config

```bash
# a) tunnel (own terminal, leave open): Windows' 127.0.0.1:15432 -> Mac's Postgres
ssh -N -R 127.0.0.1:15432:localhost:5432 -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes win

# b) code (working tree, no venv/media/secrets). From the repo root:
COPYFILE_DISABLE=1 tar -cf - --exclude .venv --exclude media --exclude .env \
  --exclude __pycache__ --exclude .pytest_cache backend | ssh win "tar -xf - -C D:/voocab"
# (committed state instead: git archive --format=tar HEAD backend | ssh win "tar -xf - -C D:/voocab")

# c) config: write this file on the Mac, then copy it as backend\.env
cat > /tmp/win.env <<'ENV'
DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:15432/app
MEDIA_ROOT=D:/voocab-media
ENV
scp /tmp/win.env win:D:/voocab/backend/.env && rm /tmp/win.env
# No R2 keys, no Gemini key: they are not needed, and R2 keys would make
# the run write to R2 instead of the folder (doctor warns if it sees them).
```

Same database means same schema: the Mac database must already be migrated to
the head of THIS code (`doctor` checks it).

## 2. Windows (over ssh): install, then doctor

```bash
ssh win powershell -NoProfile -Command "cd D:\voocab\backend; uv sync --extra tts-gpu"
ssh win powershell -NoProfile -Command "cd D:\voocab\backend; uv run python -m scripts.seed_tts doctor"
```

Every line must be PASS. First run downloads Kokoro (~330 MB) from
huggingface.co. Every check has its fix on the line under a FAIL. Exit code is
non-zero on any FAIL. (Whisper is no longer needed here: live clips were
dropped on 2026-10-07, so there is no verification step and no CUDA 12 / cuDNN 9
requirement beyond what the `tts-gpu` torch wheel brings.)

## 3. The run, in this order

Run each as a detached process with a log (it survives the ssh session ending;
if it dies anyway, just start it again, see Resuming):

```bash
```bash
ssh win powershell -NoProfile -Command "cd D:\voocab\backend; Start-Process -WindowStyle Hidden -FilePath uv -ArgumentList 'run','python','-m','scripts.seed_tts','words' -RedirectStandardOutput D:\voocab\words.log -RedirectStandardError D:\voocab\words.err"
ssh win powershell -NoProfile -Command "Get-Content D:\voocab\words.err -Tail 5"   # logging goes to stderr
```

1. `words --accent both` (every word is TTS; nothing else to do first)
2. `definitions --accent both`

(`items` is optional and not part of this run.) Add `--limit 50` first as a
pilot if you like. Flags: `--concurrency N` (default 8, max 12).

Estimates, NOT measured on a 3060 (read the live ETA instead): `words` about 24k renders, 15-40 min;
`definitions` about 35k renders, 45-120 min; roughly 1 GB of files in total.
The Mac's Docker worker keeps draining the same queues on CPU meanwhile; claims
are `SKIP LOCKED`, so nothing is made twice (it just takes a few percent).

Progress from the Mac:

```bash
docker compose exec db psql -U postgres -d app -c \
 "select kind, status, count(*) from audio_renders group by 1,2 order by 1,2"
```

## 4. Copy the audio back (Windows -> Mac) -- and the "ready but no file" window

A render is `ready` in the database the moment its file is written on Windows,
but the Mac only has the file once you copy it. Until then the dev site asks
for a file that is not there and the frontend treats it as no audio (nothing
breaks, that word just is not heard yet). Mitigation, kept simple: copy back in
rounds during the run, and once more at the end. Files are content-addressed, so
re-copying is harmless:

```bash
# from the repo root on the Mac; repeat every ~10-15 min while it runs, and at the end
ssh win "tar -cf - --exclude *.tmp -C D:/voocab-media tts" | tar -xf - -C backend/media
# (`renders` instead of `tts` for On the go files, only if you ran `items`)
```

Then, on the Mac, from `backend/`, prove nothing is dangling (and requeue any
render whose file never arrived, so the Mac worker makes it):

```bash
uv run python -m scripts.seed_tts check-files --requeue
```

## 5. Resuming

Everything is idempotent. A stopped or crashed run: start the same command
again. Renders are keyed by input hash (never made twice); rows a killed run left
`processing` are put back by age (15 min) at the next start, and Ctrl+C releases
them at once. Failed renders (`audio_renders.status = 'failed'`, reason in
`error`, e.g. "no pronunciation for ...") are retried with `--retry-failed`.
If the tunnel drops, the run stops with a database error: restore the tunnel,
re-run.

## 6. Afterwards (Mac)

- Stop the tunnel (Ctrl+C its terminal). Delete `D:\voocab-media` if you like.
- **Security:** `docker-compose.yml` publishes Postgres on all interfaces
  with `postgres`/`postgres`. Bind it to loopback and recreate the db container:

  ```yaml
  ports:
    - "127.0.0.1:5432:5432"
  ```
  ```bash
  docker compose up -d db
  ```
  (The tunnel needs only Mac-local access, so nothing here depends on the LAN port.)
