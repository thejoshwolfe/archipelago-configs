#!/usr/bin/env python3

import os, sys, time
import json, re, configparser

from dataclasses import dataclass
from typing import List, Dict

def main():
    import argparse
    parser = argparse.ArgumentParser(description=
        "provide a config file of what custom_worlds you want to download and keep updated. "
        "here we are in the year 2025 reinventing the package manager for the umpteenth time.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--repo", metavar="/path/to/Archipelago", help=
        "Path to a clone of https://github.com/ArchipelagoMW/Archipelago . "
        "This program manages the custom_worlds/ dir within that repo.")
    group.add_argument("--custom-worlds", metavar="custom_worlds", help=
        "Path directly to the custom_worlds/ dir.")
    parser.add_argument("--config-path", metavar="config.ini", help=
        "Path to config.ini . Default is adjacent to this program")
    parser.add_argument("cmd", choices=["ls", "list", "check", "update"], nargs="?", default="list", help=
        "ls/list (default): list what is configured and what's present locally against what is cached about the latest versions. "
        "check: ask github what the latest version is of everything and then do a 'list'. "
        "update: update to the latest version and delete custom apworlds that are not in the configured list.")
    parser.add_argument("names", nargs="*", help=
        "the names of specific apworlds to limit the scope of the operation to. "
        'these are the [world "<name>"] names from the config.ini. '
        "giving any names to the 'update' command will disable deleting apworlds that are not in the configured list.")
    args = parser.parse_args()

    if args.repo != None:
        custom_worlds_dir = os.path.join(args.repo, "custom_worlds")
        if not os.path.isdir(custom_worlds_dir):
            raise FileNotFoundError(custom_worlds_dir) # This dir should have be initialized by `./cli.py init`
    elif args.custom_worlds != None:
        custom_worlds_dir = args.custom_worlds
        try: os.mkdir(custom_worlds_dir)
        except FileExistsError: pass
    else: assert False

    config_path = args.config_path or os.path.join(os.path.dirname(__file__), "config.ini")
    config = load_config(config_path)

    apworld_names_set = set(args.names)
    bogus_names = apworld_names_set - config.worlds.keys()
    if bogus_names:
        sys.exit("ERROR: apworld name{} not found in config: {}".format(["s", ""][len(bogus_names) == 1], ", ".join(sorted(bogus_names))))

    cache = Cache(custom_worlds_dir)
    cache.refresh_files()

    if args.cmd in ("ls", "list"):
        do_list(config, cache, apworld_names_set)
    elif args.cmd == "check":
        do_check(config, cache, apworld_names_set)
    elif args.cmd == "update":
        do_update(config, cache, apworld_names_set, custom_worlds_dir)
    else: assert False

def do_list(config, cache, apworld_names_set):
    orphaned_files = set(cache.files.keys())
    table = []
    for world_name, world_config in config.worlds.items():
        if len(apworld_names_set) > 0 and world_name not in apworld_names_set: continue

        if world_config.github_user_and_repo != None:
            cached_repo = cache.repos.get(world_config.github_user_and_repo, None)
            cached_file = cache.files.get(world_config.github_repo_asset, None)
            orphaned_files.discard(world_config.github_repo_asset)

            if cached_file != None and cached_repo != None:
                # Find what version this is by looking up a matching sha256_hex or size.
                newer_versions = []
                for release in cached_repo.releases:
                    try:
                        asset = release.assets[world_config.github_repo_asset]
                    except KeyError:
                        # A release for something else.
                        continue
                    if asset.sha256_hex == cached_file.sha256_hex or (
                        # Some repos don't publish digests for their assets. Fallback to size matching i guess.
                        asset.sha256_hex == None and asset.size == cached_file.size
                    ):
                        # Found it.
                        version, status = release.tag_name, "up to date" if len(newer_versions) == 0 else "update available"
                        break
                    # The asset name matches, but not the digest. Assume this is a newer version.
                    newer_versions.append(release)
                else:
                    version, status = "", "unknown version"
            elif cached_file == None and cached_repo != None:
                version, status = "", "(not downloaded)"
            elif cached_file != None and cached_repo == None:
                version, status = "", "(never checked)"
            elif cached_file == None and cached_repo == None:
                version, status = "", "(not downloaded, never checked)"
            else: assert False
        elif world_config.manual_file_name != None:
            if cached_file == None:
                version, status = "", "manual file missing from disk"
            else:
                orphaned_files.discard(world_config.manual_file_name)
                version, status = "", "(manually managed)"
        else: assert False
        table.append((world_name, version, status))

    if len(apworld_names_set) == 0:
        for file in sorted(orphaned_files):
            table.append((file, "", "not listed in config"))

    column_widths = [
        max(len(row[0]) for row in table),
        max(len(row[1]) for row in table),
    ]
    for row in table:
        print("{}  {}  {}".format(
            row[0].ljust(column_widths[0]),
            row[1].ljust(column_widths[1]),
            row[2],
        ))


