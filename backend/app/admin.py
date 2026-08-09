from __future__ import annotations
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from .auth import CurrentUser, user_public
from .database import database_session
from .models import AdminOperationLogModel, AiModelModel, AiProviderModel, ApiErrorLogModel, DigitalHumanModel, GenerationJobModel, ProjectModel, TokenUsageModel, UserModel

router = APIRouter(prefix="/api/admin", tags=["admin"])
Db = Depends(database_session)
def require_admin(user):
    if user.role != "admin": raise HTTPException(403, "需要管理员权限")
def iso(value): return value.isoformat() if value else None
async def audit(db, request, user, action, target_type, target_id=None, before=None, after=None):
    db.add(AdminOperationLogModel(id=f"audit-{uuid.uuid4().hex}",admin_user_id=user.id,action=action,target_type=target_type,target_id=target_id,before_data=before or {},after_data=after or {},client_ip=request.client.host if request.client else None))

@router.get("/dashboard")
async def dashboard(user:CurrentUser, db:AsyncSession=Db):
    require_admin(user)
    async def count(model, *where): return (await db.execute(select(func.count()).select_from(model).where(model.deleted_at.is_(None),*where))).scalar_one()
    usage=(await db.execute(select(func.coalesce(func.sum(TokenUsageModel.input_tokens),0),func.coalesce(func.sum(TokenUsageModel.output_tokens),0),func.coalesce(func.sum(TokenUsageModel.total_tokens),0)).where(TokenUsageModel.deleted_at.is_(None)))).one()
    statuses=dict((await db.execute(select(GenerationJobModel.status,func.count()).where(GenerationJobModel.deleted_at.is_(None)).group_by(GenerationJobModel.status))).all())
    return {"users":await count(UserModel),"projects":await count(ProjectModel),"jobs":await count(GenerationJobModel),"systemHumans":await count(DigitalHumanModel,DigitalHumanModel.scope=="system"),"errors":await count(ApiErrorLogModel),"usage":{"inputTokens":usage[0],"outputTokens":usage[1],"totalTokens":usage[2]},"jobStatuses":statuses}

@router.get("/projects")
async def projects(user:CurrentUser, db:AsyncSession=Db):
    require_admin(user); rows=(await db.execute(select(ProjectModel,UserModel.username).join(UserModel,UserModel.id==ProjectModel.user_id).where(ProjectModel.deleted_at.is_(None)).order_by(ProjectModel.created_at.desc()).limit(300))).all()
    return [{"id":p.id,"name":p.name,"username":u,"status":p.status,"createdAt":iso(p.created_at)} for p,u in rows]

@router.get("/jobs")
async def jobs(user:CurrentUser, db:AsyncSession=Db):
    require_admin(user); rows=(await db.execute(select(GenerationJobModel).where(GenerationJobModel.deleted_at.is_(None)).order_by(GenerationJobModel.created_at.desc()).limit(300))).scalars()
    return [{"id":j.id,"userId":j.user_id,"kind":j.kind,"status":j.status,"provider":j.provider,"error":j.error,"createdAt":iso(j.created_at)} for j in rows]

@router.get("/usage")
async def usage(user:CurrentUser, db:AsyncSession=Db):
    require_admin(user); rows=(await db.execute(select(TokenUsageModel.model,TokenUsageModel.provider,func.sum(TokenUsageModel.input_tokens),func.sum(TokenUsageModel.output_tokens),func.sum(TokenUsageModel.total_tokens),func.count()).where(TokenUsageModel.deleted_at.is_(None)).group_by(TokenUsageModel.model,TokenUsageModel.provider))).all()
    return [{"model":r[0],"provider":r[1],"inputTokens":r[2] or 0,"outputTokens":r[3] or 0,"totalTokens":r[4] or 0,"calls":r[5]} for r in rows]

class ProviderIn(BaseModel):
    code:str=Field(min_length=1,max_length=80); name:str=Field(min_length=1,max_length=120); base_url:str=""; status:str="active"
