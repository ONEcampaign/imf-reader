# Caching

`imf-reader` caches data to disk. Repeated calls avoid re-requesting from the IMF, and results survive process restarts.

## Where the cache lives

The cache root sits in the platform-appropriate user cache directory, under a `readerkit` root shared with other packages built on the same caching library:

- **Linux:** `~/.cache/readerkit/v1/imf-reader/<version>/`
- **macOS:** `~/Library/Caches/readerkit/v1/imf-reader/<version>/`
- **Windows:** `%LOCALAPPDATA%\readerkit\Cache\v1\imf-reader\<version>\`

`<version>` is the installed package version. Print the resolved root rather than
building the path by hand:

```python
import imf_reader
from imf_reader import cache

print(imf_reader.__version__)
print(cache.get_cache_dir())
```

!!! info "Why"

    The root is segmented by package version. Each version's cache lives in its own directory, so upgrading `imf-reader` starts with a clean cache automatically.

!!! warning "Heads up"

    Old version directories accumulate on disk as you upgrade, since nothing removes them automatically. Segmentation only helps across a released version bump. An editable or git-pinned install stays inside the same version segment while the code underneath it changes, so the cache directory stays fixed even as the code changes. See [Editable and git installs](#editable-and-git-installs) below.

## How long entries live

| Data                                                      | TTL    |
| --------------------------------------------------------- | ------ |
| WEO observations                                          | 7 days |
| WEO series metadata sidecar                               | 7 days |
| WEO version mapping                                       | 1 hour |
| SDR holdings, allocations, exchange rates, interest rates | 7 days |
| SDR latest-available-date lookup                          | 1 day  |

WEO series metadata is cached separately from WEO observations, so a failed metadata request
leaves the already-cached observations untouched.

One cached sidecar entry backs `weo.fetch_series_metadata()` and `weo.api.get_series_metadata()`
as well as `fetch_data`'s `LASTACTUALDATE`, `NOTES`, and `COUNTRY_UPDATE_DATE` columns, all four
read from the same underlying fetch. Calling `fetch_series_metadata()` after `fetch_data()` (or
the reverse) for the same release costs no extra request beyond the first one, since the second
call is served from the entry the first one wrote.

The sidecar's cache key includes a schema discriminator, so an entry written under an older
schema is never read by code expecting a different column set: it orphans itself rather than
being served back, and no `clear_cache()` call is needed when the schema changes.

## Redirect the cache

Set `IMF_READER_CACHE_DIR` before the first call that touches the cache:

```bash
export IMF_READER_CACHE_DIR=/path/to/my/cache
```

If `IMF_READER_CACHE_DIR` is unset, `BBLOCKS_CACHE_DIR` is used instead. It's a fallback shared across the bblocks family, useful for pointing several packages at one cache root:

```bash
export BBLOCKS_CACHE_DIR=/path/to/shared/cache
```

Or redirect at runtime:

```python
from imf_reader import cache

cache.set_cache_dir("/path/to/my/cache")
cache.get_cache_dir()       # inspect the current path
cache.reset_cache_dir()     # restore the platformdirs default
```

## Clear the cache

```python
from imf_reader import cache

cache.clear_cache()               # everything
cache.clear_cache(scope="weo")    # WEO data only
cache.clear_cache(scope="sdr")    # SDR data only
cache.clear_cache(scope="http")   # HTTP-layer cache only
```

| Scope  | Removes                                           |
| ------ | ------------------------------------------------- |
| `all`  | Every sublayer under the cache root (the default) |
| `weo`  | WEO SDMX artifacts and parsed WEO frames          |
| `sdr`  | Parsed SDR frames                                 |
| `http` | Cached raw HTTP responses                         |

A scoped clear leaves the other scopes intact. `scope="sdr"` removes SDR data and leaves WEO and HTTP caches in place. Clearing `http` (or `all`) also closes the active HTTP session, so the next request opens a fresh one.

## The deprecated helpers

`weo.clear_cache()`, `weo.api.clear_cache()`, and `sdr.clear_cache()` continue to work but are deprecated. Each emits a `DeprecationWarning` pointing at `cache.clear_cache()` and is removed in 3.0.

```python
from imf_reader import weo, sdr

weo.clear_cache()   # deprecated, use cache.clear_cache(scope="weo")
sdr.clear_cache()   # deprecated, use cache.clear_cache(scope="sdr")
```

## Editable and git installs

The cache root is segmented by _installed version_, not by commit (see [Where the cache lives](#where-the-cache-lives)). An editable install (`pip install -e .`) or a git-pinned install keeps reporting the same version as the code underneath it changes, so it stays inside the same cache directory across a `git pull` or a branch switch. A stale entry written by older code can outlive the code that wrote it.

If you're on one of these installs and pick up a change to how WEO data is fetched, resolved, or labelled, clear the cache explicitly rather than relying on the version segment to do it for you:

```python
from imf_reader import cache

cache.clear_cache()
```

If you've saved an extract to disk outside the package's cache (a CSV or parquet copy labelled with a WEO release), re-pull it rather than trusting the label. The code that produced it may have changed since you saved it.

## Inspect cache paths

```python
from imf_reader import cache

cache.get_cache_dir()             # the cache root
cache.get_bulk_cache_dir()        # WEO bulk SDMX artifact namespace
cache.get_dataframe_cache_dir()   # the SDR sublayer
cache.get_http_cache_path()       # the HTTP sublayer
```

!!! warning "Heads up"

    `get_dataframe_cache_dir()` returns the SDR sublayer only, for parity with `oda_reader`, whose single dataframe sublayer maps directly to one helper. `imf-reader` splits parsed frames across three sublayers (`sdr`, `weo_api`, `weo_sdmx_parsed`).

    For a WEO cache path, build it from the root instead:

    ```python
    from imf_reader import cache

    cache.get_cache_dir() / "weo_api"
    cache.get_cache_dir() / "weo_sdmx_parsed"
    ```

## Disable caching

```python
from imf_reader import cache

cache.disable_cache()
# ... work without caching ...
cache.enable_cache()
```

While disabled, decorated functions bypass both the read and write cache paths and call through to the underlying fetch directly. Bulk downloads go to a temp file used only for that call. Data already on disk from before `disable_cache()` is untouched.

## Corrupted bulk downloads

A corrupt WEO bulk download is evicted from the cache automatically and raises `cache.BulkPayloadCorruptError`. Re-running the same call triggers a fresh download:

```python
from imf_reader import cache, weo

try:
    df = weo.fetch_data()
except cache.BulkPayloadCorruptError:
    df = weo.fetch_data()
```

The exception carries `is_retryable`. It's `False` for the two WEO releases that are permanently corrupt in the IMF's own published archive, where retrying cannot help. See [WEO coverage and known issues](weo-coverage.md) for which releases those are.

## Caches on NFS

If the cache directory sits on an NFS mount, set `READERKIT_LOCK_STRATEGY=strict-soft` to switch from native file locking to marker-file locking, which NFS supports more reliably.

## Next steps

- [World Economic Outlook](weo.md) - the module whose data makes up most of what's cached
- [Special Drawing Rights](sdr.md) - the other cached data source, and its argument-order trap
- [WEO coverage and known issues](weo-coverage.md) - more on the two permanently-corrupt releases
