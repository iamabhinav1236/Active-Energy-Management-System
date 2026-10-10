from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
import sqlite3, json, uuid, random
from datetime import datetime, timezone
from .engine import EnergyEngine

ROOT=Path(__file__).resolve().parent
DB=Path(__file__).resolve().parent.parent/'data'/'energy.db'
app=FastAPI(title='Active Energy | Multi-Agent Smart Energy',version='1.0.0',description='Negotiation-based smart energy management demo API')
engine=EnergyEngine()
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

def conn():
    DB.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.execute('''CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, created_at TEXT, status TEXT, plan_json TEXT, decision_note TEXT DEFAULT '')''')
    c.execute('''CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id TEXT, outcome TEXT, rating INTEGER, note TEXT, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS telemetry (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, load_kw REAL, solar_kw REAL, grid_kw REAL, battery_soc INTEGER, cost_per_hour REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS machines (id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, power_kw REAL NOT NULL, status TEXT NOT NULL DEFAULT 'off', priority TEXT NOT NULL DEFAULT 'normal', created_at TEXT NOT NULL)''')
    c.commit(); return c

class SettingsUpdate(BaseModel):
    site_name: str|None=None; site_type: str|None=None
    tariff_peak: float|None=Field(None,ge=0,le=1000); tariff_offpeak: float|None=Field(None,ge=0,le=1000)
    base_load_kw: float|None=Field(None,gt=0,le=10000); solar_kw: float|None=Field(None,ge=0,le=10000)
    battery_capacity_kwh: float|None=Field(None,gt=0,le=100000); battery_soc: int|None=Field(None,ge=0,le=100)
    comfort_min: float|None=Field(None,ge=10,le=35); comfort_max: float|None=Field(None,ge=10,le=35)
    occupancy: str|None=None; mode: str|None=None; budget_inr: float|None=Field(None,ge=0,le=10000000)
class Decision(BaseModel):
    action: str=Field(pattern='^(approve|reject|edit)$'); note: str=''; edited_actions: list[dict]|None=None
class Feedback(BaseModel):
    outcome: str=Field(pattern='^(better|same|worse)$'); rating: int=Field(ge=1,le=5); note: str=''

@app.on_event('startup')
def startup():
    c=conn()
    row=c.execute("SELECT value FROM app_state WHERE key='settings'").fetchone()
    if row:
        try: engine.settings.update(json.loads(row['value']))
        except (ValueError, TypeError): pass
    row=c.execute("SELECT value FROM app_state WHERE key='feedback_bias'").fetchone()
    if row:
        try: engine.feedback_bias=float(row['value'])
        except (ValueError, TypeError): pass
    c.close()
