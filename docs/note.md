

## `docker compose up -d` vs `docker compose up -d --build`

| Command | What it does |
|---|---|
| `docker compose up -d` | Starts containers. **If the image already exists**, it uses it. Does **not** rebuild. |
| `docker compose up -d --build` | **Forces a rebuild** of the image from the Dockerfile, then starts. |

So:

### First time (after the wipe)

```bash
cd /path/to/project
docker compose up -d --build
```

This builds the image and starts the container. ✅ (You need `--build` because the images were deleted.)

### Next time — stop and start again

**To stop without deleting anything:**

```bash
docker compose stop        # stops containers, keeps them + images
```

Then bring back up:

```bash
docker compose up -d       # NO --build → uses existing image, fast
```

✅ No rebuild. Just restarts.

### Other stop variants

| Command | Removes containers? | Removes images? | Removes volumes? |
|---|---|---|---|
| `docker compose stop` | ❌ keeps | ❌ keeps | ❌ keeps |
| `docker compose down` | ✅ removes | ❌ keeps | ❌ keeps |
| `docker compose down -v` | ✅ removes | ❌ keeps | ✅ **removes volumes (data!)** |
| `docker compose down --rmi all` | ✅ removes | ✅ **removes images** | ❌ keeps |

### So to answer directly

- **First time:** `docker compose up -d --build` ← you must use `--build`
- **After `docker compose stop`:** `docker compose up -d` ← no rebuild, uses the existing image
- **After `docker compose down`:** `docker compose up -d` ← still no rebuild, image is still there
- **After `docker compose down --rmi all`:** `docker compose up -d --build` ← images gone, must rebuild

### Rule of thumb

- You only need `--build` when:
  - You changed the `Dockerfile`
  - You changed files that get copied into the image (e.g. `COPY . .`) and want the new version baked in
  - The image was deleted
- Otherwise, plain `docker compose up -d` reuses the cached image and is nearly instant.

### Extra tip — check what's actually there

```bash
docker compose ps          # what's running
docker images              # what images exist
docker compose config      # sanity-check your compose file
```

If you change Python code that's mounted via a **volume** (bind mount), you often don't need to rebuild at all — just restart:

```bash
docker compose restart <service>
```











## What `--build` actually does

`docker compose up --build` = **rebuild the image from the Dockerfile**, then start the container.

But "rebuild" ≠ "start from scratch." Docker uses a **layer cache**:

- Each line in your `Dockerfile` (`FROM`, `RUN`, `COPY`, `RUN pip install`, etc.) produces a layer.
- If nothing changed above a given line, Docker **reuses the cached layer** — no re-download, no re-install.
- Only the layers **after** the first changed instruction get rebuilt.

## Concrete example

Your Dockerfile probably looks something like:

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y build-essential
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "app:app"]
```

| What you changed | What gets rebuilt |
|---|---|
| Nothing | Nothing — all cached, build takes ~2 seconds |
| Only app code (`COPY . .`) | Last `COPY` layer + `CMD` — fast, no pip reinstall |
| `requirements.txt` | `pip install` layer + everything after — pip reinstalls (but pip also has its own cache) |
| `FROM ...` line | Everything — full rebuild |

## Stop vs. down — what survives?

| Action | Containers | Images | Layer cache | Volumes |
|---|---|---|---|---|
| `docker compose stop` | kept (stopped) | kept | kept | kept |
| `docker compose down` | removed | **kept** | kept | kept |
| `docker compose down -v` | removed | kept | kept | **removed** |
| `docker compose down --rmi all` | removed | **removed** | kept | kept |
| `docker builder prune` | — | kept | **removed** | — |
| `docker system prune -a` | removed | removed | **removed** | removed |

Note: even `--rmi all` removes the **image** but the **build cache** stays, so the next `--build` is still fast.

## So the practical rule

### For daily use — you almost never need `--build`

```bash
docker compose up -d          # start (uses existing image)
docker compose stop           # stop, keep everything
docker compose down           # stop + remove containers, keep image
docker compose up -d          # start again — instant
```

### When you actually changed something

```bash
# Changed Dockerfile or requirements.txt or code that's COPY'd in:
docker compose up -d --build

# Changed only code that's bind-mounted (volumes: ./app:/app), no rebuild needed:
docker compose restart
```

### To force a true rebuild (ignore cache)

```bash
docker compose build --no-cache
docker compose up -d
```

Use this rarely — it makes the build slow (re-downloads, re-installs everything).

## What you should do — recommended workflow

```bash
# First time after the disk wipe:
docker compose up -d --build

# Every normal restart:
docker compose up -d

# When you edited code that lives INSIDE the image (not a bind mount):
docker compose up -d --build

# When you changed the Dockerfile:
docker compose up -d --build
```

## How to check what's happening

```bash
docker images                # see built images
docker compose config --images   # which image names compose expects
docker compose ps            # what's running
docker builder du           # how much build cache exists
```

Watch the `--build` output — you'll see lines like:

```
=> CACHED [2/6] RUN apt-get update          0.0s
=> CACHED [3/6] COPY requirements.txt .     0.0s
=> [4/6] RUN pip install -r requirements.txt   45.2s
```

`CACHED` = reused, no download. `[4/6]` without `CACHED` = freshly built.

## TL;DR

- `docker compose up --build` **does not re-download everything** unless the top of the Dockerfile changed.
- Docker's layer cache makes repeat builds fast — usually seconds if only app code changed.
- You don't need `--build` at all for a simple stop/start.
- If you ever want to *truly* rebuild from scratch: `docker compose build --no-cache`.

So your instinct is right: after the first build, you can just use `docker compose up -d` from then on. Only add `--build` when you've actually changed something in the image.