"""Security regression matrix. Synthetic fixtures only (FakeStore, in-process TestClient): no network, no real project.

Model under test: the API has no user accounts. The unguessable media_id is the capability for one item
("owner" = whoever created the upload and holds its id). The worker/admin token is the only other credential.
  M1  anonymous callers get no protected metadata or signed URLs from any endpoint
  M2  one actor cannot read another's media by guessing/probing ids or paths
  M3  the owner and worker paths still work
  M4  worker-only actions are not reachable from a browser without the token
"""
import os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend")); sys.path.insert(0, os.path.join(ROOT, "tests"))
TOKEN = "secret-token"
os.environ.setdefault("WORKER_TRIGGER_TOKEN", TOKEN)

from fastapi.testclient import TestClient
from fake_store import FakeStore
import supabase_api
from supabase_api import create_app
from supabase_worker import process_media
from supabase_config import INPUT_BUCKET, OUTPUT_BUCKET

IMG = os.path.join(ROOT, "tests", "test_images", "landscape.jpg")
with open(IMG, "rb") as f: IMG_BYTES = f.read()
SENSITIVE = ("signed", "fake://", "uploads/", "processed/", "thumbnails/", "original_path", "processed_path", "thumbnail_path", "token")


def make_actor_upload(client, store, name):
    j = client.post("/api/uploads", json={"filename": name, "size": len(IMG_BYTES), "content_type": "image/jpeg"}).json()
    store.objects[(INPUT_BUCKET, j["path"])] = IMG_BYTES
    assert client.post(f"/api/uploads/{j['media_id']}/complete").status_code == 200
    return j["media_id"]


