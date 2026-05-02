from importlib.metadata import metadata, version

__version__ = version("koma")

_meta = metadata("koma")
_urls = dict(url.split(", ", 1) for url in _meta.get_all("Project-URL") or [])

__repository__ = _urls.get("Repository", "https://github.com/grasssand/koma")
__issue_tracker__ = _urls.get("Bug Tracker", f"{__repository__}/issues")
__releases__ = f"{__repository__}/releases"

if __repository__.startswith("https://github.com/"):
    _repo_path = __repository__.split("github.com/")[-1].strip("/")
    __api_releases__ = f"https://api.github.com/repos/{_repo_path}/releases/latest"
else:
    __api_releases__ = ""
