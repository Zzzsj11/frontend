import assert from 'node:assert/strict'
import test from 'node:test'
import { modelDocs } from '../user-web/src/utils/modelDocs.ts'
const model = (id, kind, native='') => ({id,kind,capabilities:{native_endpoint:native},enabled:false,pricing:[]})
test('调用示例使用当前统一 API，按文本协议选择请求字段',()=>{
 const claude=modelDocs(model('claude-opus-4-8','chat','/v1/messages'))
 assert.equal(claude.path,'/v1/messages')
 assert.match(claude.examples[0].code,/max_tokens/)
 const responses=modelDocs(model('responses-model','chat','/v1/responses'))
 assert.equal(responses.path,'/v1/responses')
 assert.match(responses.examples[0].code,/max_output_tokens/)
 for(const [kind,path] of [['image','/v1/images'],['video','/v1/videos']]){
  const docs=modelDocs(model('fixture',kind))
  assert.equal(docs.path,path)
  assert.match(docs.examples[0].code,/Idempotency-Key/)
  assert.match(docs.examples[1].code,/estimate_only/)
  assert.doesNotMatch(docs.examples[1].code,/Idempotency-Key/)
  assert.match(docs.examples[2].code,/\/v1\/jobs\/TASK_ID/)
  assert.match(docs.examples[0].code,/\$MODEL_API_KEY/)
 }
 assert.equal(modelDocs(model('custom','text')).examples.length,0)
})

test('复制的命令对模型名中的 shell 单引号做转义',()=>{
 const code=modelDocs(model("fixture'quoted",'image')).examples[0].code
 assert.ok(code.includes("fixture'\"'\"'quoted"))
})