@app.get('/',response_class=HTMLResponse)
def home(): return (ROOT/'static'/'index.html').read_text(encoding='utf-8')
@app.get('/api/health')
def health(): return {'status':'ok','service':'Active Energy API','version':'1.0.0'}
@app.get('/api/dashboard')
def dashboard(): return engine.dashboard()
@app.get('/api/settings')
def get_settings(): return engine.settings
@app.put('/api/settings')
def update_settings(payload:SettingsUpdate):
    changes=payload.model_dump(exclude_none=True)
    if 'comfort_min' in changes or 'comfort_max' in changes:
        low=changes.get('comfort_min',engine.settings['comfort_min']); high=changes.get('comfort_max',engine.settings['comfort_max'])
        if low>=high: raise HTTPException(400,'Comfort minimum must be lower than comfort maximum.')
    if 'mode' in changes and changes['mode'] not in ('recommendation','assisted'): raise HTTPException(400,'Mode must be recommendation or assisted.')
    engine.settings.update(changes)
    c=conn(); c.execute("INSERT INTO app_state(key,value) VALUES('settings',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(engine.settings),)); c.commit(); c.close()
    return {'settings':engine.settings,'dashboard':engine.dashboard()}
@app.get('/api/agents')
def agents(): return engine.agents_status()
@app.post('/api/plan')
def create_plan():
    plan=engine.plan(); plan['plan_id']=str(uuid.uuid4())[:8].upper(); plan['created_at']=datetime.now(timezone.utc).isoformat()
    c=conn(); c.execute('INSERT INTO plans(id,created_at,status,plan_json) VALUES(?,?,?,?)',(plan['plan_id'],plan['created_at'],plan['status'],json.dumps(plan))); c.commit(); c.close(); return plan
@app.get('/api/plans/{plan_id}')
def get_plan(plan_id:str):
    c=conn(); row=c.execute('SELECT plan_json FROM plans WHERE id=?',(plan_id,)).fetchone(); c.close()
    if not row: raise HTTPException(404,'Plan not found')
    return json.loads(row['plan_json'])

@app.get('/api/plans')
def plans():
    c=conn(); rows=c.execute('SELECT id,created_at,status,plan_json,decision_note FROM plans ORDER BY created_at DESC LIMIT 50').fetchall(); c.close()
    out=[]
    for r in rows:
        p=json.loads(r['plan_json']); out.append({'plan_id':r['id'],'created_at':r['created_at'],'status':r['status'],'savings_per_hour_inr':p['estimated']['savings_per_hour_inr'],'action_count':len(p['actions']),'decision_note':r['decision_note']})
    return out
@app.post('/api/plans/{plan_id}/decision')
def decision(plan_id:str,payload:Decision):
    c=conn(); row=c.execute('SELECT * FROM plans WHERE id=?',(plan_id,)).fetchone()
    if not row: c.close(); raise HTTPException(404,'Plan not found')
    p=json.loads(row['plan_json'])
    if payload.action=='approve': status='approved'
    elif payload.action=='reject': status='rejected'
    else:
        if payload.edited_actions is None: c.close(); raise HTTPException(400,'Provide edited_actions when action=edit')
        # Only existing actions may be changed, and guardrails cannot be removed.
        original={a['id']:a for a in p['actions']}; edited=[]
        for a in payload.edited_actions:
            if a.get('id') not in original: c.close(); raise HTTPException(400,'Unknown action in edited plan')
            if original[a['id']]['status']=='guardrail' and a.get('enabled',True) is False: c.close(); raise HTTPException(400,'Safety guardrails cannot be disabled')
            original[a['id']]['enabled']=bool(a.get('enabled',True)); edited.append(original[a['id']])
        p['actions']=edited; p['status']='edited_pending_approval'; status='edited_pending_approval'
    p['status']=status; p['decision_note']=payload.note
    c.execute('UPDATE plans SET status=?,plan_json=?,decision_note=? WHERE id=?',(status,json.dumps(p),payload.note,plan_id)); c.commit(); c.close()
    return {'plan_id':plan_id,'status':status,'message':{'approved':'Plan approved. This demo records approval but does not control physical devices.','rejected':'Plan rejected and saved.','edited_pending_approval':'Edits saved. Review and approve the updated plan separately.'}[status]}
@app.post('/api/plans/{plan_id}/feedback')
def feedback(plan_id:str,payload:Feedback):
    global engine
    c=conn(); row=c.execute('SELECT id FROM plans WHERE id=?',(plan_id,)).fetchone()
    if not row: c.close(); raise HTTPException(404,'Plan not found')
    c.execute('INSERT INTO feedback(plan_id,outcome,rating,note,created_at) VALUES(?,?,?,?,?)',(plan_id,payload.outcome,payload.rating,payload.note,datetime.now(timezone.utc).isoformat())); c.commit(); c.close()
    # Lightweight online adaptation: positive feedback gently favors savings; negative feedback increases caution.
    engine.feedback_bias=max(-0.2,min(0.2,engine.feedback_bias + (0.02 if payload.outcome=='better' else -0.03 if payload.outcome=='worse' else 0)))
    c=conn(); c.execute("INSERT INTO app_state(key,value) VALUES('feedback_bias',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(engine.feedback_bias),)); c.commit(); c.close()
    return {'saved':True,'learning_state':round(engine.feedback_bias,2),'message':'Feedback saved and learning preference updated.'}
@app.get('/api/feedback')
def feedback_history():
    c=conn(); rows=c.execute('SELECT * FROM feedback ORDER BY id DESC LIMIT 50').fetchall(); c.close(); return [dict(r) for r in rows]
@app.get('/api/telemetry')
def telemetry_history():
    c=conn(); rows=c.execute('SELECT * FROM telemetry ORDER BY id DESC LIMIT 24').fetchall(); c.close()
    return [dict(r) for r in reversed(rows)]

@app.post('/api/telemetry/simulate')
def simulate_telemetry():
    # Deterministic-safe bounds, with small variation to make dashboard refreshes meaningful.
    s=engine.settings
    # Vary readings around configured capacity; never ratchet the user's configured load/solar capacity.
    load=round(max(0.1,s['base_load_kw']*random.uniform(0.92,1.08)+0.9),2)
    solar=round(max(0,min(s['solar_kw'],s['solar_kw']*random.uniform(0.35,0.95))),2)
    s['battery_soc']=int(max(20,min(95,s['battery_soc']+random.choice([-4,-2,1,2,3]))))
    grid=round(max(0,load-solar),2); cost=round(grid*s['tariff_peak'],2)
    engine.current_reading={'load_kw':load,'solar_kw':solar,'grid_kw':grid,'cost_per_hour':cost,'carbon_kg_hour':round(grid*s['carbon_factor'],2),'solar_share_pct':round(min(100,solar/max(load,0.1)*100))}
    c=conn(); c.execute("INSERT INTO app_state(key,value) VALUES('settings',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(s),))
    d=engine.dashboard(); c.execute('INSERT INTO telemetry(created_at,load_kw,solar_kw,grid_kw,battery_soc,cost_per_hour) VALUES(?,?,?,?,?,?)',(datetime.now(timezone.utc).isoformat(),d['load_kw'],d['solar_kw'],d['grid_kw'],d['battery_soc'],d['cost_per_hour']))
    c.commit(); c.close(); return {'settings':s,'dashboard':d,'telemetry':telemetry_history()}

@app.post('/api/reset')
def reset():
    engine.settings=__import__('app.engine',fromlist=['DEFAULTS']).DEFAULTS.copy(); engine.feedback_bias=0.0; engine.current_reading=None
    c=conn(); c.execute("INSERT INTO app_state(key,value) VALUES('settings',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(engine.settings),)); c.execute("INSERT INTO app_state(key,value) VALUES('feedback_bias','0') ON CONFLICT(key) DO UPDATE SET value='0'"); c.commit(); c.close()
    return {'settings':engine.settings,'dashboard':engine.dashboard()}


class MachineCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    kind: str = Field(min_length=2, max_length=40)
    power_kw: float = Field(gt=0, le=10000)
    priority: str = Field(default='normal', pattern='^(low|normal|high|critical)$')
    status: str = Field(default='off', pattern='^(on|off)$')

class MachineUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=80)
    kind: str | None = Field(None, min_length=2, max_length=40)
    power_kw: float | None = Field(None, gt=0, le=10000)
    priority: str | None = Field(None, pattern='^(low|normal|high|critical)$')
    status: str | None = Field(None, pattern='^(on|off)$')

@app.get('/api/machines')
def list_machines():
    c=conn()
    rows=c.execute('SELECT * FROM machines ORDER BY created_at DESC').fetchall()
    if not rows:
        seed=[('Air conditioner','HVAC',1.8,'on','high'),('Water heater','Heating',2.0,'off','normal'),('EV charger','EV charging',7.2,'off','low'),('Refrigerator','Appliance',0.25,'on','critical'),('Living room lights','Lighting',0.18,'on','normal'),('Washing machine','Appliance',0.8,'off','low'),('Induction cooktop','Appliance',2.2,'off','high'),('Office HVAC','HVAC',3.5,'off','high'),('Solar inverter','Solar',0.12,'on','critical'),('Water pump','Industrial',0.75,'off','normal')]
        for n,k,p,st,pr in seed:
            c.execute('INSERT INTO machines VALUES(?,?,?,?,?,?,?)',(uuid.uuid4().hex[:10],n,k,p,st,pr,datetime.now(timezone.utc).isoformat()))
        c.commit(); rows=c.execute('SELECT * FROM machines ORDER BY created_at DESC').fetchall()
    c.close(); return [dict(r) for r in rows]

@app.post('/api/machines')
def add_machine(payload: MachineCreate):
    c=conn(); mid=uuid.uuid4().hex[:10]
    c.execute('INSERT INTO machines VALUES(?,?,?,?,?,?,?)',(mid,payload.name,payload.kind,payload.power_kw,payload.status,payload.priority,datetime.now(timezone.utc).isoformat()))
    c.commit(); row=dict(c.execute('SELECT * FROM machines WHERE id=?',(mid,)).fetchone()); c.close(); return row

@app.patch('/api/machines/{machine_id}')
def update_machine(machine_id: str, payload: MachineUpdate | None = None):
    c=conn(); row=c.execute('SELECT * FROM machines WHERE id=?',(machine_id,)).fetchone()
    if not row: c.close(); raise HTTPException(404,'Machine not found')
    changes=payload.model_dump(exclude_none=True) if payload else {}
    if not changes:
        changes={'status':'off' if row['status']=='on' else 'on'}
    assignments=', '.join(f'{key}=?' for key in changes)
    c.execute(f'UPDATE machines SET {assignments} WHERE id=?',(*changes.values(),machine_id)); c.commit()
    result=dict(c.execute('SELECT * FROM machines WHERE id=?',(machine_id,)).fetchone()); c.close(); return result

@app.post('/api/machines/bulk')
def bulk_machines(payload: dict):
    ids=payload.get('ids',[]); action=payload.get('action')
    if not isinstance(ids,list) or not ids or len(ids)>200: raise HTTPException(400,'Select between 1 and 200 machines.')
    if action not in ('on','off','delete'): raise HTTPException(400,'Action must be on, off, or delete.')
    c=conn(); placeholders=','.join('?' for _ in ids)
    if action=='delete':
        cur=c.execute(f'DELETE FROM machines WHERE id IN ({placeholders})',ids); changed=cur.rowcount
    else:
        cur=c.execute(f"UPDATE machines SET status=? WHERE id IN ({placeholders})",[action,*ids]); changed=cur.rowcount
    c.commit(); c.close()
    return {'action':action,'changed':changed,'message':f'{changed} machine(s) {"deleted" if action=="delete" else "switched "+action}.'}

@app.get('/api/machines/summary')
def machine_summary():
    c=conn(); rows=c.execute('SELECT status, COUNT(*) AS count, COALESCE(SUM(power_kw),0) AS kw FROM machines GROUP BY status').fetchall(); c.close()
    out={'total':0,'on':0,'off':0,'on_kw':0.0,'rated_kw':0.0}
    for r in rows:
        out[r['status']]=r['count']; out['total']+=r['count']; out['rated_kw']+=r['kw']
        if r['status']=='on': out['on_kw']=round(r['kw'],2)
    out['rated_kw']=round(out['rated_kw'],2); return out

@app.delete('/api/machines/{machine_id}')
def delete_machine(machine_id: str):
    c=conn(); cur=c.execute('DELETE FROM machines WHERE id=?',(machine_id,)); c.commit(); c.close()
    if not cur.rowcount: raise HTTPException(404,'Machine not found')
    return {'deleted':machine_id}
