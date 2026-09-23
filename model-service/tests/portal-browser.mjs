// Isolated databases and processes; no supplier keys and no worker/model requests.
import { chromium, expect } from '@playwright/test'
import { spawn, spawnSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..')
const python=path.resolve(root,'../backend/.venv/bin/python')
const run=randomUUID()
const dbPath=path.join(root,'.runtime',`portal-browser-${run}.db`)
const minimal={PATH:process.env.PATH,HOME:process.env.HOME,TMPDIR:process.env.TMPDIR}
const env={...minimal,DATABASE_URL:'sqlite+aiosqlite:///'+dbPath,ADMIN_JWT_SECRET:randomUUID()+randomUUID(),ADMIN_USERNAME:'admin',ADMIN_PASSWORD:randomUUID()}
function command(args,extra={}){const r=spawnSync(python,args,{cwd:root,env:{...env,...extra},encoding:'utf8'});if(r.status!==0)throw Error(r.stderr);return r.stdout}
command(['-m','alembic','upgrade','head'])
command(['scripts/seed.py'],{PYTHONPATH:path.join(root,'public-api')})
command(['-c', `import asyncio
from gateway.db import Model, ModelRoute, Session, now
from sqlalchemy import select
async def run():
 async with Session.begin() as db:
  for route in (await db.scalars(select(ModelRoute))).all(): route.deleted_at=now()
  model=await db.get(Model,'gpt-5.6-sol')
  model.enabled=True
  model.capabilities={"unified_catalog":True,"catalog_selected":True}
  db.add(ModelRoute(id='quote-browser-route',model_id='gpt-5.6-sol',supplier='yseeai',channel='yseeai-llm',provider_model='gpt-5.6-sol',protocol='chat',enabled=False,priority=10,concurrency=1,verification='pending',capabilities={},pricing={'estimate_rules':[]}))
asyncio.run(run())`],{PYTHONPATH:path.join(root,'public-api')})
const processes=[]
function start(cmd,args,cwd,vars){const fd=fs.openSync(path.join(root,'.runtime','portal-browser-process.log'),'a');const p=spawn(cmd,args,{cwd,env:vars,stdio:['ignore',fd,fd],detached:true});processes.push(p);fs.closeSync(fd)}
async function ready(url){for(let i=0;i<80;i++){try{if((await fetch(url)).ok)return}catch{}await new Promise(r=>setTimeout(r,250))}throw Error('Service not ready: '+url)}
let browser
try {
 start(python,['-m','uvicorn','gateway.main:app','--port','8191'],path.join(root,'public-api'),{...minimal,DATABASE_URL:env.DATABASE_URL})
 start(python,['-m','uvicorn','control.main:app','--port','8192'],path.join(root,'admin-api'),env)
 start('npm',['run','dev','--','--port','8193'],path.join(root,'admin-web'),{...minimal,ADMIN_API_TARGET:'http://127.0.0.1:8192'})
 start('npm',['run','dev','--','--port','8194'],path.join(root,'user-web'),{...minimal,PUBLIC_API_TARGET:'http://127.0.0.1:8191'})
 await Promise.all(['http://127.0.0.1:8191/health','http://127.0.0.1:8192/health','http://127.0.0.1:8193','http://127.0.0.1:8194'].map(ready))
 browser=await chromium.launch({headless:true})
 const user=await browser.newPage({viewport:{width:1440,height:1000}})
 const admin=await browser.newPage({viewport:{width:1440,height:1100}})
 const errors=[];for(const p of [user,admin])p.on('pageerror',e=>errors.push(e.message))
 await user.goto('http://127.0.0.1:8194')
 await user.getByRole('button',{name:'企业邮箱登录 / 注册'}).click()
 await user.getByRole('button',{name:'创建账号'}).click()
 await expect(user.getByText('@star-net.cn',{exact:true})).toBeVisible()
 await user.getByLabel('企业邮箱前缀',{exact:true}).fill('intruder@example.com')
 if(await user.getByLabel('企业邮箱前缀',{exact:true}).evaluate(el=>el.checkValidity()))throw Error('Foreign domain accepted by registration field')
 await user.getByLabel('企业邮箱前缀',{exact:true}).fill('portal_acceptance')
 await user.getByLabel('密码',{exact:true}).fill('Synthetic-password-123')
 await user.getByRole('button',{name:'注册',exact:true}).click()
 await expect(user.getByRole('status')).toContainText('注册成功')
 await user.getByLabel('密码',{exact:true}).fill('Synthetic-password-123')
 await user.getByRole('button',{name:'登录',exact:true}).click()
 await expect(user.getByText('尚未分配 API Key，请等待管理员生成与绑定。')).toBeVisible()
 await admin.goto('http://127.0.0.1:8193')
 await admin.getByLabel('用户名',{exact:true}).fill('admin')
 await admin.getByLabel('密码',{exact:true}).fill(env.ADMIN_PASSWORD)
 await admin.getByRole('button',{name:'登录',exact:true}).click()
 await admin.getByRole('button',{name:'模型供应商',exact:true}).click()
 await admin.getByRole('button',{name:'登记验收',exact:true}).click()
 await admin.getByLabel('验收工单 ID',{exact:true}).fill('missing-fixture-job')
 await admin.getByLabel('验收记录',{exact:true}).fill('Synthetic browser guard test; no model call')
 await admin.getByLabel('已核对请求尺寸、画质、时长等规格',{exact:true}).check()
 await admin.getByLabel('已检查实际产物与请求是否一致',{exact:true}).check()
 await admin.getByLabel('已核对归因和实际用量记录',{exact:true}).check()
 await admin.getByRole('button',{name:'登记验收通过',exact:true}).click()
 await expect(admin.getByRole('alert')).toContainText('successful attributed acceptance job')
 await admin.getByRole('button',{name:'取消验收登记',exact:true}).click()
 await admin.getByRole('button',{name:'配置预估费用',exact:true}).click()
 await admin.getByLabel('默认文本输出 Token',{exact:true}).fill('256')
 await admin.getByLabel('费用调整倍率',{exact:true}).fill('1.25')
 await admin.getByLabel('预估计价规则 JSON',{exact:true}).fill(JSON.stringify([{conditions:{},rates:[{label:'输出',path:'output_tokens',unit:1000000,cny:20}]}]))
 await admin.getByRole('button',{name:'保存预估配置',exact:true}).click()
 await expect(admin.getByRole('status')).toContainText('预估配置已保存')
 await admin.getByRole('button',{name:'配置预估费用',exact:true}).click()
 await expect(admin.getByLabel('默认文本输出 Token',{exact:true})).toHaveValue('256')
 await admin.getByRole('button',{name:'关闭',exact:true}).click()
 await admin.getByRole('button',{name:'用户与积分',exact:true}).click()
 await expect(admin.getByLabel('注册用户',{exact:true}).locator('option')).toHaveCount(2)
 await admin.getByLabel('注册用户',{exact:true}).selectOption({label:await admin.getByLabel('注册用户',{exact:true}).locator('option').last().textContent()})
 await admin.getByLabel('Key 名称',{exact:true}).fill('浏览器验收 Key')
 await admin.getByLabel('每月积分额度',{exact:true}).fill('1000')
 await admin.getByRole('button',{name:'生成并绑定 Key'}).click()
 await expect(admin.getByText('仅展示一次，请通过安全渠道交付给所属用户。')).toBeVisible()
 await admin.getByRole('button',{name:'已保存，隐藏'}).click()
 await expect(admin.getByLabel('选择操作 Key',{exact:true}).locator('option')).toHaveCount(2)
 await admin.getByLabel('选择操作 Key',{exact:true}).selectOption({label:await admin.getByLabel('选择操作 Key',{exact:true}).locator('option').last().textContent()})
 await admin.getByLabel('调整积分（正数增加、负数扣减）').fill('20')
 await admin.getByLabel('原因',{exact:true}).fill('验收：临时增加积分')
 await admin.getByRole('button',{name:'记录并执行调整'}).click()
 await expect(admin.getByRole('cell',{name:'验收：临时增加积分',exact:false})).toBeVisible()
 await admin.getByLabel('调整积分（正数增加、负数扣减）').fill('-5')
 await admin.getByLabel('原因',{exact:true}).fill('验收：临时扣减积分')
 await admin.getByRole('button',{name:'记录并执行调整'}).click()
 await expect(admin.getByRole('cell',{name:'验收：临时扣减积分',exact:false})).toBeVisible()
 await admin.getByRole('button',{name:'生成方式费率',exact:true}).click()
 await admin.getByLabel('模型',{exact:true}).selectOption('gpt-5.6-sol')
 await admin.getByLabel('生成方式',{exact:true}).selectOption('chat')
 await admin.getByLabel('费率来源 / 合同版本').fill('隔离验收数据库虚构费率，仅用于测试')
 await admin.getByLabel('单任务预占积分').fill('50')
 await admin.getByRole('button',{name:'增加计价项'}).click()
 await admin.getByLabel('人民币单价',{exact:true}).fill('2')
 await admin.getByText('确认适用费率并启用此规则',{exact:true}).click()
 await admin.getByRole('button',{name:'发布新版本'}).click()
 await expect(admin.getByText('chat · 全部规格 · 已发布',{exact:true})).toBeVisible()
 command(['-c',`
import asyncio, uuid
from sqlalchemy import select
from gateway.db import Session, Job, Client, Model
from gateway.credits import lock, reserve
from gateway.queue import update
async def main():
 async with Session.begin() as db:
  await lock(db)
  c=await db.scalar(select(Client).where(Client.name=='浏览器验收 Key'))
  m=await db.get(Model,'gpt-5.6-sol')
  j=Job(id='fixture-browser-job',client_id=c.id,user_id=c.user_id,model_id=m.id,kind='chat',channel=m.channel,protocol=m.protocol,payload={'messages':[{'role':'user','content':'Synthetic fixture; no upstream request'}]},request_hash='fixture',idempotency_key='fixture',origin='agent_test',agent_name='code-agent',agent_run_id='portal-browser',test_run_id='portal-browser')
  await reserve(db,c,j,m)
  db.add(j)
 await update('fixture-browser-job',status='succeeded',usage={'completion_tokens':100000})
asyncio.run(main())
`],{PYTHONPATH:path.join(root,'public-api')})
 await user.getByRole('button',{name:'刷新',exact:true}).click()
 await expect(user.getByText('995.000000',{exact:true})).toBeVisible()
 await expect(user.getByRole('cell').filter({hasText:'按用量计价'})).toBeVisible()
 await expect(user.getByText('临时增加',{exact:true})).toBeVisible()
 await expect(user.getByText('临时扣减',{exact:true})).toBeVisible()
 await user.screenshot({path:path.join(root,'.runtime/portal-account.png'),fullPage:true})
 await user.getByRole('button',{name:'API 文档',exact:true}).click()
 await user.getByLabel('模型类型',{exact:true}).selectOption('text')
 await user.getByLabel('选择模型',{exact:true}).selectOption('gpt-5.6-sol')
 // Model catalog is deliberately cached in this page until refresh; fetch latest document rules.
 await user.reload()
 await user.getByLabel('模型类型',{exact:true}).selectOption('text')
 await user.getByLabel('选择模型',{exact:true}).selectOption('gpt-5.6-sol')
 await expect(user.getByText('200 积分 / 1000000',{exact:true})).toBeVisible()
 await user.screenshot({path:path.join(root,'.runtime/portal-docs.png'),fullPage:true})
 await admin.screenshot({path:path.join(root,'.runtime/admin-pricing.png'),fullPage:true})
 if(errors.length)throw Error(errors.join('\n'))
 fs.writeFileSync(path.join(root,'.runtime/portal-browser.json'),JSON.stringify({run,database:dbPath,passed:true,model_calls:0,assertions:['register/login','admin-only binding','monthly grant','manual credit/debit','mode pricing','measured task charge','private account view','public pricing docs']},null,2))
 console.log('Portal/admin isolated browser acceptance passed; zero model calls')
} finally {
 if(browser)await browser.close()
 for(const p of processes){try{process.kill(-p.pid,'SIGTERM')}catch{}}
}
