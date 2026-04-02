from __future__ import annotations

import time

from fastapi.testclient import TestClient

from main import app


def _assert(condition: bool, message: str) -> None:
	"""简单的断言函数，失败时抛出 AssertionError，并带上错误信息。"""
	if not condition:
		raise AssertionError(message)


def run_auth_flow_test() -> None:
	client = TestClient(app)
	email = f"test_{int(time.time())}@example.com"
	password = "12345678"

	register_resp = client.post(
		"/auth/register",
		json={"username": "tester", "email": email, "password": password},
	)
	_assert(register_resp.status_code == 201, f"register failed: {register_resp.text}")
	register_data = register_resp.json()
	_assert(register_data["email"] == email, "register email mismatch")

	login_resp = client.post(
		"/auth/login",
		json={"email": email, "password": password},
	)
	_assert(login_resp.status_code == 200, f"login failed: {login_resp.text}")
	_assert("access_token" in login_resp.json(), "missing access_token in login response")
	_assert("refresh_token" in client.cookies, "refresh cookie not set after login")

	refresh_resp = client.post("/auth/refresh")
	_assert(refresh_resp.status_code == 200, f"refresh failed: {refresh_resp.text}")
	_assert("access_token" in refresh_resp.json(), "missing access_token in refresh response")

	logout_resp = client.post("/auth/logout")
	_assert(logout_resp.status_code == 204, f"logout failed: {logout_resp.text}")

	refresh_after_logout = client.post("/auth/refresh")
	_assert(refresh_after_logout.status_code == 401, "refresh should fail after logout")

	print("PASS: auth flow test passed")
	print(f"INFO: tested email = {email}")


if __name__ == "__main__":
	run_auth_flow_test()