def do_check(config, cache, apworld_names_set):
    orphaned_repos = set(cache.repos.keys())
    total = len(apworld_names_set or config.worlds)
    previous_line = ""
    for i, world_name in enumerate(apworld_names_set or config.worlds.keys()):
        world_config = config.worlds[world_name]
        if world_config.github_user_and_repo == None: continue
        line = "{}/{} {:.0%} {}".format(i, total, i/total, world_name)
        print("\b \b" * (len(previous_line) - len(line)) + "\r" + line, end="")
        previous_line = line
        cache.refresh_repo(world_config.github_user_and_repo)
        orphaned_repos.discard(world_config.github_user_and_repo)
    line = "{}/{} {:.0%}".format(total, total, 1.0)
    print("\b \b" * (len(previous_line) - len(line)) + "\r" + line)

    if len(apworld_names_set) == 0 and len(orphaned_repos) > 0:
        for user_and_repo in orphaned_repos:
            cache.repos[user_and_repo]
        cache.save()

def do_update(config, cache, apworld_names_set, custom_worlds_dir):
    download_count = 0
    orphaned_files = set(cache.files.keys())
    for world_name, world_config in config.worlds.items():
        if len(apworld_names_set) > 0 and world_name not in apworld_names_set: continue
        if world_config.manual_file_name != None:
            orphaned_files.discard(world_config.manual_file_name)
            continue
        try:
            cached_repo = cache.repos[world_config.github_user_and_repo]
        except KeyError:
            sys.exit("ERROR: run 'check' first")
        cached_file = cache.files.get(world_config.github_repo_asset, None)
        orphaned_files.discard(world_config.github_repo_asset)
        # Find what version this is by looking for a matching sha256_hex or size.
        up_to_date = False
        for release in cached_repo.releases:
            try:
                asset = release.assets[world_config.github_repo_asset]
            except KeyError:
                # A release for something else.
                continue
            if cached_file != None and (
                asset.sha256_hex == cached_file.sha256_hex or (
                    # Some repos don't publish digests for their assets. Fallback to size matching i guess.
                    asset.sha256_hex == None and asset.size == cached_file.size
                )
            ):
                # Found it.
                up_to_date = True
                break
            # The asset name matches, but not the digest. Assume there is a newer version.
            break
        else:
            sys.exit("ERROR: asset name {} not found in any release from https://github.com/{}/releases".format(
                repr(world_config.github_repo_asset),
                world_config.github_user_and_repo,
            ))
        if up_to_date: continue # Wish python had labeled continue.

        # Download the asset.
        url = "https://github.com/{}/releases/download/{}/{}".format(
            world_config.github_user_and_repo,
            release.tag_name,
            world_config.github_repo_asset,
        )
        dest_path = os.path.join(custom_worlds_dir, world_config.github_repo_asset)
        from urllib.request import urlopen
        from shutil import copyfileobj
        print("downloading: " + url)
        with urlopen(url) as r:
            with open(dest_path + ".tmp", "wb") as f:
                copyfileobj(r, f)
        os.rename(dest_path + ".tmp", dest_path)
        download_count += 1


    if download_count == 0:
        print("already up to date")
    else:
        cache.refresh_files()
        print("downloaded {} new item".format(download_count, ["s", ""][download_count == 1]))

    if len(apworld_names_set) == 0 and len(orphaned_files) > 0:
        for file in sorted(orphaned_files):
            path = os.path.join(custom_worlds_dir, file)
            print("deleting: " + path)
            os.remove(path)

