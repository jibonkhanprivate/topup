# TOPUPERS

Flask gaming top-up storefront with JSON-based users/orders, admin dashboard, and manual payment verification.

## Run

```bash
pip install -r requirements.txt
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export ADMIN_EMAIL='support@topupers.com'
export ADMIN_PASSWORD='CHANGE_THIS_TO_A_STRONG_PASSWORD'
python app.py
```

Open http://127.0.0.1:5000/ and http://127.0.0.1:5000/admin .

For production use `gunicorn -w 1 app:app` with persistent `DATA_DIR`, `HTTPS_ONLY=1`, HTTPS reverse proxy and a stable `SECRET_KEY`. A single worker is required for this JSON implementation; multiple processes/servers require a transactional database. `data/users.json` and `data/orders.json` are created automatically. Keep `data/` outside public web roots and back it up.

If ADMIN_PASSWORD is not set, the initial bootstrap password is `admin@1234` as requested. Change it before deployment. Changing ADMIN_PASSWORD later does not change an existing account; reset the stored password hash through a trusted maintenance procedure.

## Payment and delivery

bKash, Nagad, Rocket and Upay orders can be created with manual transaction ID submission. An administrator must independently verify each transfer with the wallet provider before marking it verified and delivered. Bangla QR and Stripe are not enabled until their server-side integrations are configured. Google OAuth also requires provider credentials. No automatic game-credit delivery is implemented.

Prices are currently defined in `catalog.json` and must be reviewed before accepting orders. This is a small single-instance starter implementation: add CSRF protection, rate limiting, email verification, password reset, audit logging and a proper database before large-scale production use.
