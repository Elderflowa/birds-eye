<p align="center"><img src="assets/icon.png" width="120" alt="Birds Eye logo"></p>

# Birds Eye

Watches all of my public GitHub repositories and collects every release that contains an `.ipa` into one AltStore-compatible source. Add the source once in Feather (or AltStore, SideStore) and every app I publish shows up there.

## Add the source

```
https://raw.githubusercontent.com/Elderflowa/birds-eye/main/source.json
```

- **Feather:** open `feather://source/https://raw.githubusercontent.com/Elderflowa/birds-eye/main/source.json` on your iPhone, or paste the URL in the Sources tab.
- **AltStore and SideStore:** Sources, then add the URL.

## How it works

A GitHub Actions workflow runs every 30 minutes (and on demand):

1. Lists the public repositories of the account in `config.json`.
2. Reads each repo's latest releases and finds `.ipa` assets.
3. Downloads each new IPA once and reads the bundle ID, version and minimum iOS version from its `Info.plist`. Results are remembered in `cache.json`.
4. Looks for an icon in the repo (`assets/icon.png`, `icon.png` and a few other names).
5. Writes `source.json` with the legacy fields and the newer `versions` list, then commits it only when something changed.

## Making an app show up

Publish a GitHub release with an `.ipa` attached. That's all. To get an icon in the list, put a square PNG at `assets/icon.png` in that repo. To make Feather offer updates, each release needs a new `CFBundleShortVersionString` (the app's marketing version).

## Setup

1. Push this repo to `Elderflowa/birds-eye` (public).
2. Settings, Actions, General, Workflow permissions: choose read and write.
3. Actions tab, run `Update source` once.

## Config

`config.json` controls the account, source name and tint, whether forks, archived repos and pre-releases are included, how many versions are kept per app, the largest IPA it will inspect, and which repos to skip.

## Limits

- Public repos only. A private release asset can't be downloaded by Feather.
- GitHub pauses scheduled workflows after 60 days without repo activity. Any commit, or a manual run, wakes it up again.
- Raw GitHub URLs are cached for a few minutes, so a new release can take a little while to appear.