class ModelIn(BaseModel):
    provider_id:str; code:str=Field(min_length=1,max_length=160); name:str; modality:str; provider_model_id:str; capabilities:dict={}; status:str="active"; user_visible:bool=True; is_default:bool=False

@router.get("/providers")
async def providers(user:CurrentUser,db:AsyncSession=Db):
    require_admin(user); rows=(await db.execute(select(AiProviderModel).where(AiProviderModel.deleted_at.is_(None)).order_by(AiProviderModel.name))).scalars()
    return [{"id":x.id,"code":x.code,"name":x.name,"baseUrl":x.base_url,"status":x.status} for x in rows]
@router.post("/providers",status_code=201)
async def create_provider(payload:ProviderIn,request:Request,user:CurrentUser,db:AsyncSession=Db):
    require_admin(user); item=AiProviderModel(id=f"provider-{uuid.uuid4().hex}",code=payload.code,name=payload.name,base_url=payload.base_url,status=payload.status);db.add(item);await audit(db,request,user,"provider.create","ai_provider",item.id,after=payload.model_dump());await db.commit();return {"id":item.id}
@router.get("/models")
async def models(user:CurrentUser,db:AsyncSession=Db):
    require_admin(user); rows=(await db.execute(select(AiModelModel).where(AiModelModel.deleted_at.is_(None)).order_by(AiModelModel.modality,AiModelModel.sort_order))).scalars()
    return [{"id":x.id,"providerId":x.provider_id,"code":x.code,"name":x.name,"modality":x.modality,"providerModelId":x.provider_model_id,"capabilities":x.capabilities,"status":x.status,"userVisible":x.user_visible,"isDefault":x.is_default} for x in rows]
@router.post("/models",status_code=201)
async def create_model(payload:ModelIn,request:Request,user:CurrentUser,db:AsyncSession=Db):
    require_admin(user); item=AiModelModel(id=f"model-{uuid.uuid4().hex}",**payload.model_dump());db.add(item);await audit(db,request,user,"model.create","ai_model",item.id,after=payload.model_dump());await db.commit();return {"id":item.id}
@router.patch("/models/{model_id}")
async def update_model(model_id:str,payload:dict,request:Request,user:CurrentUser,db:AsyncSession=Db):
    require_admin(user);item=await db.get(AiModelModel,model_id)
    if not item or item.deleted_at: raise HTTPException(404,"模型不存在")
    allowed={"name","status","user_visible","is_default","capabilities","sort_order"};before={k:getattr(item,k) for k in allowed}
    for k,v in payload.items():
        if k in allowed:setattr(item,k,v)
    await audit(db,request,user,"model.update","ai_model",item.id,before,payload);await db.commit();return {"ok":True}
@router.get("/audit-logs")
async def audits(user:CurrentUser,db:AsyncSession=Db):
    require_admin(user);rows=(await db.execute(select(AdminOperationLogModel).where(AdminOperationLogModel.deleted_at.is_(None)).order_by(AdminOperationLogModel.created_at.desc()).limit(300))).scalars()
    return [{"id":x.id,"adminUserId":x.admin_user_id,"action":x.action,"targetType":x.target_type,"targetId":x.target_id,"createdAt":iso(x.created_at)} for x in rows]

public_router=APIRouter(prefix="/api")
@public_router.get("/model-options")
async def model_options(user:CurrentUser,modality:str|None=None,db:AsyncSession=Db):
    query=select(AiModelModel).where(AiModelModel.deleted_at.is_(None),AiModelModel.status=="active",AiModelModel.user_visible.is_(True))
    if modality:query=query.where(AiModelModel.modality==modality)
    rows=(await db.execute(query.order_by(AiModelModel.modality,AiModelModel.sort_order))).scalars()
    return [{"id":x.code,"name":x.name,"modality":x.modality,"capabilities":x.capabilities,"isDefault":x.is_default} for x in rows]
