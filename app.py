import os,json,secrets,threading,tempfile
from pathlib import Path
from datetime import datetime,timezone
from functools import wraps
from flask import Flask,render_template,request,jsonify,session,redirect
from werkzeug.security import generate_password_hash,check_password_hash

app=Flask(__name__)
app.config.update(SECRET_KEY=os.environ.get('SECRET_KEY',secrets.token_hex(32)),SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=os.environ.get('HTTPS_ONLY')=='1',MAX_CONTENT_LENGTH=16384)
BASE=Path(__file__).resolve().parent
DATA=Path(os.environ.get('DATA_DIR',str(BASE/'data')));DATA.mkdir(parents=True,exist_ok=True)
LOCK=threading.RLock()
CATALOG={x['id']:x for x in json.loads((BASE/'catalog.json').read_text())}
METHODS={'bKash','Nagad','Rocket','Upay','Bangla QR','Stripe'}
STATUSES={'Pending Payment','Payment Submitted','Processing','Delivered','Cancelled'}
PAYMENT_STATUSES={'Unpaid','Submitted','Verified','Rejected'}
def now():return datetime.now(timezone.utc).isoformat()
def read(name):
    p=DATA/(name+'.json')
    if not p.exists():return []
    return json.loads(p.read_text(encoding='utf-8'))
def write(name,data):
    fd,path=tempfile.mkstemp(dir=DATA,prefix='.tmp-')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(path,DATA/(name+'.json'))
    finally:
        if os.path.exists(path):os.unlink(path)
def error(message,code=400):return jsonify(error=message),code
def safe_user(u):return {k:u[k] for k in ('id','name','email','is_admin')}
def user():return next((u for u in read('users') if u['id']==session.get('uid')),None)
def login_required(fn):
    @wraps(fn)
    def wrap(*a,**kw):
        if not user():return error('Please sign in',401)
        return fn(*a,**kw)
    return wrap
def admin_required(fn):
    @wraps(fn)
    def wrap(*a,**kw):
        u=user()
        if not u or not u['is_admin']:return error('Administrator access required',403)
        return fn(*a,**kw)
    return wrap
with LOCK:
    for name in ('users','orders'):
        if not (DATA/(name+'.json')).exists():write(name,[])
    users=read('users');email=os.environ.get('ADMIN_EMAIL','support@topupers.com').lower();password=os.environ.get('ADMIN_PASSWORD','admin@1234')
    if not any(u['email']==email for u in users):
        users.append(dict(id=secrets.token_hex(12),name='TOPUPERS Admin',email=email,password_hash=generate_password_hash(password),is_admin=True,created_at=now()));write('users',users)
@app.after_request
def headers(r):
    r.headers['X-Content-Type-Options']='nosniff';r.headers['X-Frame-Options']='DENY';r.headers['Referrer-Policy']='strict-origin-when-cross-origin';return r
@app.route('/')
def home():return render_template('index.html')
@app.route('/api/me')
def me():
    u=user();return jsonify(user=safe_user(u) if u else None)
@app.post('/api/signup')
def signup():
    d=request.get_json(silent=True) or {};name=str(d.get('name','')).strip()[:100];email=str(d.get('email','')).strip().lower();pw=str(d.get('password',''))
    if len(name)<2 or '@' not in email or len(email)>254 or len(pw)<8:return error('Provide name, valid email and password of at least 8 characters')
    with LOCK:
        users=read('users')
        if any(u['email']==email for u in users):return error('Email already registered',409)
        u=dict(id=secrets.token_hex(12),name=name,email=email,password_hash=generate_password_hash(pw),is_admin=False,created_at=now());users.append(u);write('users',users)
    session.clear();session['uid']=u['id'];return jsonify(user=safe_user(u)),201
@app.post('/api/login')
def login():
    d=request.get_json(silent=True) or {};email=str(d.get('email','')).strip().lower();pw=str(d.get('password',''))
    u=next((u for u in read('users') if u['email']==email),None)
    if not u or not check_password_hash(u['password_hash'],pw):return error('Invalid email or password',401)
    session.clear();session['uid']=u['id'];return jsonify(user=safe_user(u))
@app.post('/api/logout')
def logout():session.clear();return jsonify(ok=True)
@app.post('/api/orders')
@login_required
def create_order():
    d=request.get_json(silent=True) or {};g=CATALOG.get(d.get('game_id'));idx=d.get('package_index');method=d.get('payment');recipient=str(d.get('recipient','')).strip();server=str(d.get('server','')).strip()
    if not g or type(idx)!=int or idx<0 or idx>=len(g['pk']) or method not in METHODS:return error('Invalid product, package or payment method')
    if not 3<=len(recipient)<=120 or len(server)>40:return error('Invalid player ID or delivery address')
    if method in {'Stripe','Bangla QR'}:return error('This payment method is not configured yet',422)
    qty,price=g['pk'][idx];u=user();o=dict(id='TP-'+secrets.token_hex(5).upper(),user_id=u['id'],customer=u['name'],email=u['email'],game=g['name'],game_id=g['id'],quantity=qty,unit=g['unit'],price=price,recipient=recipient,server=server,payment=method,transaction_id='',payment_status='Unpaid',status='Pending Payment',delivery_note='',created_at=now(),updated_at=now())
    with LOCK:
        orders=read('orders');orders.append(o);write('orders',orders)
    return jsonify(o),201
@app.get('/api/orders')
@login_required
def my_orders():return jsonify(orders=sorted([o for o in read('orders') if o['user_id']==user()['id']],key=lambda o:o['created_at'],reverse=True))
@app.post('/api/orders/<oid>/payment')
@login_required
def payment(oid):
    d=request.get_json(silent=True) or {};trx=str(d.get('transaction_id','')).strip()
    if not 5<=len(trx)<=100:return error('Enter a valid transaction ID')
    with LOCK:
        orders=read('orders');o=next((o for o in orders if o['id']==oid and o['user_id']==user()['id']),None)
        if not o:return error('Order not found',404)
        if o['payment_status']=='Verified' or o['status']=='Delivered':return error('Order payment already verified',409)
        o.update(transaction_id=trx,payment_status='Submitted',status='Payment Submitted',updated_at=now());write('orders',orders)
    return jsonify(ok=True)
@app.get('/api/admin/orders')
@admin_required
def admin_orders():
    orders=read('orders');return jsonify(orders=sorted(orders,key=lambda o:o['created_at'],reverse=True),users=len(read('users')),total_orders=len(orders),revenue=sum(o['price'] for o in orders if o['payment_status']=='Verified'))
@app.patch('/api/admin/orders/<oid>')
@admin_required
def update_order(oid):
    d=request.get_json(silent=True) or {};status=d.get('status');payment_status=d.get('payment_status');note=str(d.get('delivery_note',''))[:2000]
    if status not in STATUSES or payment_status not in PAYMENT_STATUSES:return error('Invalid order status')
    if status=='Delivered' and payment_status!='Verified':return error('Verify payment before marking delivered')
    with LOCK:
        orders=read('orders');o=next((x for x in orders if x['id']==oid),None)
        if not o:return error('Order not found',404)
        o.update(status=status,payment_status=payment_status,delivery_note=note,updated_at=now());write('orders',orders)
    return jsonify(ok=True)
@app.route('/admin')
def admin_page():
    u=user()
    if not u:return redirect('/?login=1')
    if not u['is_admin']:return 'Forbidden',403
    return render_template('admin.html')
@app.route('/auth/google')
def google():return error('Google OAuth requires client credentials and provider configuration',501)
if __name__=='__main__':app.run(debug=False,port=int(os.environ.get('PORT',5000)))
