# v1 API / Python 合约

所有 HTTP JSON 为直接对象/数组，不包装 data。错误 HTTP 400/409，正文 detail 字符串。服务在 loopback，静态页 /，接口 /api。ID 为安全 ASCII token，任何客户端路径不作为文件路径。

## 数据层 app/data_service.py

`DataService(root)` root 为 workspace/system_v1。`list_datasets()->list[dict]`, `get_dataset(id)->dict`, `load_market(id)->DataFrame`, `protocol_template(id)->dict`, `prepare_research_snapshot(id, protocol, destination)->manifest`。
数据字典至少包含 id/name/start/end/latest_complete_date/rows/code_count/session_count/data_mode/status/fields/filters/quality/universe。filters 是各字段 dict（enabled, reason, unit），推荐 board/listing_days/amount/turnover；finance/industry/market_cap 默认禁用。market 含内核列和 available_at，以及可核验的 name/board/listing_days/turnover 属性；unsupported 可以不存在。`import_raw_500(source, codes_source, root, progress=None)` CLI 可调用，返回数据字典。数据源hash与输入列完整记录，禁写旧缓存。

## 模型及选股 app/models.py

`ModelService(root, data_service)`；`list_models()->list`, `get_model(version_id)->dict`, `register_run(run_root, dataset_id, name=None)->dict`, `update_metadata(version_id, changes)->dict`, `set_status(version_id,status)->dict`（candidate/available/disabled，人工 API 显式调用）、`select(config)->dict`, `list_results()->list`, `get_result(id)->dict`, `save_plan(body)->dict`, `list_plans()->list`, `get_plan(id)->dict`。
config `{model_version, dataset_id, filters:{board:[], listing_days:{min,max},amount:{min,max},turnover:{min,max}},top_n}`；默认 dataset_id 可省略取模型数据。结果 `{id,created_at,model_version,model_name,dataset_id,data_date,config,counts,rows,evaluation_note}`；rows 包含 code/name/score/rank/contributions（expression/weight/raw/standardized/contribution/missing）及可用属性。counts 至少 scoring_universe/basic_eligible/coverage/after_filter/selected。拒绝未知/禁用过滤，范围含边界，空值不通过。精确版本禁用不得计算。模型列表包含 version_id/name/status/evaluation/data_ready/blocked_reason/weights/dataset_id/data_date/source，只返回合理摘要不暴露磁盘路径。
方案 `{id,name,revision,config,created_at,parent_id?}`；修改另存 revision 不覆盖。模型包不可变，元数据修改另有审计。独立评分不依赖 run 可变状态/PPO，复用已检验 ExpressionSpace 和 scoring.score。

## HTTP（主 agent 实现）

- GET /api/overview → datasets/models/experiments/jobs/counts 摘要
- GET /api/datasets；GET /api/datasets/{id}；GET /api/datasets/{id}/protocol
- GET/POST /api/projects（name,question）；GET /api/experiments；POST /api/experiments `{name,project_id,dataset_id,protocol}` → 实验草稿
- GET /api/experiments/{id} → `{id,name,project_id,dataset_id,status,protocol,run_status,trials,pools,updates,selection,test,model_version}`
- POST /api/experiments/{id}/{start,pause,resume,stop,test} → job/实验状态。start 锁协议，finish 自动 select_model/register_run，test 单独。
- GET /api/models；GET /api/models/{version}；PATCH /api/models/{version}；POST /api/models/{version}/status `{status}`
- POST /api/selections `{config}` → `{id,status,kind,...}` 后台 job；GET /api/jobs/{id} 等待 result_id；GET /api/jobs
- GET /api/results；GET /api/results/{id}；GET /api/results/{id}/csv（全结果导出）
- GET/POST /api/plans；GET /api/plans/{id}
- GET/PATCH /api/settings → 本地偏好，不包含密钥；GET /api/help

界面首选研究 workspace，本地记住导航；可用模型才可生成，候选在模型管理显式开放。选股页面固定提交 config，编辑表单不改已有结果；显示实际日期及过期提示；原始模型绩效仅附协议区间，不套用用户过滤。