class Matrix(unittest.TestCase):
    def setUp(self):
        self._saved = (supabase_api.WORKER_TOKEN, supabase_api.UPLOADS_PER_HOUR)
        supabase_api.WORKER_TOKEN = TOKEN
        supabase_api.UPLOADS_PER_HOUR = 1000
        self.store = FakeStore()
        self.app = create_app(self.store, process_media)
        self.anon = TestClient(self.app)
        # two independent owners with completed items (Alice, Bob), plus Carol's item still unprocessed
        self.alice = make_actor_upload(self.anon, self.store, "alice.jpg")
        self.bob = make_actor_upload(self.anon, self.store, "bob.jpg")
        process_media(self.store, self.alice); process_media(self.store, self.bob)
        self.carol = make_actor_upload(self.anon, self.store, "carol.jpg")   # UPLOADED, not processed

    def tearDown(self):
        supabase_api.WORKER_TOKEN, supabase_api.UPLOADS_PER_HOUR = self._saved

    def assertNoLeak(self, resp, msg="", own_id=None):
        """No signed URLs/paths, and no OTHER item's id. Echoing the id the caller itself supplied is fine."""
        body = resp.text
        for needle in SENSITIVE:
            self.assertNotIn(needle, body, f"{msg}: response leaked '{needle}': {body[:200]}")
        for other in (self.alice, self.bob, self.carol):
            if other != own_id:
                self.assertNotIn(other, body, f"{msg}: leaked another item's id")

    # ---------- M1: anonymous callers, every route ----------
    def test_M1_every_route_enumerated_and_anonymous_gets_nothing_protected(self):
        routes = [(m, r.path) for r in self.app.routes if hasattr(r, "methods") for m in r.methods if m not in ("HEAD", "OPTIONS")]
        api_routes = [(m, p) for m, p in routes if p.startswith(("/api", "/internal"))]
        self.assertGreaterEqual(len(api_routes), 5)
        for method, path in api_routes:
            url = path.replace("{media_id}", "does-not-exist")
            r = self.anon.request(method, url, json={"filename": "x.txt", "size": 1} if method == "POST" and path == "/api/uploads" else None)
            self.assertNotEqual(r.status_code, 500, f"{method} {path}")
            self.assertNoLeak(r, f"{method} {path} anonymous")
        # explicit expectations for the protected ones
        self.assertEqual(self.anon.get("/api/admin/media").status_code, 401)
        self.assertEqual(self.anon.post(f"/internal/process/{self.carol}").status_code, 401)
        self.assertIn(self.anon.get("/api/media").status_code, (404, 405))     # old public listing is gone
        self.assertEqual(self.store.get_record(self.carol)["status"], "UPLOADED")  # anon could not trigger work

    def test_M1_unprocessed_item_exposes_no_urls_or_paths(self):
        j = self.anon.get(f"/api/media/{self.carol}").json()
        self.assertEqual(j["status"], "UPLOADED")
        self.assertNotIn("processed_url", j); self.assertNotIn("thumbnail_url", j)
        for k in j: self.assertNotIn("path", k)

    def test_M1_status_view_hides_internal_storage_paths(self):
        j = self.anon.get(f"/api/media/{self.alice}").json()
        self.assertEqual(j["status"], "COMPLETED")
        self.assertIn("processed_url", j)                       # owner capability: signed URL is expected here
        for hidden in ("original_path", "processed_path", "thumbnail_path"):
            self.assertNotIn(hidden, j)

    # ---------- M2: cross-actor probing ----------
    def test_M2_guessing_neighbour_ids_finds_nothing(self):
        slug, _, suffix = self.alice.rpartition("-")
        self.assertGreaterEqual(len(suffix), 20)                # 80 bits of randomness
        guesses = [f"{slug}-{suffix[:6]}", f"{slug}-" + "0" * 20, f"{slug}-" + suffix[:-1] + ("0" if suffix[-1] != "0" else "1"),
                   "alice", "alice-1", "bob", suffix, self.alice.upper(), self.alice + "x", self.alice[:-1]]
        for g in guesses:
            r = self.anon.get(f"/api/media/{g}")
            self.assertIn(r.status_code, (400, 404), f"guess {g} -> {r.status_code}")
            self.assertNoLeak(r, f"guess {g}")

    def test_M2_ids_are_not_sequential_or_prefix_derivable(self):
        ids = [make_actor_upload(self.anon, self.store, "same.jpg") for _ in range(20)]
        suffixes = {i.rpartition("-")[2] for i in ids}
        self.assertEqual(len(suffixes), 20)
        self.assertEqual(len({s[:6] for s in suffixes}), 20)    # even the first 6 hex chars don't collide

    def test_M2_path_traversal_and_injection_in_ids_and_filenames(self):
        for bad in ("../" + self.bob, "..%2f" + self.bob, self.alice + "%2f..%2f" + self.bob, "%2e%2e/%2e%2e/etc/passwd",
                    self.alice + "'; drop table media_metadata;--", "uploads/" + self.bob, "a" * 500):
            r = self.anon.get("/api/media/" + bad)
            self.assertIn(r.status_code, (400, 404, 405), bad)
            self.assertNoLeak(r, bad)
        j = self.anon.post("/api/uploads", json={"filename": f"../../uploads/{self.bob}/bob.jpg", "size": 5}).json()
        self.assertTrue(j["path"].startswith(f"uploads/{j['media_id']}/"))
        self.assertNotIn("..", j["path"]); self.assertNotIn(self.bob, j["path"])

    def test_M2_complete_on_foreign_id_cannot_change_or_expose_other_items(self):
        r = self.anon.post(f"/api/uploads/{self.bob}/complete")       # idempotent, no state change, no data
        before = self.store.get_record(self.bob)
        self.assertEqual(before["status"], "COMPLETED")
        self.assertNoLeak(r, "complete foreign", own_id=self.bob)
        self.assertEqual(self.store.get_record(self.bob), before)
        self.assertEqual(self.anon.post("/api/uploads/not-real/complete").status_code, 404)

    def test_M2_static_file_route_cannot_read_server_files(self):
        for p in ("/../backend/.env", "/%2e%2e/backend/.env", "/..%2fbackend%2fsupabase_config.py", "/backend/.env",
                  "/../backend/supabase_api.py", "/.env", "/%2e%2e%2f%2e%2e%2fetc/passwd"):
            r = self.anon.get(p)
            self.assertNotIn("SUPABASE_SERVICE_ROLE_KEY", r.text, p); self.assertNotIn("create_client", r.text, p)
            self.assertNotIn("root:", r.text, p)
        self.assertEqual(self.anon.get("/app.js").status_code, 200)
        js = self.anon.get("/app.js").text + self.anon.get("/config.js").text + self.anon.get("/").text
        for secret in ("service_role", "SERVICE_ROLE", "sb_secret", "eyJ"):
            self.assertNotIn(secret, js)

    # ---------- M3: legitimate paths still work ----------
    def test_M3_owner_flow_end_to_end(self):
        mid = make_actor_upload(self.anon, self.store, "mine.jpg")
        self.assertEqual(self.anon.get(f"/api/media/{mid}").json()["status"], "UPLOADED")
        self.assertEqual(process_media(self.store, mid), "COMPLETED")
        j = self.anon.get(f"/api/media/{mid}").json()
        self.assertEqual(j["status"], "COMPLETED")
        self.assertTrue(j["processed_url"].startswith("fake://signed/") and "exp=3600" in j["processed_url"])
        self.assertTrue(j["thumbnail_url"])
        self.assertIn((OUTPUT_BUCKET, f"processed/{mid}.webp"), self.store.objects)

    def test_M3_worker_token_path_and_admin_list_work(self):
        r = self.anon.post(f"/internal/process/{self.carol}", headers={"X-Worker-Token": TOKEN})
        self.assertEqual(r.status_code, 200)
        listing = self.anon.get("/api/admin/media", headers={"X-Worker-Token": TOKEN})
        self.assertEqual(listing.status_code, 200)
        self.assertEqual({x["media_id"] for x in listing.json()}, {self.alice, self.bob, self.carol})

    def test_M3_worker_loop_still_claims_pending_items_once(self):
        mid = make_actor_upload(self.anon, self.store, "again.jpg")
        self.assertEqual(process_media(self.store, mid), "COMPLETED")
        self.assertEqual(process_media(self.store, mid), "SKIPPED")

    # ---------- M4: worker-only actions without the token ----------
    def test_M4_wrong_or_malformed_tokens_rejected(self):
        bad_tokens = ["", " ", TOKEN[:-1], TOKEN + "x", TOKEN.upper(), " " + TOKEN, "null", "undefined", "Bearer " + TOKEN, "0"]
        for t in bad_tokens:
            for method, path in (("GET", "/api/admin/media"), ("POST", f"/internal/process/{self.carol}")):
                r = self.anon.request(method, path, headers={"X-Worker-Token": t} if t else {})
                self.assertEqual(r.status_code, 401, f"{method} {path} token={t!r}")
                self.assertNoLeak(r)
        self.assertEqual(self.store.get_record(self.carol)["status"], "UPLOADED")

    def test_M4_token_in_query_string_or_cookie_or_body_is_not_accepted(self):
        self.assertEqual(self.anon.get(f"/api/admin/media?x_worker_token={TOKEN}").status_code, 401)
        self.assertEqual(self.anon.get(f"/api/admin/media?token={TOKEN}").status_code, 401)
        self.assertEqual(self.anon.get("/api/admin/media", cookies={"x-worker-token": TOKEN}).status_code, 401)
        self.assertEqual(self.anon.post(f"/internal/process/{self.carol}", json={"token": TOKEN}).status_code, 401)

    def test_M4_endpoints_disabled_when_no_token_configured(self):
        supabase_api.WORKER_TOKEN = ""
        for t in ("", "anything"):
            h = {"X-Worker-Token": t} if t else {}
            self.assertEqual(self.anon.get("/api/admin/media", headers=h).status_code, 401)
            self.assertEqual(self.anon.post(f"/internal/process/{self.carol}", headers=h).status_code, 401)

    def test_M4_browser_cross_origin_cannot_use_admin_endpoints(self):
        # A web page on another origin: preflight is not approved, and the endpoints still need the header anyway.
        h = {"Origin": "https://evil.example.com", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "x-worker-token"}
        r = self.anon.options("/api/admin/media", headers=h)
        self.assertIsNone(r.headers.get("access-control-allow-origin"))
        r = self.anon.get("/api/admin/media", headers={"Origin": "https://evil.example.com"})
        self.assertEqual(r.status_code, 401)
        self.assertIsNone(r.headers.get("access-control-allow-origin"))


if __name__ == "__main__":
    unittest.main()
