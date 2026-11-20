"""Authentication, workspace management, roles and workspace isolation."""

from __future__ import annotations

from tests.conftest import PASSWORD, Account, add_feedback, add_member, register


def test_register_login_me(client):
    acct = register(client, "a@example.com", "My Co")
    me = acct.get("/api/v1/auth/me").json()
    assert me["email"] == "a@example.com"
    assert me["workspaces"][0]["name"] == "My Co"
    assert me["workspaces"][0]["role"] == "owner"
    r = client.post("/api/v1/auth/login", json={"email": "A@example.com", "password": PASSWORD})
    assert r.status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "wrong-password-1"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong-password-1"}).status_code == 401


def test_register_validation(client):
    r = client.post("/api/v1/auth/register", json={"email": "x@example.com", "password": "short", "full_name": "X"})
    assert r.status_code == 422
    register(client, "dup@example.com")
    r = client.post("/api/v1/auth/register", json={"email": "dup@example.com", "password": PASSWORD, "full_name": "X"})
    assert r.status_code == 409
    r = client.post("/api/v1/auth/register", json={"email": "not-an-email", "password": PASSWORD, "full_name": "X"})
    assert r.status_code == 422
    assert PASSWORD not in r.text  # submitted values are never echoed


def test_unauthenticated_and_bad_token(client):
    assert client.get("/api/v1/feedback").status_code == 401
    assert client.get("/api/v1/feedback", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401


def test_refresh_rotation_and_reuse_detection(client):
    acct = register(client)
    old = acct.tokens["refresh_token"]
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": old})
    assert r.status_code == 200
    new = r.json()["refresh_token"]
    # Reusing the rotated token revokes the family, including the new token.
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": old}).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": new}).status_code == 401


def test_logout_revokes_refresh(client):
    acct = register(client)
    assert client.post("/api/v1/auth/logout", json={"refresh_token": acct.tokens["refresh_token"]}).status_code == 204
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": acct.tokens["refresh_token"]}).status_code == 401


def test_change_password_invalidates_tokens(client):
    acct = register(client)
    r = acct.post("/api/v1/auth/change-password", json={"current_password": PASSWORD, "new_password": "An0ther-good-pass"})
    assert r.status_code == 204
    assert acct.get("/api/v1/auth/me").status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": acct.email, "password": "An0ther-good-pass"}).status_code == 200


def test_workspace_create_update_switch(client, alice):
    r = alice.post("/api/v1/workspaces", json={"name": "Second", "timezone": "Europe/London"})
    assert r.status_code == 201
    second = r.json()["id"]
    # With two workspaces the header is required.
    no_header = Account(client, alice.email, alice.tokens)
    assert no_header.get("/api/v1/feedback").status_code == 400
    add_feedback(alice, "Feedback in first workspace")
    alice2 = Account(client, alice.email, alice.tokens, second)
    assert alice2.get("/api/v1/feedback").json()["total"] == 0
    assert alice.get("/api/v1/feedback").json()["total"] == 1
    assert alice2.patch("/api/v1/workspace", json={"timezone": "Not/AZone"}).status_code == 422
    assert alice2.patch("/api/v1/workspace", json={"name": "Renamed"}).json()["name"] == "Renamed"
    assert len(alice.get("/api/v1/workspaces").json()) == 2


def test_workspace_isolation_by_id(client, alice, bob):
    fb = add_feedback(alice, "Alice's private feedback about delivery")
    # Bob cannot read, edit or delete Alice's record by changing the ID.
    assert bob.get(f"/api/v1/feedback/{fb['id']}").status_code == 404
    assert bob.patch(f"/api/v1/feedback/{fb['id']}", json={"text": "hacked"}).status_code == 404
    assert bob.delete(f"/api/v1/feedback/{fb['id']}").status_code == 404
    assert bob.post(f"/api/v1/feedback/{fb['id']}/notes", json={"body": "x"}).status_code == 404
    assert bob.post(f"/api/v1/feedback/{fb['id']}/sentiment", json={"label": "positive"}).status_code == 404
    # Bob cannot select Alice's workspace via the header.
    forged = Account(client, bob.email, bob.tokens, alice.workspace_id)
    assert forged.get("/api/v1/feedback").status_code == 404
    assert forged.get("/api/v1/analytics/overview").status_code == 404
    # Bulk actions silently skip foreign IDs.
    r = bob.post("/api/v1/feedback/bulk", json={"ids": [fb["id"]], "action": "archive"})
    assert r.json() == {"updated": 0, "not_found": 1}
    assert bob.get("/api/v1/feedback").json()["total"] == 0
    assert bob.get("/api/v1/analytics/overview").json()["distribution"]["total"] == 0
    assert alice.get(f"/api/v1/feedback/{fb['id']}").json()["is_archived"] is False