@dataclass
class WorldConfig:
    github_user_and_repo: str | None
    github_repo_asset: str | None
    manual_file_name: str | None = None

class Config:
    worlds: Dict[str, WorldConfig] = {}
    def __init__(self):
        self.worlds = {}
    def __repr__(self):
        return "Config({})".format(repr(self.worlds))

def load_config(path):
    parser = configparser.ConfigParser(strict=True, interpolation=None)
    try:
        with open(path) as f:
            parser.read_file(f, source=path)
    except FileNotFoundError:
        pass

    config = Config()
    for section_name in parser.sections():
        [world_name] = re_match(r'^world "(.*)"$', section_name).groups()
        is_github = parser.has_option(section_name, "github_repo")
        assert is_github == parser.has_option(section_name, "github_repo_asset"), "must set github_repo and github_repo_asset together"
        is_manual = parser.has_option(section_name, "manual_file_name")
        assert is_github != is_manual, "cannot be both manual and managed by github repo"
        if is_github:
            (user, repo) = re_match([
                r'^https://github\.com/([^/]+)/([^/]+)',
                r'^([^/]+)/([^/]+)$',
            ], parser.get(section_name, "github_repo")).groups()
            world_config = WorldConfig(
                github_user_and_repo=user + "/" + repo,
                github_repo_asset=re_match(r'^.*\.apworld$', parser.get(section_name, "github_repo_asset")).group(),
            )
        elif is_manual:
            world_config = WorldConfig(None, None, re_match(r'^.*\.apworld$', parser.get(section_name, "manual_file_name")).group())
        else: assert False
        config.worlds[world_name] = world_config

    return config

@dataclass
class CachedFile:
    mtime: float
    size: int
    inode: int
    sha256_hex: str

@dataclass
class Asset:
    size: int
    sha256_hex: str | None
@dataclass
class Release:
    tag_name: str
    timestamp: str
    name: str
    body: str
    assets: Dict[str, Asset]
@dataclass
class CachedRepo:
    last_checked: float
    releases: List[Release] # Most recent first

