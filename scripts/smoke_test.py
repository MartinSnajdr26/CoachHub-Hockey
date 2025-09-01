from coach.app import app, db


def check_security_headers(resp):
    required = [
        'Content-Security-Policy',
        'X-Frame-Options',
        'X-Content-Type-Options',
        'Referrer-Policy',
        'Permissions-Policy',
        'Strict-Transport-Security',
    ]
    missing = [h for h in required if h not in resp.headers]
    return missing


def main():
    results = []
    with app.app_context():
        db.create_all()
    client = app.test_client()

    # GET /auth
    r = client.get('/auth')
    results.append(('GET /auth status', r.status_code == 200))
    missing = check_security_headers(r)
    results.append(('security headers on /auth', not missing))

    # Register new user + team
    email = 'smoke_test@example.com'
    data = {
        'email': email,
        'password': 'TestPassw0rd!',
        'first_name': 'Smoke',
        'last_name': 'Test',
        'team_mode': 'create',
        'team_name': 'Smoke Team',
        'role': 'coach',
    }
    r = client.post('/register', data=data, follow_redirects=False)
    results.append(('POST /register redirect', r.status_code in (302, 303)))

    # After login, should redirect to /awaiting (email not confirmed)
    r2 = client.get('/awaiting')
    results.append(('GET /awaiting status', r2.status_code == 200))
    missing2 = check_security_headers(r2)
    results.append(('security headers on /awaiting', not missing2))

    # Password reset request (generic response)
    r3 = client.post('/password/forgot', data={'email': email}, follow_redirects=False)
    results.append(('POST /password/forgot redirect', r3.status_code in (302, 303)))

    # Print summary
    ok = all(flag for (_name, flag) in results)
    for name, flag in results:
        print(f"[{'OK' if flag else 'FAIL'}] {name}")
    print('OVERALL:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())