def test_foreign_product_reference_rejected(alice, bob):
    p = alice.post("/api/v1/products", json={"name": "Alice Widget"}).json()
    r = bob.post("/api/v1/feedback", json={"text": "x y z", "product_id": p["id"]})
    assert r.status_code == 404


def test_roles_enforced_on_backend(client, alice):
    viewer = add_member(alice, "viewer@example.com", "viewer")
    analyst = add_member(alice, "analyst@example.com", "analyst")
    admin = add_member(alice, "admin@example.com", "admin")
    fb = add_feedback(alice, "Great service overall")
    # Viewer: read only
    assert viewer.get("/api/v1/feedback").status_code == 200
    assert viewer.post("/api/v1/feedback", json={"text": "viewer write"}).status_code == 403
    assert viewer.post("/api/v1/topics", json={"name": "X"}).status_code == 403
    assert viewer.post("/api/v1/reports", json={"format": "csv"}).status_code == 403
    assert viewer.post(f"/api/v1/feedback/{fb['id']}/sentiment", json={"label": "negative"}).status_code == 403
    # Analyst: write but not delete / manage members
    assert analyst.post("/api/v1/feedback", json={"text": "analyst write"}).status_code == 201
    assert analyst.delete(f"/api/v1/feedback/{fb['id']}").status_code == 403
    assert analyst.post("/api/v1/workspace/invitations", json={"email": "z@example.com"}).status_code == 403
    assert analyst.post("/api/v1/integrations", json={"provider": "rest_api", "name": "x"}).status_code == 403
    assert analyst.put("/api/v1/workspace/ai-settings", json={"provider": "none"}).status_code == 403
    # Admin: can delete and manage, but cannot delete the workspace or touch owners
    assert admin.delete(f"/api/v1/feedback/{fb['id']}").status_code == 204
    assert admin.post("/api/v1/workspace/delete", json={"confirm_name": "Alice Co"}).status_code == 403
    members = alice.get("/api/v1/workspace/members").json()
    owner_mid = next(m["id"] for m in members if m["role"] == "owner")
    assert admin.patch(f"/api/v1/workspace/members/{owner_mid}", json={"role": "viewer"}).status_code == 403
    assert admin.post("/api/v1/workspace/invitations", json={"email": "adm2@example.com", "role": "admin"}).status_code == 403


def test_last_owner_protection_and_delete(client, alice):
    members = alice.get("/api/v1/workspace/members").json()
    mid = members[0]["id"]
    assert alice.patch(f"/api/v1/workspace/members/{mid}", json={"role": "viewer"}).status_code == 400
    assert alice.delete(f"/api/v1/workspace/members/{mid}").status_code == 400
    assert alice.post("/api/v1/workspace/delete", json={"confirm_name": "wrong"}).status_code == 400
    assert alice.post("/api/v1/workspace/delete", json={"confirm_name": "Alice Co"}).status_code == 204
    assert alice.get("/api/v1/workspaces").json() == []


def test_invitation_flow_existing_user(client, alice, bob):
    r = alice.post("/api/v1/workspace/invitations", json={"email": bob.email, "role": "analyst"})
    token = r.json()["token"]
    assert client.get(f"/api/v1/invitations/{token}").json()["workspace_name"] == "Alice Co"
    carol = register(client, "carol@example.com")
    assert carol.post("/api/v1/invitations/accept", json={"token": token}).status_code == 403  # wrong email
    r = bob.post("/api/v1/invitations/accept", json={"token": token})
    assert r.status_code == 200
    assert len(bob.get("/api/v1/workspaces").json()) == 2
    assert bob.post("/api/v1/invitations/accept", json={"token": token}).status_code == 400  # single use


def test_security_headers_and_health(client):
    r = client.get("/health")
    assert r.json()["status"] == "ok"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert client.get("/health/ready").json()["database"] == "ok"


def test_cors_only_allows_configured_origin(client):
    ok = client.options("/api/v1/auth/login", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options("/api/v1/auth/login", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers
