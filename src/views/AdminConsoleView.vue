<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { apiRequest } from '../api/client'
type Tab='dashboard'|'users'|'projects'|'jobs'|'usage'|'models'|'errors'|'audit'
const tab=ref<Tab>('dashboard'), loading=ref(false), error=ref(''), data=ref<any>(null)
const tabs:[Tab,string][]=[['dashboard','仪表盘'],['users','用户'],['projects','项目'],['jobs','生成任务'],['usage','费用用量'],['models','模型管理'],['errors','错误日志'],['audit','操作审计']]
const endpoint=computed(()=>({dashboard:'/admin/dashboard',users:'/admin/users',projects:'/admin/projects',jobs:'/admin/jobs',usage:'/admin/usage',models:'/admin/models',errors:'/admin/api-errors',audit:'/admin/audit-logs'}[tab.value]))
const rows=computed<any[]>(()=>Array.isArray(data.value)?data.value:(data.value?.items||[]))
const load=async()=>{loading.value=true;error.value='';try{data.value=await apiRequest(endpoint.value)}catch(e){error.value=e instanceof Error?e.message:'加载失败'}finally{loading.value=false}}
const select=async(value:Tab)=>{tab.value=value;await load()}
const toggleModel=async(row:any)=>{await apiRequest(`/admin/models/${row.id}`,{method:'PATCH',body:JSON.stringify({status:row.status==='active'?'disabled':'active'})});await load()}
const columns=computed(()=>rows.value.length?Object.keys(rows.value[0]).filter(k=>!['capabilities','traceback','requestPayload'].includes(k)):[])
onMounted(load)
</script>
<template>
  <div class="console">
    <aside><div class="brand">映刻 MV<br><small>管理控制台 v0.1</small></div><button v-for="item in tabs" :key="item[0]" :class="{on:tab===item[0]}" @click="select(item[0])">{{item[1]}}</button><RouterLink to="/projects">← 返回工作台</RouterLink></aside>
    <main><header><div><h1>{{tabs.find(x=>x[0]===tab)?.[1]}}</h1><p>MV AI 生产平台运营与模型控制中心</p></div><button class="refresh" @click="load">刷新</button></header>
      <p v-if="error" class="error">{{error}}</p><p v-if="loading">加载中…</p>
      <section v-else-if="tab==='dashboard'&&data" class="cards">
        <article><b>{{data.users}}</b><span>用户</span></article><article><b>{{data.projects}}</b><span>项目</span></article><article><b>{{data.jobs}}</b><span>生成任务</span></article><article><b>{{data.systemHumans}}</b><span>系统人物</span></article><article><b>{{data.errors}}</b><span>错误记录</span></article><article><b>{{data.usage?.totalTokens||0}}</b><span>累计 Token</span></article>
        <article class="wide"><h3>任务状态</h3><pre>{{JSON.stringify(data.jobStatuses,null,2)}}</pre></article><article class="wide"><h3>Token 构成</h3><p>输入 {{data.usage?.inputTokens||0}} / 输出 {{data.usage?.outputTokens||0}}</p></article>
      </section>
      <section v-else class="table-wrap"><table><thead><tr><th v-for="c in columns" :key="c">{{c}}</th><th v-if="tab==='models'">操作</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id||row.model"><td v-for="c in columns" :key="c"><span :class="{status:c==='status'}">{{typeof row[c]==='object'?JSON.stringify(row[c]):row[c]}}</span></td><td v-if="tab==='models'"><button class="action" @click="toggleModel(row)">{{row.status==='active'?'停用':'启用'}}</button></td></tr></tbody></table><p v-if="!rows.length" class="empty">暂无数据</p></section>
    </main>
  </div>
</template>
<style scoped>
.console{min-height:100vh;background:#f6f7f9;display:grid;grid-template-columns:220px 1fr;color:#25262a}aside{background:#17191d;color:#fff;padding:24px 14px;display:flex;flex-direction:column;gap:7px}.brand{font-size:19px;font-weight:700;padding:8px 10px 25px}.brand small{font-size:11px;color:#999;font-weight:400}aside button,aside a{border:0;background:transparent;color:#aaa;text-align:left;padding:11px 13px;border-radius:8px;text-decoration:none;cursor:pointer}aside button.on,aside button:hover{background:#ff5a2c;color:#fff}aside a{margin-top:auto}main{padding:30px;min-width:0}header{display:flex;justify-content:space-between;align-items:center;margin-bottom:25px}h1{margin:0;font-size:25px}header p{margin:6px 0;color:#888}.refresh,.action{border:0;border-radius:7px;background:#ff5a2c;color:#fff;padding:8px 14px;cursor:pointer}.cards{display:grid;grid-template-columns:repeat(3,minmax(160px,1fr));gap:16px}.cards article{background:#fff;border:1px solid #e8e8eb;border-radius:12px;padding:22px;display:flex;flex-direction:column}.cards b{font-size:30px;color:#ff5a2c}.cards span{color:#777;margin-top:8px}.cards .wide{grid-column:span 3}.table-wrap{overflow:auto;background:#fff;border:1px solid #e8e8eb;border-radius:12px}table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:12px 14px;border-bottom:1px solid #eee;text-align:left;white-space:nowrap;max-width:340px;overflow:hidden;text-overflow:ellipsis}th{background:#fafafa;color:#777}.status{padding:3px 7px;background:#eef8ef;border-radius:10px}.empty,.error{padding:20px}.error{color:#c33}
</style>
