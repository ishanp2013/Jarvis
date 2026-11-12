"""GitHub through the official REST API with your own personal access token (Connections -> GitHub).
A fine-grained token with read access to notifications, issues and pull requests is enough; add
Issues: write if you want Jarvis to open issues. The token is kept in Windows Credential Manager."""
import httpx

from ..config import get_secret, settings

API = "https://api.github.com"


def connected():
    return bool(settings.get("github_enabled") and get_secret("github_token"))


def _req(method, path, **kw):
    token = get_secret("github_token")
    if not token:
        raise RuntimeError("GitHub isn't connected. Add a personal access token under Connections.")
    r = httpx.request(method, API + path, timeout=20, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "JarvisAssistant"}, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"GitHub error {r.status_code}: {r.json().get('message', '') if r.content else ''}")
    return r.json() if r.content else {}


def whoami():
    return _req("GET", "/user")["login"]


def notifications(limit=10):
    try:
        rows = _req("GET", "/notifications", params={"per_page": limit})
    except RuntimeError as e:
        if "403" in str(e):  # GitHub only lets classic tokens read notifications
            raise RuntimeError("GitHub doesn't let fine-grained tokens read notifications. To get them, make a classic "
                               "token with the notifications and repo scopes and connect that instead. "
                               "Your repos, issues and pull requests work with the token you have.") from e
        raise
    return [{"repo": n["repository"]["full_name"], "type": n["subject"]["type"], "title": n["subject"]["title"],
             "reason": n.get("reason", ""), "updated": n.get("updated_at", "")[:10]} for n in rows]


def my_repos(limit=10):
    return [{"name": r["full_name"], "stars": r["stargazers_count"], "updated": r["pushed_at"][:10],
             "private": r["private"], "url": r["html_url"]}
            for r in _req("GET", "/user/repos", params={"sort": "pushed", "per_page": limit})]


def my_work(limit=10):
    """Open issues assigned to you and pull requests waiting for your review."""
    me = whoami()
    found = []
    for q, kind in ((f"is:open assignee:{me}", "assigned"), (f"is:open is:pr review-requested:{me}", "review requested")):
        for i in _req("GET", "/search/issues", params={"q": q, "per_page": limit}).get("items", []):
            found.append({"what": kind, "title": i["title"], "repo": i["repository_url"].split("/repos/")[-1], "url": i["html_url"]})
    return found


def repo_info(repo):
    r = _req("GET", f"/repos/{repo}")
    return {"name": r["full_name"], "description": r.get("description") or "", "stars": r["stargazers_count"],
            "open_issues": r["open_issues_count"], "last_push": r["pushed_at"][:10], "url": r["html_url"]}


def create_issue(repo, title, body=""):
    i = _req("POST", f"/repos/{repo}/issues", json={"title": title, "body": body})
    return f"Opened issue #{i['number']} in {repo}: {i['html_url']}"