class Cache:
    files: Dict[str, CachedFile]
    repos: Dict[str, CachedRepo]

    # meta
    dir: str
    def __init__(self, dir):
        self.files = {}
        self.repos = {}
        self.dir = dir
        try:
            with open(os.path.join(self.dir, ".cache_state.json")) as f:
                j = json.load(f)
        except FileNotFoundError:
            return
        for name, info in j.get("files", {}).items():
            self.files[name] = CachedFile(**info)
        for name, repo_info in j.get("repos", {}).items():
            self.repos[name] = CachedRepo(**{**repo_info, **{
                "releases": [
                    Release(**{**release_info, **{
                        "assets": {
                            asset_name: Asset(**asset_info)
                            for asset_name, asset_info in release_info["assets"].items()
                        },
                    }})
                    for release_info in repo_info["releases"]
                ],
            }})

    def save(self):
        path = os.path.join(self.dir, ".cache_state.json")
        with open(path+".tmp", "w") as f:
            json.dump({
                "files": {name: info.__dict__ for name, info in self.files.items()},
                "repos": {
                    user_and_repo: {**cached_repo.__dict__, **{
                        "releases": [
                            {**release.__dict__, **{
                                "assets": {
                                    asset_name: asset.__dict__ for asset_name, asset in release.assets.items()
                                },
                            }}
                            for release in cached_repo.releases
                        ],
                    }}
                    for user_and_repo, cached_repo in self.repos.items()
                },
            }, f, indent=2, sort_keys=True)
            f.write("\n")
        os.rename(path+".tmp", path)

    def refresh_files(self):
        dirty = False
        outstanding_keys = set(self.files.keys())
        for real_info in os.scandir(self.dir):
            name = real_info.name
            # Ignore files according to the same logic as this:
            # https://github.com/ArchipelagoMW/Archipelago/blob/4a0a65d60439f21ab6ae959f89c1a795637e128c/worlds/__init__.py#L92-L93
            if name.startswith(("_", ".")): continue
            stat = real_info.stat()
            try:
                expected = self.files[name]
            except KeyError:
                self.files[name] = load_cached_file(real_info.path, stat)
                dirty = True
            else:
                outstanding_keys.remove(name)
                # If these three match, then it's probably good. no need to do the expensive hashing.
                if (
                    expected.mtime == stat.st_mtime and
                    expected.size == stat.st_size and
                    expected.inode == stat.st_ino
                ):
                    self.files[name] = expected
                else:
                    self.files[name] = load_cached_file(real_info.path, stat)
                    dirty = True
        for name in outstanding_keys:
            del self.files[name]
            dirty = True
        if dirty:
            self.save()

    def refresh_repo(self, user_and_repo):
        try:
            cached_repo = self.repos[user_and_repo]
        except KeyError: pass
        else:
            fresh_enough_seconds = 3600
            if time.time() - cached_repo.last_checked < fresh_enough_seconds: return
        cached_repo = CachedRepo(
            last_checked=time.time(),
            releases=[],
        )

        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        full_response = []
        url = "https://api.github.com/repos/{}/releases?per_page=100".format(user_and_repo)
        while True:
            try:
                with urlopen(Request(url, headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                })) as response:
                    full_response.extend(json.load(response))

                    pagination_info = {
                        rel: url
                        for url, rel in re.findall(r'<(.*?)>; rel="(.*?)"', response.headers.get("link", ""))
                    }
                    try:
                        url = pagination_info["next"]
                    except KeyError:
                        break

            except HTTPError as e:
                if e.status in (403, 429) and e.headers.get("x-ratelimit-remaining") == '0':
                    wait_time = int(e.headers.get("x-ratelimit-reset")) - int(time.time())
                    sys.exit("ERROR: github is rate limiting us. we need to wait {} before trying again".format(format_time(wait_time)))
                raise

        for release_info in full_response:
            cached_repo.releases.append(Release(
                tag_name=release_info["tag_name"],
                timestamp=sorted([
                    release_info["created_at"],
                    release_info.get("updated_at", None) or "",
                    release_info.get("published_at", None) or "",
                ])[-1],
                name=release_info.get("name", None) or "",
                body=release_info.get("body", None) or "",
                assets={
                    asset_info["name"]: Asset(
                        size=asset_info["size"],
                        sha256_hex=re_match(r'^sha256:([0-9a-f]{64})$', asset_info["digest"]).group(1) if asset_info.get("digest", None) else None,
                    )
                    for asset_info in release_info["assets"]
                },
            ))
        self.repos[user_and_repo] = cached_repo
        self.save()

def load_cached_file(path, stat):
    import hashlib
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(0x1000)
            if len(chunk) == 0: break
            sha256.update(chunk)
    return CachedFile(
        mtime=stat.st_mtime,
        size=stat.st_size,
        inode=stat.st_ino,
        sha256_hex=sha256.hexdigest(),
    )

def re_match(patterns, string):
    if type(patterns) == str:
        patterns = [patterns]
    for pattern in patterns:
        match = re.match(pattern, string)
        if match != None:
            return match
    if len(patterns) == 1:
        raise ValueError("expected string to match regex: {}, found: {}".format(repr(patterns[0]), repr(string)))
    else:
        raise ValueError("expected string to match one regex: {}, found: {}".format(", ".join(repr(p) for p in patterns), repr(string)))

def format_time(seconds):
    if seconds < 60:
        return "{}s".format(seconds)
    elif seconds < 3600:
        return "{}m{:0>2}s".format(seconds // 60, seconds % 60)
    else:
        return "{}h{:0>2}m{:0>2}s".format(seconds // 3600, (seconds % 3600) // 60, seconds % 60)

if __name__ == "__main__":
    main()
